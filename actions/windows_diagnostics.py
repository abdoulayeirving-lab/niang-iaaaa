"""Read-only, bounded Windows diagnostics for the local NIANG IA session."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from actions.windows_process import WindowsProcessCancelled, run_windows_process

try:
    import psutil
except ImportError:
    psutil = None


_HISTORY_LOCK = threading.Lock()
_MAX_HISTORY_ITEMS = 50
_DEFAULT_TIMEOUT_SECONDS = 45
_EVENT_QUERY_TIMEOUT_SECONDS = 45
_EVENT_SYSTEM_TIMEOUT_SECONDS = 45
_EVENT_APPLICATION_TIMEOUT_SECONDS = 45
_EVENT_PAGE_SIZE = 100
_EVENT_MAX_RESULTS_PER_LOG = 100
_EVENT_PAGE_DAYS = 1
_EVENT_WINDOW_DAYS = 1
_DISM_SCAN_TIMEOUT_SECONDS = 1800
_SFC_VERIFY_TIMEOUT_SECONDS = 900
_PERFORMANCE_MONITOR_SECONDS = 300
_PERFORMANCE_SAMPLE_INTERVAL_SECONDS = 5


class DiagnosticCancelled(RuntimeError):
    """A diagnostic subprocess was stopped before it finished."""

_POWERSHELL_SCRIPTS = {
    "temperature": r"""
$ErrorActionPreference = 'Stop'
$values = @(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue |
    ForEach-Object { [math]::Round(($_.CurrentTemperature / 10) - 273.15, 1) } |
    Where-Object { $_ -ge 0 -and $_ -le 120 })
$temperature = $null
if ($values.Count -gt 0) { $temperature = [math]::Round(($values | Measure-Object -Average).Average, 1) }
[pscustomobject]@{ Celsius = $temperature; SensorCount = $values.Count } | ConvertTo-Json -Compress
""",
    "windows": r"""
$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, LastBootUpTime
$hotfixes = @(Get-HotFix -ErrorAction SilentlyContinue | Sort-Object InstalledOn -Descending | Select-Object -First 10 HotFixID, InstalledOn)
$pendingCount = $null
$pendingTitles = @()
$updateError = $null
try {
    $session = New-Object -ComObject Microsoft.Update.Session
    $search = $session.CreateUpdateSearcher().Search("IsInstalled=0 and Type='Software'")
    $pendingCount = [int]$search.Updates.Count
    for ($i = 0; $i -lt [Math]::Min($pendingCount, 10); $i++) {
        $pendingTitles += [string]$search.Updates.Item($i).Title
    }
} catch {
    $updateError = 'Windows Update search unavailable'
}
[pscustomobject]@{ OS = $os; RecentUpdates = $hotfixes; PendingUpdateCount = $pendingCount; PendingUpdateTitles = $pendingTitles; UpdateError = $updateError } | ConvertTo-Json -Depth 5 -Compress
""",
    "drivers": r"""
$ErrorActionPreference = 'Stop'
$gpus = @(Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue | Select-Object Name, DriverVersion, Status)
$amdDrivers = @(Get-CimInstance Win32_PnPSignedDriver -ErrorAction SilentlyContinue |
    Where-Object { $_.DeviceName -match 'AMD|Radeon' } |
    Select-Object DeviceName, DriverProviderName, DriverVersion, DriverDate, IsSigned)
$pnpAvailable = [bool](Get-Command Get-PnpDevice -ErrorAction SilentlyContinue)
$problemDevices = @()
if ($pnpAvailable) {
    $problemDevices = @(Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | Where-Object { $_.Status -ne 'OK' } | Select-Object -First 30 Class, FriendlyName, Status, Problem)
}
$physicalDisks = @()
try {
    foreach ($disk in (Get-PhysicalDisk -ErrorAction Stop)) {
        $temperature = $null
        $counter = $null
        try {
            $counter = $disk | Get-StorageReliabilityCounter -ErrorAction Stop
            $temperature = $counter.Temperature
        } catch { }
        $physicalDisks += [pscustomobject]@{
            Name = $disk.FriendlyName
            HealthStatus = [string]$disk.HealthStatus
            OperationalStatus = (@($disk.OperationalStatus) -join ', ')
            SizeBytes = [int64]$disk.Size
            TemperatureC = $temperature
            Wear = $counter.Wear
            ReadErrorsTotal = $counter.ReadErrorsTotal
            WriteErrorsTotal = $counter.WriteErrorsTotal
            PowerOnHours = $counter.PowerOnHours
        }
    }
} catch { }
$batteries = @(Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue |
    Select-Object Name, BatteryStatus, EstimatedChargeRemaining, DesignVoltage, Status)
$fans = @(Get-CimInstance Win32_Fan -ErrorAction SilentlyContinue |
    Select-Object Name, Status, DesiredSpeed, VariableSpeed)
[pscustomobject]@{
    GPUs = $gpus
    AmdDrivers = $amdDrivers
    PnpAvailable = $pnpAvailable
    ProblemDevices = $problemDevices
    PhysicalDisks = $physicalDisks
    Batteries = $batteries
    Fans = $fans
    GpuTemperatureC = $null
    GpuTemperatureNote = 'No standard Windows sensor exposed a GPU temperature.'
} | ConvertTo-Json -Depth 5 -Compress
""",
    "services": r"""
$ErrorActionPreference = 'Stop'
$services = @(Get-CimInstance Win32_Service -ErrorAction Stop |
    Where-Object { $_.StartMode -eq 'Auto' -and $_.State -ne 'Running' } |
    Select-Object -First 40 Name, DisplayName, State, StartMode)
[pscustomobject]@{ AutoStartStopped = $services } | ConvertTo-Json -Depth 4 -Compress
""",
    "network": r"""
$ErrorActionPreference = 'Stop'
$adapters = @(Get-NetAdapter -ErrorAction Stop | Select-Object Name, InterfaceDescription, Status, LinkSpeed)
$configs = @(Get-NetIPConfiguration -ErrorAction SilentlyContinue | ForEach-Object {
    [pscustomobject]@{
        Name = $_.InterfaceAlias
        HasIPv4Gateway = [bool]$_.IPv4DefaultGateway
        HasDnsServer = [bool]$_.DnsServer
    }
})
[pscustomobject]@{ Adapters = $adapters; Configurations = $configs } | ConvertTo-Json -Depth 4 -Compress
""",
}

_CATEGORY_TO_SCRIPT = {
    "windows": "windows",
    "drivers": "drivers",
    "services": "services",
    "network": "network",
}

_CATEGORY_LABELS = {
    "overview": "Full PC overview",
    "performance": "Performance snapshot",
    "performance_monitor_5m": "Five-minute performance monitoring",
    "windows": "Windows and update status",
    "drivers": "Drivers, devices, and storage health",
    "services": "Windows services",
    "network": "Network adapter status",
    "errors": "Recent Windows event summaries",
    "system_files": "System file integrity checks",
    "errors": "Recent Windows event summaries",
}


def _system_executable(relative_path: str) -> str:
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise RuntimeError("The Windows SystemRoot environment variable is unavailable.")
    executable = Path(system_root) / "System32" / relative_path
    if not executable.is_file():
        raise RuntimeError(f"Required Windows component is unavailable: {relative_path}.")
    return str(executable)


def _history_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return root / "NIANG IA" / "diagnostics" / "history.json"


def _reports_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return root / "NIANG IA" / "diagnostics" / "reports"


def _run_process(
    command: list[str],
    timeout_seconds: int,
    cancel_event: threading.Event | None = None,
) -> subprocess.CompletedProcess:
    try:
        return run_windows_process(command, timeout_seconds, cancel_event)
    except WindowsProcessCancelled as exc:
        raise DiagnosticCancelled(str(exc)) from exc


def _powershell(
    script: str,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    cancel_event: threading.Event | None = None,
) -> Any:
    if platform.system() != "Windows":
        raise RuntimeError("Windows diagnostics are available only on Windows.")

    command = [
        _system_executable(r"WindowsPowerShell\v1.0\powershell.exe"),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); " + script,
    ]
    result = _run_process(command, timeout_seconds, cancel_event)
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            f"PowerShell diagnostic failed (exit {result.returncode})"
            + (f": {detail[:300]}" if detail else ".")
        )
    output = result.stdout.strip()
    if not output:
        raise RuntimeError("PowerShell returned no diagnostic data.")
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("PowerShell returned invalid diagnostic JSON.") from exc


def _as_list(value: Any) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _check(
    name: str,
    status: str,
    details: Any,
    source: str,
    verification_state: str | None = None,
) -> dict:
    verification_states = {
        "issues_found": "problem_detected",
        "unavailable": "data_unavailable",
        "requires_administrator": "permission_refused",
        "permission_refused": "permission_refused",
        "unverified": "not_verified",
        "timeout": "not_verified",
        "error": "not_verified",
        "partial": "not_verified",
        "interrupted": "interrupted",
        "ok": "observed",
        "informational": "observed",
    }
    return {
        "name": name,
        "status": status,
        "verification_state": verification_state or verification_states.get(status, "not_verified"),
        "source": source,
        "details": details,
    }


def _make_finding(
    severity: str,
    problem: str,
    cause: str,
    solution: str,
    authorization_required: bool = False,
) -> dict:
    return {
        "severity": severity,
        "problem": problem,
        "likely_cause": cause,
        "recommended_solution": solution,
        "authorization_required": authorization_required,
        "repair_result": None,
    }


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(phrase.casefold() in lowered for phrase in phrases)


def _bounded_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _read_event_log(
    log_name: str,
    *,
    timeout_seconds: int | None = None,
    page_size: int | None = None,
    max_results: int | None = None,
    page_days: int | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    if log_name not in {"System", "Application"}:
        raise ValueError("Unsupported Windows event log.")
    env_timeout = (
        "NIANG_IA_DIAGNOSTIC_SYSTEM_EVENT_TIMEOUT_S"
        if log_name == "System"
        else "NIANG_IA_DIAGNOSTIC_APPLICATION_EVENT_TIMEOUT_S"
    )
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else _bounded_setting(env_timeout, _EVENT_QUERY_TIMEOUT_SECONDS, 5, 600)
    )
    page_size = (
        page_size
        if page_size is not None
        else _bounded_setting("NIANG_IA_DIAGNOSTIC_EVENT_PAGE_SIZE", _EVENT_PAGE_SIZE, 1, 500)
    )
    max_results = (
        max_results
        if max_results is not None
        else _bounded_setting("NIANG_IA_DIAGNOSTIC_EVENT_MAX_RESULTS", _EVENT_MAX_RESULTS_PER_LOG, 1, 2000)
    )
    page_days = 1
    if min(timeout, page_size, max_results) <= 0:
        raise ValueError("Event log query limits must be positive.")
    if timeout > 600 or page_size > 500 or max_results > 2000:
        raise ValueError("Event log query limits exceed the supported maximum.")
    script = f"""
$ErrorActionPreference = 'Stop'
$logName = '{log_name}'
$windowHours = 24
$windowDays = 1
$pageDays = 1
$pageSize = {page_size}
$maxResults = {max_results}
$windowStart = (Get-Date).AddHours(-$windowHours)
$events = [System.Collections.Generic.List[object]]::new()
$truncated = $false
$queryError = $null
$queryStatus = 'ok'
try {{
    $page = @(Get-WinEvent -FilterHashtable @{{ LogName=$logName; StartTime=$windowStart; Level=1,2 }} -MaxEvents $maxResults -ErrorAction Stop)
    foreach ($event in $page) {{
        $events.Add([pscustomobject]@{{
            LogName = $logName
            TimeCreated = $event.TimeCreated
            ProviderName = $event.ProviderName
            Id = $event.Id
            LevelDisplayName = $event.LevelDisplayName
            RecordId = $event.RecordId
        }})
    }}
    $truncated = $page.Count -ge $maxResults
}} catch {{
    if ($_.FullyQualifiedErrorId -notlike '*NoMatchingEventsFound*') {{
        $queryError = 'Windows event query failed.'
        if ($_.Exception.Message -match '740|access.*denied|unauthori|accès refusé|non autorisé') {{
            $queryStatus = 'permission_refused'
        }} else {{
            $queryStatus = 'not_verified'
        }}
    }}
}}
$ordered = @($events | Sort-Object TimeCreated -Descending | Select-Object -First $maxResults)
[pscustomobject]@{{
    LogName = $logName
    Events = $ordered
    WindowDays = $windowDays
    PageDays = $pageDays
    PageSize = $pageSize
    MaximumResults = $maxResults
    Truncated = $truncated
    QueryError = $queryError
    QueryStatus = $queryStatus
}} | ConvertTo-Json -Depth 4 -Compress
"""
    try:
        data = _powershell(script, timeout_seconds=timeout, cancel_event=cancel_event)
    except DiagnosticCancelled:
        raise
    except subprocess.TimeoutExpired as exc:
        return {
            "log_name": log_name,
            "events": [],
            "status": "timeout",
            "error": f"The {log_name} event query exceeded its {timeout}-second timeout.",
            "process_termination_confirmed": getattr(exc, "termination_confirmed", None),
        }
    except PermissionError:
        return {
            "log_name": log_name,
            "events": [],
            "status": "permission_refused",
            "error": "Windows denied access to this event log.",
        }
    except (OSError, RuntimeError) as exc:
        message = str(exc).casefold()
        if "740" in message or _contains_any(message, (
            "access is denied",
            "accès refusé",
            "unauthorized",
            "non autorisé",
            "permission",
        )):
            status = "permission_refused"
            error = "Windows denied access to this event log."
        else:
            status = "not_verified"
            error = f"The {log_name} event query could not be completed."
        return {"log_name": log_name, "events": [], "status": status, "error": error}

    events = _as_list(data.get("Events"))
    if data.get("QueryError"):
        status = data.get("QueryStatus", "not_verified")
    elif data.get("Truncated"):
        status = "partial"
    else:
        status = "ok"
    return {
        "log_name": log_name,
        "events": events,
        "window_days": data.get("WindowDays", _EVENT_WINDOW_DAYS),
        "page_days": data.get("PageDays", page_days),
        "page_size": data.get("PageSize", page_size),
        "maximum_results": data.get("MaximumResults", max_results),
        "status": status,
        "error": data.get("QueryError"),
    }


def _collect_performance(
    cancel_event: threading.Event | None = None,
) -> tuple[list[dict], list[dict]]:
    checks = []
    findings = []
    if psutil is None:
        checks.append(_check("Performance", "unavailable", "psutil is not installed.", "psutil"))
        return checks, findings

    cpu_percent = psutil.cpu_percent(interval=0.4)
    cpu_temperature = None
    try:
        for sensors in psutil.sensors_temperatures().values():
            for sensor in sensors:
                if sensor.current is not None and 0 <= sensor.current <= 120:
                    cpu_temperature = round(float(sensor.current), 1)
                    break
            if cpu_temperature is not None:
                break
    except (AttributeError, OSError, RuntimeError, NotImplementedError):
        pass
    temperature_source = "psutil sensor unavailable"
    if cpu_temperature is None and platform.system() == "Windows":
        try:
            temperature_data = _powershell(
                _POWERSHELL_SCRIPTS["temperature"],
                timeout_seconds=15,
                cancel_event=cancel_event,
            )
            value = temperature_data.get("Celsius")
            cpu_temperature = float(value) if value is not None else None
            temperature_source = (
                "ACPI thermal zone"
                if cpu_temperature is not None
                else "No supported ACPI temperature sensor was exposed."
            )
        except DiagnosticCancelled:
            raise
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            temperature_source = "Windows did not expose a readable temperature sensor."
    elif cpu_temperature is not None:
        temperature_source = "psutil sensor"

    memory = psutil.virtual_memory()
    disk_io = None
    try:
        disk_io = psutil.disk_io_counters()
    except (AttributeError, psutil.Error, OSError):
        disk_io = None
    disk_data = []
    seen_mounts = set()
    for partition in psutil.disk_partitions(all=False):
        mount = partition.mountpoint
        if not mount or mount in seen_mounts or partition.fstype.lower() == "cdrom":
            continue
        seen_mounts.add(mount)
        try:
            usage = psutil.disk_usage(mount)
        except (PermissionError, OSError):
            continue
        disk_data.append({
            "mount": mount,
            "total_bytes": int(usage.total),
            "free_bytes": int(usage.free),
            "used_percent": round(float(usage.percent), 1),
        })
        if usage.percent >= 95:
            findings.append(_make_finding(
                "high",
                f"Disk {mount} is critically full ({usage.percent:.1f}% used).",
                "The volume has very little free space.",
                "Review storage usage and remove only files you personally identify as safe to remove.",
                True,
            ))
        elif usage.percent >= 90:
            findings.append(_make_finding(
                "medium",
                f"Disk {mount} has low free space ({usage.percent:.1f}% used).",
                "The volume is nearing capacity.",
                "Review storage usage; do not delete system or personal files automatically.",
                True,
            ))

    process_summary = []
    skipped_process_count = 0
    process_scan_error = None
    try:
        for proc in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
            try:
                process_summary.append({
                    "name": proc.info.get("name") or "unknown",
                    "cpu_percent": round(float(proc.info.get("cpu_percent") or 0), 1),
                    "memory_percent": round(float(proc.info.get("memory_percent") or 0), 1),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                skipped_process_count += 1
                continue
    except (psutil.Error, OSError) as exc:
        process_scan_error = f"Process enumeration was incomplete: {type(exc).__name__}."
    process_summary.sort(key=lambda item: (item["cpu_percent"], item["memory_percent"]), reverse=True)

    if cpu_percent >= 95:
        findings.append(_make_finding(
            "high",
            f"CPU utilization is high ({cpu_percent:.1f}% during the sample).",
            "A process may be consuming CPU, or a short-lived workload is active.",
            "Review the process list and repeat the measurement before changing or stopping anything.",
        ))
    if memory.percent >= 90:
        findings.append(_make_finding(
            "high",
            f"Memory utilization is high ({memory.percent:.1f}%).",
            "Applications or background processes are using most available RAM.",
            "Review the process list and close only applications you recognize and choose to stop.",
        ))

    performance_details = {
        "cpu_percent_sample": round(float(cpu_percent), 1),
        "cpu_temperature_c": cpu_temperature,
        "cpu_temperature_source": temperature_source,
        "memory_total_bytes": int(memory.total),
        "memory_available_bytes": int(memory.available),
        "memory_used_percent": round(float(memory.percent), 1),
        "disks": disk_data,
        "disk_io": {
            "status": "available" if disk_io is not None else "unavailable",
            "read_bytes_total": int(disk_io.read_bytes) if disk_io is not None else None,
            "write_bytes_total": int(disk_io.write_bytes) if disk_io is not None else None,
            "read_count_total": int(disk_io.read_count) if disk_io is not None else None,
            "write_count_total": int(disk_io.write_count) if disk_io is not None else None,
            "read_latency_ms": None,
            "write_latency_ms": None,
            "active_time_ms": (
                int(disk_io.busy_time)
                if disk_io is not None and hasattr(disk_io, "busy_time")
                else None
            ),
            "source": "psutil" if disk_io is not None else "unavailable",
        },
        "unavailable_disk_count": max(0, len(seen_mounts) - len(disk_data)),
        "top_processes": process_summary[:10],
        "skipped_process_count": skipped_process_count,
        "process_scan_error": process_scan_error,
        "process_list_note": "Process command lines and executable paths are not collected.",
    }
    checks.append(_check("Performance", "ok", performance_details, "psutil"))
    checks.append(_check(
        "CPU temperature",
        "ok" if cpu_temperature is not None else "unavailable",
        {
            "temperature_c": cpu_temperature,
            "source": temperature_source,
        },
        "psutil / ACPI thermal zone",
        verification_state="observed" if cpu_temperature is not None else "data_unavailable",
    ))
    return checks, findings


def _performance_trend(values: list[float], tolerance: float) -> str:
    if len(values) < 4:
        return "insufficient_samples"
    quarter = max(1, len(values) // 4)
    first = sum(values[:quarter]) / quarter
    last = sum(values[-quarter:]) / quarter
    if last - first >= tolerance:
        return "rising"
    if first - last >= tolerance:
        return "falling"
    return "stable"


def _monitor_performance(
    *,
    duration_seconds: int = _PERFORMANCE_MONITOR_SECONDS,
    sample_interval_seconds: int = _PERFORMANCE_SAMPLE_INTERVAL_SECONDS,
    cancel_event: threading.Event | None = None,
    progress_callback=None,
) -> tuple[dict, list[dict], bool]:
    if not 10 <= duration_seconds <= _PERFORMANCE_MONITOR_SECONDS:
        raise ValueError(
            f"Performance monitoring duration must be between 10 and "
            f"{_PERFORMANCE_MONITOR_SECONDS} seconds."
        )
    if not 1 <= sample_interval_seconds <= 30:
        raise ValueError("Performance sample interval must be between 1 and 30 seconds.")
    if psutil is None:
        return {
            "status": "unavailable",
            "reason": "psutil is not installed.",
            "samples": [],
        }, [], False

    samples = []
    findings = []
    started = time.monotonic()
    deadline = started + duration_seconds
    last_sample = started
    try:
        previous_disk = psutil.disk_io_counters()
    except (psutil.Error, OSError):
        previous_disk = None
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)
    discard_first_sample = True
    interrupted = False

    while True:
        if cancel_event is not None and cancel_event.is_set():
            interrupted = True
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        wait_seconds = min(sample_interval_seconds, remaining)
        if cancel_event is not None:
            if cancel_event.wait(wait_seconds):
                interrupted = True
                break
        else:
            time.sleep(wait_seconds)

        sample_time = time.monotonic()
        elapsed = max(sample_time - last_sample, 0.001)
        memory = psutil.virtual_memory()
        try:
            disk = psutil.disk_io_counters()
        except (psutil.Error, OSError):
            disk = None
        cpu_percent = float(psutil.cpu_percent(interval=None))
        process_usage = []
        skipped_processes = 0
        try:
            for process in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
                try:
                    process_usage.append({
                        "name": process.info.get("name") or "unknown",
                        "cpu_percent": round(float(process.info.get("cpu_percent") or 0), 1),
                        "memory_percent": round(float(process.info.get("memory_percent") or 0), 1),
                    })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    skipped_processes += 1
        except (psutil.Error, OSError):
            skipped_processes += 1
        process_usage.sort(
            key=lambda item: (item["cpu_percent"], item["memory_percent"]),
            reverse=True,
        )

        disk_read_rate = None
        disk_write_rate = None
        if disk is not None and previous_disk is not None:
            disk_read_rate = max(0, disk.read_bytes - previous_disk.read_bytes) / elapsed
            disk_write_rate = max(0, disk.write_bytes - previous_disk.write_bytes) / elapsed
        previous_disk = disk
        cpu_per_core = []
        try:
            cpu_per_core = [
                round(float(value), 1)
                for value in psutil.cpu_percent(interval=None, percpu=True)
            ]
        except (AttributeError, psutil.Error, OSError):
            cpu_per_core = []
        if discard_first_sample:
            discard_first_sample = False
            last_sample = sample_time
            continue
        samples.append({
            "elapsed_seconds": round(sample_time - started, 1),
            "cpu_percent": round(cpu_percent, 1),
            "cpu_per_core_percent": cpu_per_core,
            "memory_used_percent": round(float(memory.percent), 1),
            "disk_read_bytes_per_second": (
                round(disk_read_rate, 1) if disk_read_rate is not None else None
            ),
            "disk_write_bytes_per_second": (
                round(disk_write_rate, 1) if disk_write_rate is not None else None
            ),
            "top_processes": process_usage[:5],
            "skipped_process_count": skipped_processes,
        })
        last_sample = sample_time
        if progress_callback is not None:
            progress_callback(min(1.0, (sample_time - started) / duration_seconds))

    cpu_values = [sample["cpu_percent"] for sample in samples]
    memory_values = [sample["memory_used_percent"] for sample in samples]
    read_values = [
        sample["disk_read_bytes_per_second"]
        for sample in samples
        if sample["disk_read_bytes_per_second"] is not None
    ]
    write_values = [
        sample["disk_write_bytes_per_second"]
        for sample in samples
        if sample["disk_write_bytes_per_second"] is not None
    ]
    per_core_values = [
        sample["cpu_per_core_percent"]
        for sample in samples
        if sample.get("cpu_per_core_percent")
    ]
    cpu_per_core_average = []
    cpu_per_core_minimum = []
    cpu_per_core_maximum = []
    if per_core_values:
        core_count = min(len(values) for values in per_core_values)
        for core_index in range(core_count):
            values = [
                values[core_index]
                for values in per_core_values
                if len(values) > core_index
            ]
            if values:
                cpu_per_core_average.append(round(sum(values) / len(values), 1))
                cpu_per_core_minimum.append(min(values))
                cpu_per_core_maximum.append(max(values))
    details = {
        "status": "interrupted" if interrupted else "complete",
        "duration_seconds": round(time.monotonic() - started, 1),
        "requested_duration_seconds": duration_seconds,
        "sample_interval_seconds": sample_interval_seconds,
        "sample_count": len(samples),
        "cpu_percent_average": round(sum(cpu_values) / len(cpu_values), 1) if cpu_values else None,
        "cpu_percent_peak": max(cpu_values) if cpu_values else None,
        "cpu_percent_minimum": min(cpu_values) if cpu_values else None,
        "cpu_trend": _performance_trend(cpu_values, 5),
        "cpu_per_core": {
            "status": "available" if cpu_per_core_average else "unavailable",
            "sample_count": len(per_core_values),
            "average_percent": cpu_per_core_average,
            "minimum_percent": cpu_per_core_minimum,
            "maximum_percent": cpu_per_core_maximum,
            "source": "psutil" if cpu_per_core_average else "unavailable",
        },
        "memory_used_percent_average": (
            round(sum(memory_values) / len(memory_values), 1) if memory_values else None
        ),
        "memory_used_percent_peak": max(memory_values) if memory_values else None,
        "memory_trend": _performance_trend(memory_values, 3),
        "disk_read_bytes_per_second_average": (
            round(sum(read_values) / len(read_values), 1) if read_values else None
        ),
        "disk_write_bytes_per_second_average": (
            round(sum(write_values) / len(write_values), 1) if write_values else None
        ),
        "disk_latency_ms": {
            "status": "unavailable",
            "reason": "psutil exposes byte counters but not a reliable Windows disk latency metric.",
        },
        "disk_active_time": {
            "status": "unavailable",
            "reason": "Active-time percentage is not exposed as a cross-platform psutil metric.",
        },
        "samples": samples,
        "process_list_note": "Process command lines and executable paths are not collected.",
    }
    if not samples and not interrupted:
        details["status"] = "not_verified"
    if cpu_values and max(cpu_values) >= 95:
        findings.append(_make_finding(
            "high",
            "CPU utilization reached at least 95% during the monitoring window.",
            "A sustained workload or background process may be consuming CPU.",
            "Review the time-series and process samples; stop or change nothing automatically.",
        ))
    if memory_values and max(memory_values) >= 95:
        findings.append(_make_finding(
            "high",
            "Memory utilization reached at least 95% during the monitoring window.",
            "Applications or background processes may have used most available memory.",
            "Review the time-series and process samples; close only applications you recognize.",
        ))
    return details, findings, interrupted


def _run_integrity_checks(
    cancel_event: threading.Event | None = None,
) -> tuple[list[dict], list[dict]]:
    checks = []
    findings = []
    if platform.system() != "Windows":
        return [_check("System files", "unavailable", "Windows only.", "SFC and DISM")], findings

    for name, command, timeout in (
        (
            "DISM component store scan",
            ["DISM.exe", "/Online", "/Cleanup-Image", "/ScanHealth"],
            _DISM_SCAN_TIMEOUT_SECONDS,
        ),
        (
            "Windows system files verification",
            ["sfc.exe", "/verifyonly"],
            _SFC_VERIFY_TIMEOUT_SECONDS,
        ),
    ):
        source_name = command[0]
        verification_state = None
        try:
            command = [_system_executable(command[0]), *command[1:]]
            result = _run_process(command, timeout, cancel_event)
            output = (result.stdout + "\n" + result.stderr).strip()
            normalized = output.casefold()
            if result.returncode != 0 and (
                "740" in normalized
                or _contains_any(normalized, (
                "administrator",
                "administrateur",
                "elevation",
                "élévation",
                "access is denied",
                "accès refusé",
                "must be run from an elevated command prompt",
                "doit être exécuté à partir d'une invite de commandes élevée",
                ))
            ):
                status = "requires_administrator"
                details = "Windows requires an already elevated session for this check; no elevation was attempted."
            elif result.returncode != 0:
                status = "error"
                details = (
                    "Windows returned error 740 or denied access; no elevation was attempted."
                    if "740" in normalized or _contains_any(normalized, ("access is denied", "accès refusé"))
                    else f"The read-only integrity command exited with code {result.returncode}."
                )
            elif name == "Windows system files verification" and _contains_any(normalized, (
                "did not find any integrity violations",
                "n'a détecté aucune violation d'intégrité",
                "n’a détecté aucune violation d’intégrité",
            )):
                status = "ok"
                details = "No system file integrity violations were reported."
                verification_state = "healthy_verified"
            elif name == "Windows system files verification" and _contains_any(normalized, (
                "found integrity violations",
                "a détecté des violations d'intégrité",
                "a détecté des fichiers endommagés",
                "a trouvé des violations d'intégrité",
            )):
                status = "issues_found"
                details = "SFC reported system file integrity violations; it did not repair them."
                findings.append(_make_finding(
                    "high",
                    "Windows system file integrity violations were reported.",
                    "Windows Resource Protection detected files that may be corrupted.",
                    "Review Windows servicing logs. If you request repair, use the separately confirmed SFC operation; it requires an elevated session and a verified restore point.",
                    True,
                ))
            elif name == "DISM component store scan" and _contains_any(normalized, (
                "no component store corruption detected",
                "aucune corruption du magasin de composants n'a été détectée",
                "aucune corruption du magasin de composants n’a été détectée",
                "no component store corruption was detected",
                "aucune corruption détectée dans le magasin de composants",
            )):
                status = "ok"
                details = "DISM ScanHealth reported no component-store corruption."
                verification_state = "healthy_verified"
            elif name == "DISM component store scan" and _contains_any(normalized, (
                "component store is repairable",
                "component store corruption",
                "le magasin de composants est réparable",
                "corruption du magasin de composants",
            )):
                status = "issues_found"
                details = "DISM reports component-store corruption; this check did not repair it."
                findings.append(_make_finding(
                    "high",
                    "The Windows component store may be corrupted.",
                    "DISM ScanHealth reported component-store corruption.",
                    "If you request repair, use the separately confirmed DISM operation after backing up important data; it requires an elevated session and a verified restore point.",
                    True,
                ))
            else:
                status = "unverified"
                details = (
                    "The read-only command returned output that did not establish a recognized health result."
                    if output
                    else "The command returned no recognizable health result."
                )
                verification_state = "not_verified"
            checks.append(_check(
                name,
                status,
                details,
                source_name,
                verification_state=verification_state,
            ))
            if status == "error":
                findings.append(_make_finding(
                    "medium",
                    f"{name} could not complete successfully.",
                    "The integrity checker reported an error; its output does not by itself identify a repair.",
                    "Review the local Windows result. Do not run repair operations until the error and required permissions are understood.",
                    True,
                ))
        except subprocess.TimeoutExpired as exc:
            termination_confirmed = getattr(
                exc,
                "termination_confirmed",
                None,
            )
            checks.append(_check(
                name,
                "timeout",
                {
                    "message": f"The read-only check exceeded its {timeout}-second limit.",
                    "process_termination_confirmed": termination_confirmed,
                },
                source_name,
            ))
        except DiagnosticCancelled:
            raise
        except RuntimeError as exc:
            checks.append(_check(name, "unavailable", str(exc), source_name))
        except OSError as exc:
            checks.append(_check(name, "unavailable", f"Could not start the Windows tool: {exc}", source_name))
    return checks, findings


def _read_powershell_category(
    category: str,
    cancel_event: threading.Event | None = None,
) -> tuple[list[dict], list[dict]]:
    checks = []
    findings = []
    if category == "errors":
        all_events = []
        for log_name in ("System", "Application"):
            result = _read_event_log(log_name, cancel_event=cancel_event)
            events = result["events"]
            all_events.extend(events)
            status = result["status"]
            details = {
                "window_days": result.get("window_days", _EVENT_WINDOW_DAYS),
                "page_days": result.get("page_days", _EVENT_PAGE_DAYS),
                "page_size": result.get("page_size", _EVENT_PAGE_SIZE),
                "maximum_results": result.get("maximum_results", _EVENT_MAX_RESULTS_PER_LOG),
                "count": len(events),
                "truncated": status == "partial",
                "error": result.get("error"),
                "events": events,
                "privacy_note": "Event messages and user-specific paths are not collected.",
            }
            checks.append(_check(
                f"{log_name} event summaries",
                status,
                details,
                "Get-WinEvent -FilterHashtable",
            ))
        counts = {}
        for event in all_events:
            level = str(event.get("LevelDisplayName") or "Unknown")
            counts[level] = counts.get(level, 0) + 1
        if any(
            str(event.get("LevelDisplayName", "")).casefold()
            in {"critical", "error", "critique", "erreur"}
            for event in all_events
        ):
            error_count = sum(
                count for level, count in counts.items()
                if level.casefold() in {"critical", "error", "critique", "erreur"}
            )
            findings.append(_make_finding(
                "medium",
                f"{error_count} critical/error event summaries were found in the last {_EVENT_WINDOW_DAYS} days.",
                "Windows recorded critical/error events; event entries do not alone prove an ongoing failure.",
                "Review the event provider and ID in Event Viewer and correlate with when the issue occurred.",
            ))
        return checks, findings

    script_key = _CATEGORY_TO_SCRIPT.get(category)
    if script_key is None:
        return checks, findings
    try:
        data = _powershell(
            _POWERSHELL_SCRIPTS[script_key],
            cancel_event=cancel_event,
        )
    except DiagnosticCancelled:
        raise
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return [_check(_CATEGORY_LABELS[category], "error", str(exc), "PowerShell/CIM")], findings

    if category == "windows":
        os_data = data.get("OS") or {}
        update_data = {
            "recent_installed_updates": _as_list(data.get("RecentUpdates")),
            "pending_update_count": data.get("PendingUpdateCount"),
            "pending_update_titles": _as_list(data.get("PendingUpdateTitles")),
            "update_search_note": data.get("UpdateError") or "No updates were downloaded or installed.",
        }
        checks.append(_check(
            "Windows",
            "ok" if os_data else "unavailable",
            os_data or "Windows version information was not returned.",
            "CIM Win32_OperatingSystem",
        ))
        checks.append(_check("Windows updates", "ok" if not data.get("UpdateError") else "partial", update_data, "Get-HotFix and Windows Update search"))
        if isinstance(data.get("PendingUpdateCount"), int) and data["PendingUpdateCount"] > 0:
            findings.append(_make_finding(
                "medium",
                f"{data['PendingUpdateCount']} software updates are reported as pending.",
                "Windows Update search found updates that are not installed.",
                "Review the updates in Windows Settings. NIANG IA will not download or install them.",
                True,
            ))

    elif category == "drivers":
        gpus = _as_list(data.get("GPUs"))
        amd_drivers = _as_list(data.get("AmdDrivers"))
        devices = _as_list(data.get("ProblemDevices"))
        disks = _as_list(data.get("PhysicalDisks"))
        batteries = _as_list(data.get("Batteries"))
        fans = _as_list(data.get("Fans"))
        pnp_available = bool(data.get("PnpAvailable"))
        checks.append(_check("Graphics adapters", "ok" if gpus else "unavailable", gpus or "No GPU information was returned.", "CIM Win32_VideoController"))
        checks.append(_check(
            "AMD Radeon driver",
            "ok" if amd_drivers else "unavailable",
            amd_drivers or "No AMD/Radeon signed-driver record was returned.",
            "CIM Win32_PnPSignedDriver",
        ))
        checks.append(_check(
            "Device Manager",
            "ok" if pnp_available else "unavailable",
            {
                "problem_device_count": len(devices),
                "devices": devices,
                "note": None if pnp_available else "The Get-PnpDevice cmdlet is unavailable; device status was not checked.",
            },
            "Get-PnpDevice",
            verification_state=(
                "healthy_verified"
                if pnp_available and not devices
                else "problem_detected"
                if devices
                else "data_unavailable"
            ),
        ))
        disk_has_problem = any(
            str(disk.get("HealthStatus", "")).casefold() not in {"healthy", "unknown", ""}
            for disk in disks
        )
        disk_has_health_data = any(
            str(disk.get("HealthStatus", "")).casefold() not in {"unknown", ""}
            for disk in disks
        )
        checks.append(_check(
            "Storage SMART/reliability",
            "issues_found" if disk_has_problem else "ok" if disks else "unavailable",
            disks or "Physical disk health counters are unavailable on this device/controller.",
            "Get-PhysicalDisk / Get-StorageReliabilityCounter",
            verification_state=(
                "problem_detected"
                if disk_has_problem
                else "healthy_verified"
                if disks and disk_has_health_data
                else "not_verified"
                if disks
                else "data_unavailable"
            ),
        ))
        checks.append(_check(
            "GPU temperature",
            "unavailable",
            data.get("GpuTemperatureNote") or "No GPU temperature sensor data was returned.",
            "Windows hardware sensor providers",
        ))
        checks.append(_check(
            "Battery",
            "ok" if batteries else "unavailable",
            batteries or "No battery information was exposed by Win32_Battery.",
            "CIM Win32_Battery",
        ))
        checks.append(_check(
            "Cooling fans",
            "ok" if fans else "unavailable",
            fans or "No fan status or speed was exposed by Win32_Fan.",
            "CIM Win32_Fan",
        ))
        for device in devices:
            findings.append(_make_finding(
                "medium",
                f"Device reports a non-OK state: {device.get('FriendlyName', 'unnamed device')} ({device.get('Status', 'unknown')}).",
                "Plug and Play reports a non-OK status; the status alone may not indicate a fault.",
                "Review the device in Device Manager and its vendor documentation; do not uninstall or update drivers automatically.",
                True,
            ))
        for disk in disks:
            health = str(disk.get("HealthStatus", "")).casefold()
            if health and health not in {"healthy", "unknown"}:
                findings.append(_make_finding(
                    "high",
                    f"Storage device health is reported as {disk.get('HealthStatus')}.",
                    "The storage provider reports a non-healthy health status.",
                    "Back up important data using your normal backup process and obtain a vendor-specific assessment before any repair.",
                    True,
                ))

    elif category == "services":
        services = _as_list(data.get("AutoStartStopped"))
        checks.append(_check("Automatic services", "ok", {"stopped_count": len(services), "services": services}, "CIM Win32_Service"))
        checks.append(_check(
            "Service interpretation",
            "informational",
            "Stopped automatic services are listed for review only; many Windows services are trigger-started or normally stopped.",
            "Local interpretation",
        ))

    elif category == "errors":
        events = _as_list(data.get("Events"))
        query_errors = _as_list(data.get("QueryErrors"))
        counts = {}
        for event in events:
            level = str(event.get("LevelDisplayName") or "Unknown")
            counts[level] = counts.get(level, 0) + 1
        checks.append(_check(
            "Recent event summaries",
            "partial" if query_errors else "ok",
            {
                "window_days": data.get("WindowDays", 7),
                "count": len(events),
                "counts_by_level": counts,
                "events": events,
                "unavailable_logs": query_errors,
                "privacy_note": "Event messages and user-specific paths are not collected.",
            },
            "Get-WinEvent",
        ))
        if any(
            str(event.get("LevelDisplayName", "")).casefold()
            in {"critical", "error", "critique", "erreur"}
            for event in events
        ):
            findings.append(_make_finding(
                "medium",
                f"{sum(count for level, count in counts.items() if level.casefold() in {'critical', 'error', 'critique', 'erreur'})} recent critical/error event summaries were found.",
                "Windows recorded events at critical/error severity during the last seven days; event entries do not alone prove an ongoing failure.",
                "Review the event provider and ID in Event Viewer and correlate with the time the problem occurred.",
            ))

    elif category == "network":
        adapters = _as_list(data.get("Adapters"))
        configs = _as_list(data.get("Configurations"))
        checks.append(_check(
            "Network",
            "ok",
            {
                "adapters": adapters,
                "configuration_presence": configs,
                "privacy_note": "IP addresses and DNS server addresses are intentionally omitted; external connectivity was not probed.",
            },
            "Get-NetAdapter and Get-NetIPConfiguration",
        ))
        down = [
            adapter for adapter in adapters
            if str(adapter.get("Status", "")).casefold() not in {"up", "connected"}
        ]
        if adapters and len(down) == len(adapters):
            findings.append(_make_finding(
                "medium",
                "No network adapter is currently reported as connected.",
                "Adapters are disconnected, disabled, or unavailable.",
                "Check the physical connection and Windows network settings; do not reset network settings automatically.",
                True,
            ))
    return checks, findings


def _normalize_category(category: str | None) -> str:
    normalized = str(category or "overview").strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "analyze": "overview",
        "analyse": "overview",
        "analyser": "overview",
        "analyse_mon_pc": "overview",
        "drivers": "drivers",
        "driver": "drivers",
        "pilotes": "drivers",
        "windows": "windows",
        "performance": "performance",
        "performances": "performance",
        "performance_monitor_5m": "performance_monitor_5m",
        "monitor_performance": "performance_monitor_5m",
        "surveiller_5_minutes": "performance_monitor_5m",
        "errors": "errors",
        "erreurs": "errors",
        "network": "network",
        "reseau": "network",
        "services": "services",
        "system_files": "system_files",
        "fichiers_systeme": "system_files",
        "integrity": "system_files",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in _CATEGORY_LABELS:
        raise ValueError(f"Unsupported diagnostic category: {category!r}.")
    return normalized


def _store_history(report: dict) -> None:
    summary = {
        "timestamp_utc": report["timestamp_utc"],
        "category": report["category"],
        "status": report["status"],
        "finding_count": len(report["findings"]),
        "findings": [
            {
                "severity": item["severity"],
                "problem": item["problem"][:240],
            }
            for item in report["findings"][:20]
        ],
    }
    path = _history_path()
    with _HISTORY_LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError("The local diagnostic history directory is unavailable.") from exc
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, list) or any(
                not isinstance(item, dict) for item in existing
            ):
                raise RuntimeError("The local diagnostic history has an unexpected format.")
            history = existing
        except FileNotFoundError:
            history = []
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("The local diagnostic history could not be read safely.") from exc
        history.append(summary)
        try:
            path.write_text(
                json.dumps(history[-_MAX_HISTORY_ITEMS:], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise RuntimeError("The local diagnostic history could not be saved.") from exc


def _store_report(report: dict) -> Path:
    directory = _reports_directory()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError("The local diagnostic report directory is unavailable.") from exc
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = directory / f"windows-diagnostic-{timestamp}.json"
    report["report_path"] = str(path)
    try:
        with path.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=True, indent=2)
            output.write("\n")
    except OSError as exc:
        raise RuntimeError("The local diagnostic report could not be saved.") from exc
    return path


def read_history() -> list[dict]:
    path = _history_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read diagnostic history: {exc}") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RuntimeError("The local diagnostic history has an unexpected format.")
    return value[-_MAX_HISTORY_ITEMS:]


def run_diagnostic(
    category: str | None = None,
    *,
    record_history: bool = True,
    cancel_event: threading.Event | None = None,
    progress_callback=None,
    monitor_duration_seconds: int = _PERFORMANCE_MONITOR_SECONDS,
) -> dict:
    """Run selected read-only checks and return a structured local report."""
    if cancel_event is not None and cancel_event.is_set():
        raise DiagnosticCancelled("The Windows diagnostic was cancelled before collection started.")
    selected = _normalize_category(category)
    checks: list[dict] = []
    findings: list[dict] = []
    categories = (
        ("performance", "windows", "drivers", "services", "network", "errors", "system_files")
        if selected == "overview"
        else (selected,)
    )
    interrupted = False

    for item in categories:
        if cancel_event is not None and cancel_event.is_set():
            checks.append(_check(
                item,
                "interrupted",
                "Analysis stopped before this check started.",
                "cancellation event",
            ))
            interrupted = True
            break
        try:
            if item == "performance":
                category_checks, category_findings = _collect_performance(cancel_event)
            elif item == "performance_monitor_5m":
                details, category_findings, monitor_interrupted = _monitor_performance(
                    duration_seconds=monitor_duration_seconds,
                    cancel_event=cancel_event,
                    progress_callback=progress_callback,
                )
                interrupted = monitor_interrupted
                monitor_status = details.get("status")
                category_checks, category_findings = [
                    _check(
                        _CATEGORY_LABELS[item],
                        (
                            "interrupted" if monitor_interrupted
                            else "unavailable" if monitor_status == "unavailable"
                            else "unverified" if monitor_status == "not_verified"
                            else "ok"
                        ),
                        details,
                        "psutil",
                    )
                ], category_findings
            elif item == "system_files":
                category_checks, category_findings = _run_integrity_checks(cancel_event)
            else:
                category_checks, category_findings = _read_powershell_category(item, cancel_event)
        except DiagnosticCancelled:
            raise
        except subprocess.TimeoutExpired as exc:
            checks.append(_check(
                item,
                "timeout",
                {
                    "message": f"The {item} check exceeded its time limit.",
                    "process_termination_confirmed": getattr(exc, "termination_confirmed", None),
                },
                "bounded process",
            ))
            continue
        except Exception as exc:
            category_checks, category_findings = [
                _check(item, "error", f"Collection failed: {type(exc).__name__}.", "local diagnostic")
            ], []
        checks.extend(category_checks)
        findings.extend(category_findings)

    status = "interrupted" if interrupted else "issues_found" if findings else "ok"
    if any(
        check["status"] in {
            "error",
            "timeout",
            "partial",
            "requires_administrator",
            "permission_refused",
            "unavailable",
            "unverified",
        }
        for check in checks
    ) and not interrupted:
        status = "partial_with_findings" if findings else "partial"
    if checks and all(check["status"] == "unavailable" for check in checks):
        status = "unavailable"
    report = {
        "category": selected,
        "label": _CATEGORY_LABELS[selected],
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "status": status,
        "checks": checks,
        "findings": findings,
        "privacy": (
            "No command lines, executable paths, serial numbers, IP addresses, "
            "event messages, or personal file contents are collected. "
            "Diagnostics are observation-only; full reports and bounded summaries are stored locally."
        ),
        "limitations": [
            "Temperature, SMART, Device Manager, and Windows Update results depend on hardware, drivers, services, and Windows permissions.",
            "GPU temperatures and fan data are reported only when a Windows provider exposes them.",
            "DISM /ScanHealth and SFC /verifyonly are observation checks; they do not repair files, but may write Windows servicing logs.",
            "Five-minute performance monitoring is a local sampled observation, not a full performance trace.",
        ],
    }
    try:
        from actions.windows_repair_analysis import analyze_report
        report["repair_proposals"] = analyze_report(report)
    except Exception:
        report["repair_proposals"] = []
        report["repair_analysis_status"] = "not_available"
    else:
        report["repair_analysis_status"] = "available"
    if record_history:
        try:
            _store_history(report)
            report["history_status"] = "saved_locally"
        except RuntimeError as exc:
            report["history_status"] = "not_saved"
            report["persistence_error"] = str(exc)
        report["report_status"] = "saved_locally"
        try:
            report_path = _store_report(report)
            report["report_path"] = str(report_path)
        except RuntimeError as exc:
            report["report_status"] = "not_saved"
            report["persistence_error"] = str(exc)
    return report


def windows_diagnostics(
    parameters: dict | None = None,
    *,
    cancel_flag: threading.Event | None = None,
    **_kwargs,
) -> str:
    """Agent tool entry point. Its report is private and requires safety approval."""
    params = parameters or {}
    report = run_diagnostic(
        params.get("action") or params.get("category") or "overview",
        cancel_event=cancel_flag,
        monitor_duration_seconds=int(
            params.get("duration_seconds") or _PERFORMANCE_MONITOR_SECONDS
        ),
    )
    if report["status"] == "interrupted":
        raise DiagnosticCancelled("The Windows diagnostic was interrupted.")
    return json.dumps(report, ensure_ascii=False)


def history_text() -> str:
    history = read_history()
    return json.dumps(history, ensure_ascii=False, indent=2)

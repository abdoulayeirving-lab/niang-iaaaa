"""Explicitly approved, fixed Windows repair operations."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import subprocess
import threading
import socket
from datetime import datetime, timezone
from pathlib import Path
import uuid

from actions.windows_process import WindowsProcessCancelled, run_windows_process
from typing import Any


_REPAIRS = {
    "flush_dns": {
        "label": "Flush the Windows DNS resolver cache",
        "command": ["ipconfig.exe", "/flushdns"],
        "timeout_seconds": 30,
        "restore_point": False,
        "requires_admin": True,
    },
    "sfc_scannow": {
        "label": "Run System File Checker repair",
        "command": ["sfc.exe", "/scannow"],
        "timeout_seconds": 1800,
        "restore_point": True,
        "requires_admin": True,
    },
    "dism_restore_health": {
        "label": "Repair the Windows component store with DISM",
        "command": ["DISM.exe", "/Online", "/Cleanup-Image", "/RestoreHealth"],
        "timeout_seconds": 3600,
        "restore_point": True,
        "requires_admin": True,
    },
}


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return any(phrase.casefold() in lowered for phrase in phrases)


def _dns_baseline() -> dict:
    baseline: dict[str, Any] = {"domain": "microsoft.com"}
    try:
        addresses = socket.getaddrinfo("microsoft.com", 443, type=socket.SOCK_STREAM)
        baseline["resolution_successful"] = bool(addresses)
        baseline["address_count"] = len(addresses)
    except socket.gaierror as exc:
        baseline["resolution_successful"] = False
        baseline["resolution_error"] = type(exc).__name__
    try:
        with socket.create_connection(("microsoft.com", 443), timeout=5):
            baseline["connectivity_successful"] = True
    except OSError as exc:
        baseline["connectivity_successful"] = False
        baseline["connectivity_error"] = type(exc).__name__
    return baseline


class RepairCancelled(RuntimeError):
    """A repair subprocess was explicitly stopped; final state may be unknown."""


def repair_description(action: str) -> str:
    operation = _REPAIRS.get(str(action or "").strip().casefold())
    if operation is None:
        raise ValueError(f"Unsupported Windows repair: {action!r}.")
    description = f"{operation['label']} using the fixed command: {' '.join(operation['command'])}."
    if operation["restore_point"]:
        description += (
            " First attempt to create a Windows restore point. If that is unavailable, "
            "the repair will not run. Requires the application to already be elevated."
        )
    return description


def _is_elevated() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _system_executable(relative_path: str) -> str:
    system_root = os.environ.get("SystemRoot")
    if not system_root:
        raise RuntimeError("The Windows SystemRoot environment variable is unavailable.")
    executable = Path(system_root) / "System32" / relative_path
    if not executable.is_file():
        raise RuntimeError(f"Required Windows component is unavailable: {relative_path}.")
    return str(executable)


def _run(
    command: list[str],
    timeout_seconds: int,
    cancel_event: threading.Event | None = None,
) -> subprocess.CompletedProcess:
    if not Path(command[0]).is_absolute():
        command = [_system_executable(command[0]), *command[1:]]
    try:
        return run_windows_process(command, timeout_seconds, cancel_event)
    except WindowsProcessCancelled as exc:
        raise RepairCancelled(str(exc)) from exc


def _create_restore_point(cancel_event: threading.Event | None = None) -> dict:
    script = (
        "$ErrorActionPreference='Stop'; "
        "Checkpoint-Computer -Description 'NIANG IA approved repair' "
        "-RestorePointType MODIFY_SETTINGS; "
        "$point = Get-ComputerRestorePoint | Sort-Object SequenceNumber -Descending | Select-Object -First 1; "
        "if (-not $point) { throw 'Windows did not report a restore point.' }; "
        "[pscustomobject]@{ Description=$point.Description; SequenceNumber=$point.SequenceNumber } "
        "| ConvertTo-Json -Compress"
    )
    result = _run(
        [
            _system_executable(r"WindowsPowerShell\v1.0\powershell.exe"),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        90,
        cancel_event,
    )
    if result.returncode:
        return {
            "created": False,
            "detail": (result.stderr or result.stdout).strip()[:500]
            or f"PowerShell exited with code {result.returncode}.",
        }
    try:
        point: Any = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return {"created": False, "detail": "Windows did not return verifiable restore-point details."}
    if not isinstance(point, dict) or not point.get("SequenceNumber"):
        return {"created": False, "detail": "Windows did not confirm a restore point."}
    return {
        "created": True,
        "description": str(point.get("Description") or "NIANG IA approved repair"),
        "sequence_number": point.get("SequenceNumber"),
    }


def _verification(
    action: str,
    cancel_event: threading.Event | None = None,
) -> dict:
    if action == "flush_dns":
        dns_status: dict[str, Any] = {"external_resolution": False}
        try:
            addresses = socket.getaddrinfo("microsoft.com", 443, type=socket.SOCK_STREAM)
            dns_status["external_resolution"] = bool(addresses)
            dns_status["resolved_addresses"] = len(addresses)
        except socket.gaierror as exc:
            dns_status["external_resolution_error"] = type(exc).__name__

        cache_output: list[str] = []
        display_dns_status = "unavailable"
        display_dns_detail = ""
        try:
            display_dns = _run(["ipconfig.exe", "/displaydns"], 15, cancel_event)
            if display_dns.returncode == 0:
                display_dns_status = "collected"
                display_dns_detail = display_dns.stdout[-1200:]
                cache_output.append(display_dns_detail)
            else:
                display_dns_status = "error"
                display_dns_detail = (display_dns.stderr or display_dns.stdout).strip()[-1200:]
        except RepairCancelled:
            raise
        except (subprocess.TimeoutExpired, OSError, RuntimeError):
            display_dns_status = "unavailable"

        powershell_status = "unavailable"
        powershell_detail = ""
        try:
            cache_script = (
                "Get-DnsClientCache -ErrorAction Stop "
                "| Select-Object -First 100 Entry,Name,Status,Type,Data "
                "| ConvertTo-Json -Compress"
            )
            cache = _run(
                [
                    _system_executable(r"WindowsPowerShell\v1.0\powershell.exe"),
                    "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", cache_script,
                ],
                15,
                cancel_event,
            )
            if cache.returncode == 0:
                powershell_status = "collected"
                powershell_detail = cache.stdout[-1200:]
                cache_output.append(powershell_detail)
            else:
                powershell_status = "error"
        except RepairCancelled:
            raise
        except (subprocess.TimeoutExpired, OSError, RuntimeError):
            powershell_status = "unavailable"

        if not dns_status["external_resolution"]:
            status = "verification_failed"
        elif display_dns_status == "unavailable" and powershell_status == "unavailable":
            status = "verification_unavailable"
        elif display_dns_status == "error" or powershell_status == "error":
            status = "verification_failed"
        else:
            status = "verified"
        return {
            "verified": status == "verified",
            "method": (
                "External-domain resolution plus ipconfig /displaydns and "
                "Get-DnsClientCache when available"
            ),
            "status": status,
            "external_resolution": dns_status["external_resolution"],
            "cache_inspection": {
                "ipconfig_displaydns": display_dns_status,
                "get_dns_client_cache": powershell_status,
            },
            "cache_empty": "unknown",
            "cache_detail_available": bool(cache_output),
            "detail": display_dns_detail[:300],
        }
    if action == "sfc_scannow":
        try:
            result = _run(["sfc.exe", "/verifyonly"], 900, cancel_event)
        except RepairCancelled:
            raise
        except subprocess.TimeoutExpired:
            return {
                "verified": False,
                "method": "SFC /verifyonly",
                "status": "timeout",
            }
        except OSError as exc:
            return {
                "verified": False,
                "method": "SFC /verifyonly",
                "status": "error",
                "detail": str(exc)[:500],
            }
        except RuntimeError as exc:
            return {
                "verified": False,
                "method": "SFC /verifyonly",
                "status": "unavailable",
                "detail": str(exc)[:500],
            }
        output = (result.stdout + "\n" + result.stderr).strip()
        normalized = output.casefold()
        if _contains_any(normalized, (
            "did not find any integrity violations",
            "n'a détecté aucune violation d'intégrité",
            "n’a détecté aucune violation d’intégrité",
        )):
            status = "healthy"
        elif _contains_any(normalized, (
            "found integrity violations",
            "a détecté des violations d'intégrité",
            "a détecté des fichiers endommagés",
            "a trouvé des violations d'intégrité",
        )):
            status = "issues_found"
        else:
            status = "unknown"
        return {
            "verified": result.returncode == 0 and status == "healthy",
            "method": "SFC /verifyonly",
            "status": status if result.returncode == 0 else "error",
            "detail": output[-1200:],
        }
    try:
        result = _run(
            ["DISM.exe", "/Online", "/Cleanup-Image", "/ScanHealth"],
            1800,
            cancel_event,
        )
    except RepairCancelled:
        raise
    except subprocess.TimeoutExpired:
        return {
            "verified": False,
            "method": "DISM /ScanHealth",
            "status": "timeout",
        }
    except OSError as exc:
        return {
            "verified": False,
            "method": "DISM /ScanHealth",
            "status": "error",
            "detail": str(exc)[:500],
        }
    except RuntimeError as exc:
        return {
            "verified": False,
            "method": "DISM /ScanHealth",
            "status": "unavailable",
            "detail": str(exc)[:500],
        }
    output = (result.stdout + "\n" + result.stderr).strip()
    normalized = output.casefold()
    if _contains_any(normalized, (
        "no component store corruption detected",
        "aucune corruption du magasin de composants n'a été détectée",
        "aucune corruption du magasin de composants n’a été détectée",
    )):
        status = "healthy"
    elif _contains_any(normalized, (
        "component store is repairable",
        "component store corruption",
        "le magasin de composants est réparable",
        "corruption du magasin de composants",
    )):
        status = "issues_found"
    else:
        status = "unknown"
    return {
        "verified": result.returncode == 0 and status == "healthy",
        "method": "DISM /ScanHealth",
        "status": status if result.returncode == 0 else "error",
        "detail": output[-1200:],
    }


def _perform_repair(
    action: str,
    *,
    approved: bool = False,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Run only a listed operation and only after an explicit human approval."""
    normalized = str(action or "").strip().casefold()
    operation = _REPAIRS.get(normalized)
    if operation is None:
        raise ValueError(f"Unsupported Windows repair: {action!r}.")
    if approved is not True:
        return {
            "action": normalized,
            "status": "blocked",
            "reason": "Explicit human approval is required; no command was run.",
        }
    if cancel_event is not None and cancel_event.is_set():
        raise RepairCancelled("The repair was cancelled before it started.")
    if platform.system() != "Windows":
        return {
            "action": normalized,
            "status": "unavailable",
            "reason": "Windows repairs are available only on Windows.",
        }
    if operation["requires_admin"] and not _is_elevated():
        return {
            "action": normalized,
            "status": "blocked_by_permissions",
            "reason": (
                "The current NIANG IA process is not elevated. No UAC prompt was "
                "opened and no administrator password was requested."
            ),
            "instruction": (
                "Close NIANG IA, then relaunch it using "
                "'Run as administrator' after reviewing the operation."
            ),
            "permission_detected": "not_elevated",
        }

    restore_point = None
    if operation["restore_point"]:
        try:
            restore_point = _create_restore_point(cancel_event)
        except RepairCancelled:
            raise
        except RuntimeError as exc:
            return {
                "action": normalized,
                "status": "blocked",
                "reason": f"A restore point could not be verified; repair was not started: {exc}",
                "restore_point": {"created": False},
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {
                "action": normalized,
                "status": "blocked",
                "reason": f"A restore point could not be verified; repair was not started: {exc}",
                "restore_point": {"created": False},
            }
        if not restore_point["created"]:
            return {
                "action": normalized,
                "status": "blocked",
                "reason": (
                    "Windows could not create and verify a restore point; the repair "
                    "was not started."
                ),
                "restore_point": restore_point,
            }

    dns_baseline = _dns_baseline() if normalized == "flush_dns" else None

    try:
        result = _run(
            operation["command"],
            operation["timeout_seconds"],
            cancel_event,
        )
    except RepairCancelled:
        raise
    except subprocess.TimeoutExpired:
        return {
            "action": normalized,
            "status": "timeout",
            "reason": (
                "The repair exceeded its time limit. Its final system state is unknown; "
                "inspect Windows before attempting it again."
            ),
            "command": " ".join(operation["command"]),
            "return_code": None,
            "permission_detected": "elevated" if _is_elevated() else "not_elevated",
            "restore_point": restore_point,
            "dns_baseline": dns_baseline,
        }
    except OSError as exc:
        return {
            "action": normalized,
            "status": "error",
            "reason": f"Could not start the approved Windows command: {exc}",
            "restore_point": restore_point,
        }
    except RuntimeError as exc:
        return {
            "action": normalized,
            "status": "error",
            "reason": f"Could not start the approved Windows command: {exc}",
            "restore_point": restore_point,
        }

    output = (result.stdout + "\n" + result.stderr).strip()
    if result.returncode != 0:
        return {
            "action": normalized,
            "status": "error",
            "reason": f"The approved command exited with code {result.returncode}.",
            "return_code": result.returncode,
            "command": " ".join(operation["command"]),
            "permission_detected": "elevated" if _is_elevated() else "not_elevated",
            "detail": output[-1200:],
            "restore_point": restore_point,
            "dns_baseline": dns_baseline,
        }

    verification = _verification(normalized, cancel_event)
    return {
        "action": normalized,
        "status": "completed" if verification["verified"] else "completed_unverified",
        "completed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": " ".join(operation["command"]),
        "return_code": result.returncode,
        "permission_detected": "elevated" if _is_elevated() else "not_elevated",
        "detail": output[-1200:],
        "dns_baseline": dns_baseline,
        "restore_point": restore_point,
        "verification": verification,
        "limitations": [
            "The command runs with the current Windows process permissions; NIANG IA does not request elevation or bypass UAC.",
            "Review the verification result and Windows event logs before repeating a repair.",
        ],
    }


def perform_repair(
    action: str,
    *,
    approved: bool = False,
    cancel_event: threading.Event | None = None,
    diagnostic_associated: str = "",
    problem: str = "",
    mission_id: str = "",
) -> dict:
    """Execute a fixed repair and persist a privacy-limited audit entry."""
    from actions.windows_repair_history import record_repair_event

    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    mission_id = str(mission_id or uuid.uuid4()).strip()[:120]
    interrupted = False
    try:
        result = _perform_repair(
            action,
            approved=approved,
            cancel_event=cancel_event,
        )
    except RepairCancelled:
        interrupted = True
        result = {
            "action": str(action or ""),
            "status": "cancelled",
            "reason": "The repair was cancelled; its final state may be unknown.",
            "command": " ".join(
                _REPAIRS.get(str(action or "").strip().casefold(), {}).get("command", [])
            ),
            "permission_detected": "elevated" if _is_elevated() else "not_elevated",
        }
        try:
            record_repair_event(
                action=str(action or ""),
                mission_id=mission_id,
                diagnostic_associated=diagnostic_associated,
                problem=problem,
                authorization="approved" if approved else "blocked",
                started_at_utc=started_at,
                result=result,
                interrupted=True,
                command=" ".join(
                    _REPAIRS.get(str(action or "").strip().casefold(), {}).get("command", [])
                ),
                permission_detected=result.get("permission_detected", "unknown"),
            )
        except RuntimeError:
            pass
        raise
    except ValueError:
        raise
    except Exception as exc:
        result = {
            "action": str(action or ""),
            "status": "error",
            "reason": f"The repair failed before a verified result: {type(exc).__name__}.",
        }
    try:
        record_repair_event(
            action=str(action or ""),
            mission_id=mission_id,
            diagnostic_associated=diagnostic_associated,
            problem=problem,
            authorization="approved" if approved else "blocked",
            started_at_utc=started_at,
            result=result,
            interrupted=interrupted,
            rollback_performed=False,
            command=" ".join(
                _REPAIRS.get(str(action or "").strip().casefold(), {}).get("command", [])
            ),
            permission_detected=result.get("permission_detected", "unknown"),
        )
    except RuntimeError:
        result["history_status"] = "not_saved"
    return result


def windows_repair(
    parameters: dict | None = None,
    *,
    cancel_flag: threading.Event | None = None,
    **_kwargs,
) -> str:
    """Agent tool entry point. Executor approval is required before dispatch."""
    params = parameters or {}
    action = params.get("action")
    result = perform_repair(
        action,
        approved=True,
        cancel_event=cancel_flag,
        mission_id=str(params.get("mission_id") or ""),
    )
    return json.dumps(result, ensure_ascii=False)

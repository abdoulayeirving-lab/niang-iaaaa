"""Select CPU temperature readings from local sensor providers."""

from __future__ import annotations

import math
import re
from typing import Any


POWERSHELL_TEMPERATURE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$sensors = @()
foreach ($provider in @(
    [pscustomobject]@{ Namespace = 'root/LibreHardwareMonitor'; Name = 'LibreHardwareMonitor' },
    [pscustomobject]@{ Namespace = 'root/OpenHardwareMonitor'; Name = 'OpenHardwareMonitor' }
)) {
    try {
        $rows = @(Get-CimInstance -Namespace $provider.Namespace -ClassName Sensor -ErrorAction Stop |
            Where-Object {
                $_.SensorType -eq 'Temperature' -and
                "$($_.Name) $($_.Identifier) $($_.Parent)" -match '(?i)cpu|processor|amdcpu|intelcpu|core|tctl|tdie' -and
                "$($_.Name) $($_.Identifier) $($_.Parent)" -notmatch '(?i)gpu|graphics|nvidia|radeon'
            })
        if ($rows.Count -gt 0) {
            $sensors = @($rows | ForEach-Object {
                [pscustomobject]@{
                    Name = [string]$_.Name
                    Value = [double]$_.Value
                    Source = $provider.Name
                }
            })
            break
        }
    } catch { }
}
if ($sensors.Count -eq 0) {
    $values = @(Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue |
        ForEach-Object {
            [pscustomobject]@{
                Name = 'ACPI thermal zone'
                Value = [math]::Round(($_.CurrentTemperature / 10) - 273.15, 1)
                Source = 'ACPI thermal zone'
            }
        } |
        Where-Object { $_.Value -ge 0 -and $_.Value -le 120 })
    $sensors = @($values)
}
[pscustomobject]@{ Sensors = $sensors } | ConvertTo-Json -Depth 4 -Compress
"""

_GPU_MARKERS = re.compile(r"gpu|graphics|nvidia|radeon", re.IGNORECASE)
_CPU_MARKERS = re.compile(r"cpu|processor|core|tctl|tdie|amdcpu|intelcpu", re.IGNORECASE)
_PACKAGE_MARKERS = re.compile(r"cpu.*package|package.*cpu|tctl|tdie|package id", re.IGNORECASE)
_CORE_MARKERS = re.compile(r"cpu.*core|core.*cpu|^core(?:\s|#|$)", re.IGNORECASE)


def _records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if isinstance(value, (list, tuple)):
        return [item for item in value if isinstance(item, dict)]
    return []


def select_temperature_reading(sensors: Any) -> dict[str, Any] | None:
    """Prefer a CPU package sensor, then CPU cores, then ACPI thermal zones."""
    valid = []
    for sensor in _records(sensors):
        try:
            value = float(sensor.get("Value"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value) or not 0 <= value <= 120:
            continue
        name = str(sensor.get("Name") or "")
        source = str(sensor.get("Source") or "")
        identity = f"{name} {source}"
        if _GPU_MARKERS.search(identity):
            continue
        valid.append((sensor, value, identity))

    cpu_sensors = [item for item in valid if _CPU_MARKERS.search(item[2])]
    if cpu_sensors:
        packages = [item for item in cpu_sensors if _PACKAGE_MARKERS.search(item[2])]
        selected = packages[:1] or [
            item for item in cpu_sensors if _CORE_MARKERS.search(item[2])
        ] or cpu_sensors[:1]
        value = sum(item[1] for item in selected) / len(selected)
        first = selected[0][0]
        return {
            "Celsius": round(value, 1),
            "Source": str(first.get("Source") or "hardware sensor"),
            "SensorName": str(first.get("Name") or "CPU temperature"),
            "SensorCount": len(selected),
        }

    acpi_sensors = [
        item for item in valid
        if "acpi" in item[2].lower() or "thermal zone" in item[2].lower()
    ]
    if acpi_sensors:
        value = sum(item[1] for item in acpi_sensors) / len(acpi_sensors)
        return {
            "Celsius": round(value, 1),
            "Source": "ACPI thermal zone (not CPU-specific)",
            "SensorName": str(acpi_sensors[0][0].get("Name") or "ACPI thermal zone"),
            "SensorCount": len(acpi_sensors),
        }
    return None


def is_cpu_specific_temperature(reading: dict[str, Any] | None) -> bool:
    return bool(reading and "not CPU-specific" not in str(reading.get("Source", "")))


def select_psutil_temperature_reading(temperatures: Any) -> dict[str, Any] | None:
    """Normalize psutil's platform-specific sensor map for the shared selector."""
    if not isinstance(temperatures, dict):
        return None
    sensors = []
    for source, entries in temperatures.items():
        if not isinstance(entries, (list, tuple)):
            continue
        for entry in entries:
            current = getattr(entry, "current", None)
            label = getattr(entry, "label", None)
            if current is not None:
                sensors.append({
                    "Name": str(label or source),
                    "Value": current,
                    "Source": str(source),
                })
    return select_temperature_reading(sensors)

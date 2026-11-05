"""Privacy-limited local history for supervised Windows repairs."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOCK = threading.Lock()
_MAX_HISTORY_ITEMS = 50


def _history_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return root / "NIANG IA" / "diagnostics"


def _history_path() -> Path:
    return _history_directory() / "repair-history.json"


def _final_status(result: dict) -> str:
    status = str(result.get("status") or "")
    verification = result.get("verification")
    verification_status = (
        str(verification.get("status") or "") if isinstance(verification, dict) else ""
    )
    allowed = {
        "success", "error", "blocked_by_permissions", "cancelled",
        "timeout", "verification_failed", "verification_unavailable",
        "outcome_unknown",
    }
    if status == "completed" and verification_status == "verified":
        return "success"
    if status == "blocked_by_permissions" or status == "requires_administrator":
        return "blocked_by_permissions"
    if status == "cancelled":
        return "cancelled"
    if status == "timeout":
        return "timeout"
    if verification_status in {"verification_failed", "failed"}:
        return "verification_failed"
    if verification_status in {"verification_unavailable", "unavailable"}:
        return "verification_unavailable"
    if status == "error":
        return "error"
    return status if status in allowed else "outcome_unknown"


def _expurgated_result(result: dict) -> dict:
    verification = result.get("verification")
    return {
        "status": str(result.get("status") or "unknown")[:40],
        "reason": str(result.get("reason") or "")[:500],
        "return_code": result.get("return_code")
        if isinstance(result.get("return_code"), int) else None,
        "verification": _verification_summary(result),
        "permission_detected": str(result.get("permission_detected") or "")[:40],
    }


def _verification_summary(result: dict) -> dict:
    verification = result.get("verification")
    if not isinstance(verification, dict):
        return {}
    return {
        "status": str(verification.get("status") or "unknown")[:40],
        "verified": verification.get("verified") if isinstance(
            verification.get("verified"), bool
        ) else False,
        "method": str(verification.get("method") or "")[:300],
        "external_resolution": verification.get("external_resolution"),
        "cache_inspection": verification.get("cache_inspection")
        if isinstance(verification.get("cache_inspection"), dict)
        else {},
        "cache_empty": verification.get("cache_empty") if (
            verification.get("cache_empty") in ("unknown", True, False)
        ) else "unknown",
    }


def record_repair_event(
    *,
    action: str,
    mission_id: str = "",
    diagnostic_associated: str = "",
    problem: str = "",
    authorization: str = "requested",
    started_at_utc: str = "",
    result: dict | None = None,
    interrupted: bool = False,
    rollback_performed: bool = False,
    command: str = "",
    permission_detected: str = "",
) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    safe_result = result if isinstance(result, dict) else {}
    entry = {
        "mission_id": str(mission_id or "")[:120],
        "timestamp_start_utc": started_at_utc or now,
        "timestamp_end_utc": now,
        "diagnostic_associated": str(diagnostic_associated or "")[:200],
        "problem": str(problem or "")[:240],
        "proposed_repair": str(action or "")[:80],
        "authorization": str(authorization or "")[:80],
        "permission_detected": str(
            permission_detected
            or safe_result.get("permission_detected")
            or "unknown"
        )[:40],
        "command_fixed": str(command or "")[:240],
        "return_code": safe_result.get("return_code")
        if isinstance(safe_result.get("return_code"), int) else None,
        "result_status": str(safe_result.get("status") or "unknown")[:40],
        "verification_status": str((safe_result.get("verification") or {}).get("status") or "unknown")[:40],
        "independent_verification": _verification_summary(safe_result),
        "expurgated_result": _expurgated_result(safe_result),
        "final_status": _final_status(safe_result),
        "error": str(safe_result.get("reason") or "")[:500],
        "interrupted": bool(interrupted),
        "rollback_performed": bool(rollback_performed),
        "rollback_available": bool(safe_result.get("restore_point", {}).get("created"))
        if isinstance(safe_result.get("restore_point"), dict)
        else False,
    }
    path = _history_path()
    with _LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError("The repair history directory is unavailable.") from exc
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(existing, list) or any(not isinstance(item, dict) for item in existing):
                raise RuntimeError("The repair history has an unexpected format.")
        except FileNotFoundError:
            existing = []
        except (OSError, json.JSONDecodeError, RuntimeError):
            existing = []
        existing.append(entry)
        try:
            path.write_text(
                json.dumps(existing[-_MAX_HISTORY_ITEMS:], ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            raise RuntimeError("The repair history could not be saved.") from exc
    return entry


def read_repair_history(limit: int = _MAX_HISTORY_ITEMS) -> list[dict]:
    try:
        value = json.loads(_history_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Could not read repair history safely.") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise RuntimeError("The repair history has an unexpected format.")
    return value[-max(1, min(limit, _MAX_HISTORY_ITEMS)):]


def repair_history_text() -> str:
    return json.dumps(read_repair_history(), ensure_ascii=False, indent=2)

"""Opt-in local usage patterns for lightweight proactive suggestions."""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = (
    Path(sys.executable).parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent.parent
)
DATA_PATH = BASE_DIR / "memory" / "proactive_usage.json"
_LOCK = threading.Lock()
_MAX_EVENTS = 240
_MIN_ACTIVE_DAYS = 3

SUGGESTIONS = {
    "calendar": ("calendar", "You often use Calendar. Want me to check your upcoming agenda?"),
    "reminder": ("reminder", "You often set reminders. Want to schedule one for your next task?"),
    "web_search": ("research", "You often research topics. Want me to organize a new search into a short summary?"),
    "translate": ("translation", "You often translate text. Want to translate another passage?"),
    "search_documents": ("documents", "You often search your documents. Want me to find a file or answer a question from one?"),
    "analyze_data": ("data reports", "You often analyze data. Want me to prepare another local report?"),
    "create_document": ("documents", "You often create documents. Want me to draft a new one?"),
    "smart_home_control": ("home control", "You often control your smart home. Want to check or adjust a device?"),
}
TRACKED_TOOLS = frozenset(SUGGESTIONS)


def _read_state() -> dict:
    if not DATA_PATH.exists():
        return {"enabled": False, "events": []}
    try:
        state = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read local suggestion history: {exc}") from exc
    if (
        not isinstance(state, dict)
        or not isinstance(state.get("enabled"), bool)
        or not isinstance(state.get("events"), list)
    ):
        raise RuntimeError("Local suggestion history has an invalid format.")
    return state


def _write_state(state: dict) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = DATA_PATH.with_suffix(".tmp")
    try:
        temp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp_path, DATA_PATH)
    except OSError as exc:
        raise RuntimeError(f"Could not save local suggestion preferences: {exc}") from exc


def record_tool_use(tool_name: str, today: date | None = None) -> None:
    """Record only an allow-listed tool name and date when tracking is enabled."""
    if tool_name not in TRACKED_TOOLS:
        return
    current_day = (today or date.today()).isoformat()
    with _LOCK:
        state = _read_state()
        if not state["enabled"]:
            return
        events = [
            item for item in state["events"]
            if isinstance(item, dict)
            and item.get("tool") in TRACKED_TOOLS
            and isinstance(item.get("day"), str)
        ]
        if not any(item["tool"] == tool_name and item["day"] == current_day for item in events):
            events.append({"tool": tool_name, "day": current_day})
        cutoff = (today or date.today()) - timedelta(days=29)
        state["events"] = [
            item for item in events
            if _valid_day(item["day"]) and date.fromisoformat(item["day"]) >= cutoff
        ][-_MAX_EVENTS:]
        _write_state(state)


def _valid_day(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def get_suggestions(today: date | None = None) -> list[str]:
    """Suggest shortcuts for tools used on at least three days in the last week."""
    current_day = today or date.today()
    cutoff = current_day - timedelta(days=6)
    with _LOCK:
        state = _read_state()
    if not state["enabled"]:
        return []
    active_days: dict[str, set[str]] = {}
    for item in state["events"]:
        if not isinstance(item, dict):
            continue
        tool = item.get("tool")
        day = item.get("day")
        if tool not in TRACKED_TOOLS or not isinstance(day, str) or not _valid_day(day):
            continue
        event_day = date.fromisoformat(day)
        if cutoff <= event_day <= current_day:
            active_days.setdefault(tool, set()).add(day)
    ranked = sorted(
        (
            (len(days), tool)
            for tool, days in active_days.items()
            if len(days) >= _MIN_ACTIVE_DAYS
        ),
        key=lambda item: (-item[0], item[1]),
    )
    return [SUGGESTIONS[tool][1] for _, tool in ranked[:2]]


def proactive_suggestions(parameters: dict) -> str:
    params = parameters if isinstance(parameters, dict) else {}
    action = str(params.get("action", "suggest")).strip().lower()
    try:
        with _LOCK:
            state = _read_state()
            if action == "enable":
                state["enabled"] = True
                _write_state(state)
                return (
                    "Proactive suggestions are enabled. NIANG IA will keep only "
                    "allow-listed tool names and dates locally (no arguments or "
                    "message content), for up to 30 days."
                )
            if action == "disable":
                state["enabled"] = False
                state["events"] = []
                _write_state(state)
                return "Proactive suggestions are disabled and their local usage history was deleted."
            if action == "status":
                return (
                    "Proactive suggestions are enabled."
                    if state["enabled"]
                    else "Proactive suggestions are disabled."
                )
        if action in {"suggest", "check"}:
            suggestions = get_suggestions()
            if not suggestions:
                return "No proactive suggestions yet. Suggestions need repeated use on at least three different days."
            return "Suggestions based on recent usage: " + " ".join(suggestions)
        return "Choose enable, disable, status, or suggest."
    except RuntimeError as exc:
        return str(exc)

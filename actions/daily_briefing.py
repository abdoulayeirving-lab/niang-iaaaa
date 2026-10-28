# actions/daily_briefing.py
# Kaizumi — Daily morning brief (time, weather, memory facts, system status)

import re
from datetime import datetime


def _get_time() -> str:
    now = datetime.now()
    return now.strftime("%A, %B %d %Y — %I:%M %p")


def _get_weather(city: str) -> str:
    if not city:
        return ""
    try:
        from actions.weather_report import weather_action
        text = weather_action(parameters={"city": city}, player=None)
        return str(text or "").strip()
    except Exception as e:
        return f"Weather unavailable: {e}"


def _get_system() -> str:
    try:
        from actions.system_status import system_status
        text = system_status(parameters={"focus": "overview"}, player=None)
        return str(text or "").strip()
    except Exception:
        return ""


def _get_calendar_agenda() -> str:
    from google_oauth import get_credentials

    if not get_credentials():
        return ""
    from actions.calendar_actions import calendar_action
    result = calendar_action(
        parameters={"action": "today", "max_results": 5},
        response=None,
        player=None,
    )
    if result.startswith("No upcoming events today"):
        return ""
    return result


def _get_memory() -> str:
    try:
        from memory.memory_manager import format_memory_for_prompt, load_memory
        mem = format_memory_for_prompt(load_memory())
        if not mem:
            return ""
        lines = []
        for line in mem.splitlines():
            line = line.strip()
            if line.startswith("-"):
                lines.append(line.lstrip("- ").strip())
        if not lines:
            return ""
        sample = "; ".join(fragment for fragment in lines[:6] if len(fragment) < 80 and not fragment.startswith("[")
                           and "WHAT YOU" not in fragment.upper())
        return sample[:600] if sample else ""
    except Exception:
        return ""


def daily_briefing(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Morning briefing: time, weather, key facts you know, system status."""
    params = parameters or {}
    city   = str(params.get("city", "")).strip()

    if not city:
        try:
            from memory.memory_manager import load_memory
            mem = load_memory()
            identity = mem.get("identity", {})
            for key in ("city", "location"):
                entry = identity.get(key, {})
                val = entry.get("value") if isinstance(entry, dict) else entry
                if val:
                    city = str(val)
                    break
        except Exception:
            pass

    parts = [f"Good morning, sir. Today is {_get_time()}."]

    try:
        from actions.proactive_suggestions import get_suggestions
        suggestions = get_suggestions()
        if suggestions:
            parts.append("A few suggestions based on your recent usage: " + " ".join(suggestions))
    except RuntimeError as exc:
        parts.append(f"Personalized suggestions unavailable: {exc}")

    weather = _get_weather(city)
    if weather and "unavailable" not in weather and len(weather) > 10:
        parts.append(f"Today's weather: {weather}")

    try:
        agenda = _get_calendar_agenda()
        if agenda:
            parts.append(agenda)
    except Exception as exc:
        print(f"[Briefing] Calendar agenda unavailable: {exc}")
        parts.append(f"Calendar agenda unavailable: {exc}")

    facts = _get_memory()
    if facts:
        parts.append(f"Here's what I remember about you: {facts}")

    sys_info = _get_system()
    if sys_info:
        parts.append(f"System status: {sys_info}")

    return " ".join(parts)[:1200]
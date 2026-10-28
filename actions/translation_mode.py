"""Preferences and instructions for live speech translation."""

from __future__ import annotations

MAX_LANGUAGE_LENGTH = 40


def _preference_value(preferences: dict, key: str) -> str:
    entry = preferences.get(key)
    if isinstance(entry, dict):
        entry = entry.get("value", "")
    return str(entry or "").strip()


def read_live_translation(memory: dict | None) -> tuple[bool, str, str]:
    preferences = memory.get("preferences", {}) if isinstance(memory, dict) else {}
    if not isinstance(preferences, dict):
        return False, "", ""
    enabled = _preference_value(preferences, "live_translation_enabled").lower()
    source = _preference_value(preferences, "live_translation_source")
    target = _preference_value(preferences, "live_translation_target")
    return enabled in {"true", "1", "yes", "on"}, source, target


def translation_instruction(memory: dict | None) -> str:
    enabled, source, target = read_live_translation(memory)
    if not enabled or not target:
        return ""
    source_description = (
        "the detected source language"
        if source.lower() in {"", "auto-detect", "auto"}
        else source
    )
    return (
        "[LIVE SPEECH TRANSLATION MODE]\n"
        f"Act as a live interpreter from {source_description} into {target}. "
        "Translate each user utterance promptly into natural spoken "
        f"{target}, preserving its meaning, tone, and register. "
        "Speak only the translation; do not answer the utterance, add "
        "commentary, or repeat the source text. If speech is unclear, ask "
        "briefly for repetition in the target language.\n\n"
    )


def translation_mode_update(parameters: dict) -> tuple[dict | None, str]:
    params = parameters if isinstance(parameters, dict) else {}
    action = str(params.get("action", "status")).strip().lower()
    if action == "disable":
        return {
            "preferences": {
                "live_translation_enabled": {"value": "false"},
            }
        }, "Live translation disabled."
    if action == "status":
        return None, "status"
    if action != "enable":
        return None, "Choose enable, disable, or status."

    source = str(params.get("from", "")).strip() or "auto-detect"
    target = str(params.get("to", "")).strip()
    if not target:
        return None, "Provide the target language to enable live translation."
    if len(target) > MAX_LANGUAGE_LENGTH or len(source) > MAX_LANGUAGE_LENGTH:
        return None, f"Language names must be at most {MAX_LANGUAGE_LENGTH} characters."
    if any(ord(char) < 32 for char in source + target):
        return None, "Language names must not contain control characters."

    updates = {
        "preferences": {
            "live_translation_enabled": {"value": "true"},
            "live_translation_source": {"value": source},
            "live_translation_target": {"value": target},
        }
    }
    source_description = (
        "automatic language detection"
        if source.lower() in {"auto-detect", "auto"}
        else source
    )
    return updates, f"Live translation enabled: {source_description} to {target}."

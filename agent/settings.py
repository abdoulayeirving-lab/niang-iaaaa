"""Validated runtime limits for autonomous missions."""

from __future__ import annotations

import os


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
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


def action_timeout_seconds() -> int:
    return _bounded_int("NIANG_IA_AGENT_ACTION_TIMEOUT_S", 180, 1, 1800)


def windows_action_timeout_seconds() -> int:
    return _bounded_int("NIANG_IA_WINDOWS_ACTION_TIMEOUT_S", 4200, 30, 7200)


def gemini_timeout_seconds() -> int:
    return _bounded_int("NIANG_IA_GEMINI_TIMEOUT_S", 180, 1, 1800)


def mission_timeout_seconds() -> int:
    return _bounded_int("NIANG_IA_AGENT_MISSION_TIMEOUT_S", 1800, 1, 86400)


def max_actions_per_mission() -> int:
    return _bounded_int("NIANG_IA_AGENT_MAX_ACTIONS", 20, 1, 1000)


def max_attempts_per_step() -> int:
    return _bounded_int("NIANG_IA_AGENT_MAX_ATTEMPTS_PER_STEP", 3, 1, 10)


def max_replans_per_mission() -> int:
    return _bounded_int("NIANG_IA_AGENT_MAX_REPLANS", 2, 0, 10)


def artifact_retention_days() -> int:
    return _bounded_int("NIANG_IA_ARTIFACT_RETENTION_DAYS", 30, 1, 3650)


def sensitive_mission_policy() -> str:
    policy = os.environ.get("NIANG_IA_SENSITIVE_MISSION_POLICY", "block")
    policy = policy.strip().lower()
    if policy not in {"block", "confirm"}:
        raise ValueError(
            "NIANG_IA_SENSITIVE_MISSION_POLICY must be 'block' or 'confirm'."
        )
    return policy

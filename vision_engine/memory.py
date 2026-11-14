"""Visual memory: what NIANG IA saw, and what changed since last time.

The memory stores *descriptions*, never pixels.  Screenshots are not written
to disk and no raw frame survives the observation that produced it.

Responsibilities:

* keep the previous observation so the engine can describe what changed,
* keep a per-mission context so a task can be resumed coherently,
* remember actions that already failed so they are not repeated blindly.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from .config import VisionConfig
from .scene import ScreenObservation


def _signature(tool: str, params: dict[str, Any]) -> str:
    """Stable fingerprint of an attempted action."""
    payload = json.dumps(
        {"tool": str(tool or ""), "params": params or {}},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class VisualMemory:
    """Contextual visual memory with mission tracking and failure history."""

    def __init__(
        self,
        config: VisionConfig | None = None,
        path: str | Path | None = None,
    ) -> None:
        self._config = config or VisionConfig()
        self._lock = threading.RLock()
        self._path = Path(path) if path else None
        self._observations: deque[dict[str, Any]] = deque(
            maxlen=max(1, int(self._config.memory_retention))
        )
        self._missions: dict[str, dict[str, Any]] = {}
        self._failures: deque[dict[str, Any]] = deque(
            maxlen=max(1, int(self._config.max_failures))
        )
        self._current_mission: str | None = None
        self._last_observation: ScreenObservation | None = None

    # ── Persistence ─────────────────────────────────────────────────────────
    @property
    def path(self) -> Path | None:
        return self._path

    def load(self) -> bool:
        """Load the persisted memory (failures and mission context)."""
        if not self._path or not self._path.exists():
            return False
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return False
        with self._lock:
            for item in data.get("failures", [])[-self._failures.maxlen :]:
                self._failures.append(dict(item))
            for key, value in (data.get("missions") or {}).items():
                self._missions[key] = dict(value)
        return True

    def save(self) -> bool:
        """Persist failures and mission context (no pixels, no raw frames)."""
        if not self._path:
            return False
        with self._lock:
            payload = {
                "version": 1,
                "updated_at": time.time(),
                "failures": list(self._failures),
                "missions": {k: dict(v) for k, v in self._missions.items()},
            }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(self._path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, indent=2, default=str), encoding="utf-8"
            )
            os.replace(temporary, self._path)
            return True
        except Exception:
            return False

    # ── Observations ────────────────────────────────────────────────────────
    def record(self, observation: ScreenObservation) -> None:
        """Store an observation (descriptions only) as the new reference."""
        summary = observation.to_dict()
        with self._lock:
            self._last_observation = observation
            self._observations.append(summary)
            mission = self._current_mission
            if mission:
                context = self._missions.setdefault(
                    mission,
                    {"mission_id": mission, "observations": [], "started_at": time.time()},
                )
                context["observations"] = (context.get("observations") or [])[-20:] + [
                    {
                        "observed_at": summary["observed_at"],
                        "app_name": summary["app_name"],
                        "window_title": summary["window_title"],
                        "changed": summary["changed"],
                        "change_score": summary["change_score"],
                        "text_preview": _preview(summary.get("text", "")),
                    }
                ]
                context["updated_at"] = time.time()
                context["observation_count"] = len(context["observations"])

    def previous(self) -> ScreenObservation | None:
        """The observation recorded before the current one."""
        with self._lock:
            if len(self._observations) < 2:
                return None
            return self._observations[-2]  # type: ignore[return-value]

    def last(self) -> ScreenObservation | None:
        with self._lock:
            return self._last_observation

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._observations)[-max(1, int(limit)):]
        return [dict(item) for item in reversed(items)]

    def diff(self, current: ScreenObservation | dict[str, Any]) -> dict[str, Any]:
        """Describe what changed between the previous observation and now."""
        current_dict = current.to_dict() if isinstance(current, ScreenObservation) else dict(current)
        with self._lock:
            previous = (
                self._observations[-2] if len(self._observations) >= 2 else None
            )
            if previous is None and len(self._observations) == 1:
                previous = self._observations[0]
        if previous is None:
            return {
                "first_observation": True,
                "app_changed": False,
                "window_changed": False,
                "added_text": [],
                "removed_text": [],
                "new_elements": [],
                "removed_elements": [],
            }

        previous_elements = {
            str(item.get("name") or item.get("automation_id") or "")
            for item in previous.get("elements", [])
        }
        current_elements = {
            str(item.get("name") or item.get("automation_id") or "")
            for item in current_dict.get("elements", [])
        }
        previous_lines = {
            line.strip() for line in str(previous.get("text", "")).splitlines() if line.strip()
        }
        current_lines = {
            line.strip() for line in str(current_dict.get("text", "")).splitlines() if line.strip()
        }
        return {
            "first_observation": False,
            "app_changed": previous.get("app_name") != current_dict.get("app_name"),
            "window_changed": previous.get("window_title")
            != current_dict.get("window_title"),
            "previous_app": previous.get("app_name", ""),
            "previous_window": previous.get("window_title", ""),
            "added_text": sorted(current_lines - previous_lines)[:20],
            "removed_text": sorted(previous_lines - current_lines)[:20],
            "new_elements": sorted(current_elements - previous_elements)[:20],
            "removed_elements": sorted(previous_elements - current_elements)[:20],
            "change_score": current_dict.get("change_score", 0.0),
        }

    # ── Missions ────────────────────────────────────────────────────────────
    def start_mission(self, mission_id: str, goal: str = "") -> dict[str, Any]:
        with self._lock:
            self._current_mission = str(mission_id or "")
            context = self._missions.setdefault(
                str(mission_id or ""),
                {"mission_id": str(mission_id or ""), "observations": []},
            )
            context.setdefault("goal", goal)
            context.setdefault("started_at", time.time())
            context["updated_at"] = time.time()
            return dict(context)

    def end_mission(self) -> str | None:
        with self._lock:
            mission = self._current_mission
            self._current_mission = None
            return mission

    @property
    def current_mission(self) -> str | None:
        return self._current_mission

    def mission_context(self, mission_id: str | None = None) -> dict[str, Any]:
        key = mission_id or self._current_mission
        if not key:
            return {}
        with self._lock:
            context = self._missions.get(key)
            return dict(context) if context else {}

    # ── Failure history ─────────────────────────────────────────────────────
    def remember_failure(
        self,
        tool: str,
        params: dict[str, Any],
        reason: str,
        *,
        mission_id: str | None = None,
    ) -> str:
        """Record that an action failed so it is not blindly repeated."""
        signature = _signature(tool, params)
        entry = {
            "signature": signature,
            "tool": str(tool or ""),
            "reason": str(reason or "")[:300],
            "at": time.time(),
            "count": 1,
            "mission_id": mission_id or self._current_mission or "",
        }
        with self._lock:
            for existing in self._failures:
                if existing["signature"] == signature:
                    existing["count"] = int(existing.get("count", 1)) + 1
                    existing["reason"] = entry["reason"]
                    existing["at"] = entry["at"]
                    break
            else:
                self._failures.append(entry)
        self.save()
        return signature

    def is_repeated_failure(self, tool: str, params: dict[str, Any]) -> bool:
        signature = _signature(tool, params)
        with self._lock:
            return any(item["signature"] == signature for item in self._failures)

    def failure_count(self, tool: str, params: dict[str, Any]) -> int:
        signature = _signature(tool, params)
        with self._lock:
            for item in self._failures:
                if item["signature"] == signature:
                    return int(item.get("count", 1))
        return 0

    def failures(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._failures)[-max(1, int(limit)):]
        return [dict(item) for item in reversed(items)]

    def clear_failures(self) -> None:
        with self._lock:
            self._failures.clear()
        self.save()

    # ── Housekeeping ────────────────────────────────────────────────────────
    def clear(self) -> None:
        with self._lock:
            self._observations.clear()
            self._missions.clear()
            self._failures.clear()
            self._current_mission = None
            self._last_observation = None
        self.save()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "observations": len(self._observations),
                "missions": len(self._missions),
                "failures": len(self._failures),
                "current_mission": self._current_mission,
                "persisted": bool(self._path),
            }


def _preview(text: str, limit: int = 180) -> str:
    value = str(text or "").strip().replace("\n", " ")
    return value[:limit]


__all__ = ["VisualMemory"]

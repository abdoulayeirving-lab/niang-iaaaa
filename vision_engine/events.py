"""Structured events published by the vision engine.

The engine never blocks on a subscriber: a faulty callback must not be able to
stall screen monitoring.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

SEVERITIES = ("info", "notice", "warning", "error")

# Event types emitted by the engine (stable identifiers used by the UI and the
# agent tools).
EVENT_ENGINE_STARTED = "engine_started"
EVENT_ENGINE_STOPPED = "engine_stopped"
EVENT_ENGINE_ERROR = "engine_error"
EVENT_EMERGENCY_STOP = "emergency_stop"
EVENT_CAPTURE_LOST = "capture_lost"
EVENT_CAPTURE_RESTORED = "capture_restored"
EVENT_SCREEN_CHANGED = "screen_changed"
EVENT_SCREEN_STABLE = "screen_stable"
EVENT_WINDOW_FOCUSED = "window_focused"
EVENT_WINDOW_OPENED = "window_opened"
EVENT_WINDOW_CLOSED = "window_closed"
EVENT_OBSERVATION = "observation"
EVENT_PROBLEM_DETECTED = "problem_detected"
EVENT_PRIVACY_MODE = "privacy_mode"


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class VisionEvent:
    """One structured observation of the screen state."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    severity: str = "info"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "payload": dict(self.payload),
            "severity": self.severity,
            "timestamp": self.timestamp,
            "observed_at": _iso(self.timestamp),
        }


class VisionEventBus:
    """Thread-safe publish/subscribe bus with a bounded history."""

    def __init__(self, history: int = 200) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[int, Callable[[VisionEvent], None]] = {}
        self._next_token = 1
        self._history: deque[VisionEvent] = deque(maxlen=max(1, int(history)))
        self._dropped = 0

    # ── Subscription ────────────────────────────────────────────────────────
    def subscribe(self, callback: Callable[[VisionEvent], None]) -> int:
        if not callable(callback):
            raise TypeError("A vision event subscriber must be callable.")
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._subscribers[token] = callback
            return token

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._subscribers.pop(token, None)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    # ── Publication ─────────────────────────────────────────────────────────
    def publish(self, event: VisionEvent) -> None:
        with self._lock:
            self._history.append(event)
            subscribers = list(self._subscribers.values())
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                # A broken subscriber must never kill the monitoring loop.
                self._dropped += 1

    def emit(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        severity: str = "info",
    ) -> VisionEvent:
        event = VisionEvent(
            type=event_type,
            payload=dict(payload or {}),
            severity=severity if severity in SEVERITIES else "info",
        )
        self.publish(event)
        return event

    # ── History ─────────────────────────────────────────────────────────────
    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._history)[-max(1, int(limit)):]
        return [item.to_dict() for item in reversed(items)]

    def clear(self) -> None:
        with self._lock:
            self._history.clear()


__all__ = [
    "VisionEvent",
    "VisionEventBus",
    "SEVERITIES",
    "EVENT_ENGINE_STARTED",
    "EVENT_ENGINE_STOPPED",
    "EVENT_ENGINE_ERROR",
    "EVENT_EMERGENCY_STOP",
    "EVENT_CAPTURE_LOST",
    "EVENT_CAPTURE_RESTORED",
    "EVENT_SCREEN_CHANGED",
    "EVENT_SCREEN_STABLE",
    "EVENT_WINDOW_FOCUSED",
    "EVENT_WINDOW_OPENED",
    "EVENT_WINDOW_CLOSED",
    "EVENT_OBSERVATION",
    "EVENT_PROBLEM_DETECTED",
    "EVENT_PRIVACY_MODE",
]

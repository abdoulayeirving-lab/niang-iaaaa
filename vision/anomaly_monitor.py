"""Lightweight local anomaly monitoring over normalized vision events."""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from time import time
from typing import Iterable

from .vision_events import VisionEvent


@dataclass(slots=True)
class AnomalyConfig:
    warmup_frames: int = 10
    min_count_delta: int = 1


class AnomalyMonitor:
    """Learn a simple normal object profile and emit change events.

    The baseline is recomputed from a rolling window of the last
    ``warmup_frames`` observations so the monitor adapts to legitimate scene
    evolution instead of freezing on the warm-up average.
    """

    def __init__(self, config: AnomalyConfig | None = None):
        self.config = config or AnomalyConfig()
        self._frames = 0
        self._profile: Counter[str] = Counter()
        self._history: deque[Counter] = deque(maxlen=max(2, int(self.config.warmup_frames)))

    @property
    def ready(self) -> bool:
        return self._frames >= self.config.warmup_frames

    @property
    def profile(self) -> dict[str, int]:
        return dict(self._profile)

    def observe(self, events: Iterable[VisionEvent]) -> list[VisionEvent]:
        counts = Counter(
            event.label for event in events if event.type == "object_detected" and event.label
        )
        self._frames += 1
        window = list(self._history)
        if len(window) < self.config.warmup_frames:
            # Still warming up: accumulate totals to build the initial baseline.
            self._profile.update(counts)
            self._history.append(counts)
            return []
        if len(window) > self.config.warmup_frames:
            window = window[-self.config.warmup_frames:]
        totals: Counter[str] = Counter()
        for frame in window:
            totals.update(frame)
        baseline = {label: total / len(window) for label, total in totals.items()}
        changed: dict[str, tuple[float, int]] = {}
        for label in set(baseline) | set(counts):
            base = baseline.get(label, 0.0)
            current = counts.get(label, 0)
            if abs(current - base) >= self.config.min_count_delta:
                changed[label] = (base, current)
        self._history.append(counts)
        if not changed:
            return []
        return [VisionEvent(
            type="anomaly_detected", timestamp=time(), label="scene_change",
            confidence=1.0, metadata={"changes": changed, "baseline": baseline},
        )]


__all__ = ["AnomalyMonitor", "AnomalyConfig"]

"""Visual change detection between two screen signatures.

The detector is deliberately cheap: it works on a 160x90 grayscale thumbnail
and reports

* a scalar *score* (mean absolute pixel difference, 0-255),
* whether the change is significant relative to the current noise floor,
* the bounding boxes of the regions that actually changed.

Because the threshold adapts to the observed noise, a screen playing a video
does not keep the engine busy while a static desktop stays cheap.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .config import VisionConfig


@dataclass(slots=True)
class ChangeResult:
    """Outcome of one comparison."""

    score: float = 0.0
    threshold: float = 0.0
    changed: bool = False
    regions: list[tuple[int, int, int, int]] = field(default_factory=list)
    first_frame: bool = False

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 3),
            "threshold": round(self.threshold, 3),
            "changed": self.changed,
            "regions": [list(region) for region in self.regions],
            "first_frame": self.first_frame,
        }


class ChangeDetector:
    """Compares consecutive signatures and adapts to screen noise."""

    def __init__(self, config: VisionConfig | None = None) -> None:
        self._config = config or VisionConfig()
        self._lock = threading.RLock()
        self._previous: Any = None
        self._noise: deque[float] = deque(maxlen=24)
        self._baseline = self._config.base_change_threshold * 0.3
        self._last_score = 0.0

    # ── State ───────────────────────────────────────────────────────────────
    def reset(self) -> None:
        """Forget the previous signature (used after a capture loss)."""
        with self._lock:
            self._previous = None
            self._noise.clear()
            self._baseline = self._config.base_change_threshold * 0.3
            self._last_score = 0.0

    @property
    def threshold(self) -> float:
        with self._lock:
            return self._effective_threshold()

    @property
    def last_score(self) -> float:
        return self._last_score

    @property
    def noise_floor(self) -> float:
        with self._lock:
            return round(self._baseline, 3)

    def _effective_threshold(self) -> float:
        threshold = self._config.base_change_threshold
        adaptive = self._baseline * self._config.adaptive_multiplier
        return float(min(self._config.max_change_threshold, max(threshold, adaptive)))

    # ── Detection ───────────────────────────────────────────────────────────
    def update(self, signature: Any) -> ChangeResult:
        """Compare ``signature`` with the previous one."""
        import cv2
        import numpy as np

        with self._lock:
            if signature is None:
                return ChangeResult(first_frame=self._previous is None)
            previous = self._previous
            if previous is None or previous.shape != signature.shape:
                self._previous = signature.copy() if hasattr(signature, "copy") else signature
                return ChangeResult(
                    score=0.0,
                    threshold=self._effective_threshold(),
                    changed=False,
                    first_frame=True,
                )

            diff = cv2.absdiff(signature, previous)
            score = float(diff.mean())
            self._last_score = score
            threshold = self._effective_threshold()
            changed = score >= threshold

            if changed:
                # A change is signal, not noise: do not pollute the baseline.
                regions = self._regions(diff, signature.shape)
            else:
                regions = []
                self._noise.append(score)
                if len(self._noise) >= 4:
                    self._baseline = float(sum(self._noise) / len(self._noise))

            self._previous = signature.copy() if hasattr(signature, "copy") else signature
            return ChangeResult(
                score=score,
                threshold=threshold,
                changed=changed,
                regions=regions,
                first_frame=False,
            )

    # ── Region localisation ──────────────────────────────────────────────────
    def _regions(
        self, diff: Any, shape: tuple[int, int]
    ) -> list[tuple[int, int, int, int]]:
        """Locate the blocks that changed, in *signature* coordinates."""
        import cv2
        import numpy as np

        grid_x, grid_y = self._config.region_grid
        height, width = shape[:2]
        try:
            small = cv2.resize(
                diff, (max(1, grid_x * 4), max(1, grid_y * 4)), interpolation=cv2.INTER_AREA
            )
        except Exception:
            return []
        block_h = max(1, small.shape[0] // grid_y)
        block_w = max(1, small.shape[1] // grid_x)
        mask = np.zeros((grid_y, grid_x), dtype=np.uint8)
        threshold = max(self._config.region_min_score, self._last_score * 0.45)
        for row in range(grid_y):
            for col in range(grid_x):
                y0, x0 = row * block_h, col * block_w
                y1 = min(small.shape[0], y0 + block_h)
                x1 = min(small.shape[1], x0 + block_w)
                if y1 <= y0 or x1 <= x0:
                    continue
                if float(small[y0:y1, x0:x1].mean()) >= threshold:
                    mask[row, col] = 1
        if not mask.any():
            return []

        count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask, 8)
        regions: list[tuple[int, int, int, int]] = []
        for index in range(1, count):
            x, y, w, h, _area = stats[index]
            left = int(x * width / grid_x)
            top = int(y * height / grid_y)
            region_w = max(1, int(w * width / grid_x))
            region_h = max(1, int(h * height / grid_y))
            regions.append((left, top, region_w, region_h))
        return regions


__all__ = ["ChangeDetector", "ChangeResult"]

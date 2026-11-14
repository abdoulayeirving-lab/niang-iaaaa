"""Test doubles for the NIANG IA continuous vision engine.

They make the engine tests deterministic and fast: no real screen capture,
no Tesseract, no UI Automation.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import numpy as np

from vision_engine.capture import CaptureFrame, MonitorInfo
from vision_engine.elements import InteractiveElement
from vision_engine.ocr import TextBlock
from vision_engine.windows import WindowInfo


def solid_image(width: int = 320, height: int = 200, value: int = 10) -> np.ndarray:
    """A uniform BGR image."""
    return np.full((height, width, 3), value, dtype=np.uint8)


def noisy_image(width: int = 320, height: int = 200, seed: int = 1) -> np.ndarray:
    """A deterministic pseudo-random BGR image."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (height, width, 3), dtype=np.uint8)


def signature_of(image: np.ndarray, size: tuple[int, int] = (160, 90)) -> np.ndarray:
    """Downscale an image the same way the real capture layer does."""
    import cv2

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.resize(gray, size, interpolation=cv2.INTER_AREA)


def window(
    hwnd: int = 100,
    title: str = "Test window",
    process: str = "app.exe",
    foreground: bool = False,
    visible: bool = True,
    minimized: bool = False,
    bounds: dict[str, int] | None = None,
) -> WindowInfo:
    return WindowInfo(
        hwnd=hwnd,
        title=title,
        pid=4242,
        process_name=process,
        class_name="TestClass",
        visible=visible,
        minimized=minimized,
        foreground=foreground,
        bounds=bounds if bounds is not None else {"left": 0, "top": 0, "width": 800, "height": 600},
        role="main",
    )


class FakeCapture:
    """Deterministic capture backend."""

    def __init__(
        self,
        images: list[np.ndarray] | None = None,
        monitors: list[MonitorInfo] | None = None,
    ) -> None:
        self.images = list(images or [solid_image()])
        self._monitors = list(
            monitors
            or [
                MonitorInfo(
                    index=1,
                    left=0,
                    top=0,
                    width=320,
                    height=200,
                    primary=True,
                    name="fake-1",
                )
            ]
        )
        self._index = 0
        self._lock = threading.RLock()
        self.grabs = 0
        self.full_grabs = 0
        self.closed = False
        self.error: str | None = None
        self._failures = 0

    # ── Backend API ─────────────────────────────────────────────────────────
    def open(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True

    def monitors(self) -> list[MonitorInfo]:
        return list(self._monitors)

    def monitor_count(self) -> int:
        return len(self._monitors)

    @property
    def captures(self) -> int:
        return self.grabs

    @property
    def failures(self) -> int:
        return self._failures

    @property
    def is_open(self) -> bool:
        return not self.closed

    def grab(self, *, want_full: bool = False) -> CaptureFrame | None:
        with self._lock:
            self.grabs += 1
            if self.error is not None:
                self._failures += 1
                return None
            image = self.images[min(self._index, len(self.images) - 1)]
            self._index += 1
            if want_full:
                self.full_grabs += 1
            return CaptureFrame(
                timestamp=time.time(),
                signature=signature_of(image),
                image=image.copy() if want_full else None,
                monitors=self.monitors(),
                width=int(image.shape[1]),
                height=int(image.shape[0]),
            )

    # ── Test controls ───────────────────────────────────────────────────────
    def set_images(self, images: list[np.ndarray]) -> None:
        with self._lock:
            self.images = list(images)
            self._index = 0

    def break_capture(self, error: str = "Screen capture failed: fake failure") -> None:
        """Make the next captures fail."""
        with self._lock:
            self.error = error

    def repair_capture(self) -> None:
        with self._lock:
            self.error = None
            self._index = 0


class FakeTracker:
    """Window tracker returning a scripted list of windows."""

    def __init__(self, windows: list[WindowInfo] | None = None) -> None:
        self.windows = list(windows or [])
        self._previous: dict[int, WindowInfo] = {}
        self.error: str | None = None
        self.snapshots = 0

    def snapshot(self, **_kwargs) -> list[WindowInfo]:
        self.snapshots += 1
        return list(self.windows)

    def foreground_hwnd(self) -> int:
        for item in self.windows:
            if item.foreground:
                return item.hwnd
        return 0

    def foreground(self) -> WindowInfo | None:
        for item in self.windows:
            if item.foreground:
                return item
        return None

    def diff(self, current: list[WindowInfo]) -> dict[str, Any]:
        previous = self._previous
        current_map = {item.hwnd: item for item in current}
        opened = [current_map[h].to_dict() for h in current_map if h not in previous]
        closed = [previous[h].to_dict() for h in previous if h not in current_map]
        focused_before = next((i.hwnd for i in previous.values() if i.foreground), 0)
        focused_after = next((i.hwnd for i in current if i.foreground), 0)
        self._previous = current_map
        return {
            "opened": opened,
            "closed": closed,
            "focus_changed": focused_before != focused_after,
            "focused_hwnd": focused_after,
            "previous_focused_hwnd": focused_before,
        }

    def remember(self, windows: list[WindowInfo]) -> None:
        self._previous = {item.hwnd: item for item in windows}

    def set_windows(self, windows: list[WindowInfo]) -> None:
        self.windows = list(windows)


class FakeInspector:
    """UI Automation inspector returning scripted elements."""

    def __init__(self, elements: list[InteractiveElement] | None = None) -> None:
        self.elements = list(elements or [])
        self.error: str | None = None
        self.calls = 0

    @property
    def available(self) -> bool:
        return True

    def inspect(self, hwnd: int) -> list[InteractiveElement]:
        self.calls += 1
        return list(self.elements)


class FakeOCR:
    """Local OCR returning scripted text blocks."""

    def __init__(self, blocks: list[TextBlock] | None = None) -> None:
        self.blocks = list(blocks or [])
        self.error: str | None = None
        self.reads = 0
        self.regions: list[Any] = []

    def available(self) -> bool:
        return True

    def reset(self) -> None:
        self.error = None

    def read(
        self,
        frame: Any,
        origin: tuple[int, int] = (0, 0),
        region: tuple[int, int, int, int] | None = None,
    ) -> list[TextBlock]:
        self.reads += 1
        self.regions.append(region)
        if self.error:
            return []
        return list(self.blocks)


__all__ = [
    "solid_image",
    "noisy_image",
    "signature_of",
    "window",
    "FakeCapture",
    "FakeTracker",
    "FakeInspector",
    "FakeOCR",
]

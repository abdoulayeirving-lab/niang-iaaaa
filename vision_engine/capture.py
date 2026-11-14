"""Low-level Windows screen capture with a multi-monitor aware signature.

The engine only needs two things from the capture layer:

* a cheap *signature* (a small grayscale thumbnail) used for change detection,
* an optional full-resolution BGR frame used for OCR when a deep analysis is
  actually required.

Nothing is ever written to disk here.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from .config import VisionConfig


@dataclass(slots=True)
class MonitorInfo:
    """One physical display."""

    index: int
    left: int
    top: int
    width: int
    height: int
    primary: bool = False
    name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
            "primary": self.primary,
            "name": self.name,
        }


@dataclass(slots=True)
class CaptureFrame:
    """Result of a single capture."""

    timestamp: float
    signature: Any = None
    image: Any = None
    monitors: list[MonitorInfo] = field(default_factory=list)
    width: int = 0
    height: int = 0
    origin_x: int = 0
    origin_y: int = 0

    @property
    def has_image(self) -> bool:
        return self.image is not None


class ScreenCapture:
    """Thread-safe wrapper around ``mss`` screen grabs."""

    def __init__(self, config: VisionConfig | None = None) -> None:
        self._config = config or VisionConfig()
        self._lock = threading.RLock()
        self._mss: Any = None
        self._monitors: list[MonitorInfo] = []
        self._union: dict[str, int] | None = None
        self._error: str | None = None
        self._captures = 0
        self._failures = 0

    # ── Lifecycle ───────────────────────────────────────────────────────────
    def open(self) -> bool:
        """Open the underlying capture backend.  Safe to call repeatedly."""
        with self._lock:
            if self._mss is not None:
                return True
            try:
                import mss  # noqa: WPS433 - optional heavy dependency
            except Exception as exc:
                self._error = f"Screen capture backend is unavailable: {exc}"
                return False
            try:
                self._mss = mss.MSS()
                self._read_monitors()
                self._error = None
                return True
            except Exception as exc:
                self._mss = None
                self._error = f"Screen capture backend failed to start: {exc}"
                return False

    def close(self) -> None:
        with self._lock:
            backend = self._mss
            self._mss = None
        if backend is not None:
            try:
                backend.close()
            except Exception:
                pass

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def captures(self) -> int:
        return self._captures

    @property
    def failures(self) -> int:
        return self._failures

    @property
    def is_open(self) -> bool:
        return self._mss is not None

    # ── Monitors ────────────────────────────────────────────────────────────
    def monitors(self) -> list[MonitorInfo]:
        with self._lock:
            if not self._monitors:
                self._read_monitors()
            return list(self._monitors)

    def monitor_count(self) -> int:
        return len(self.monitors())

    def _read_monitors(self) -> None:
        backend = self._mss
        if backend is None:
            return
        raw = list(getattr(backend, "monitors", []) or [])
        if not raw:
            self._monitors = []
            self._union = None
            return
        union = raw[0]
        self._union = {
            "left": int(union.get("left", 0)),
            "top": int(union.get("top", 0)),
            "width": int(union.get("width", 0)),
            "height": int(union.get("height", 0)),
        }
        monitors: list[MonitorInfo] = []
        for index, item in enumerate(raw[1:], start=1):
            monitors.append(
                MonitorInfo(
                    index=index,
                    left=int(item.get("left", 0)),
                    top=int(item.get("top", 0)),
                    width=int(item.get("width", 0)),
                    height=int(item.get("height", 0)),
                    primary=bool(item.get("is_primary", False)),
                    name=str(item.get("name", "") or ""),
                )
            )
        if not monitors and self._union:
            monitors.append(
                MonitorInfo(
                    index=1,
                    left=self._union["left"],
                    top=self._union["top"],
                    width=self._union["width"],
                    height=self._union["height"],
                    primary=True,
                    name="primary",
                )
            )
        self._monitors = monitors

    # ── Capture ─────────────────────────────────────────────────────────────
    def grab(self, *, want_full: bool = False) -> CaptureFrame | None:
        """Capture the whole desktop.  Returns ``None`` when capture failed."""
        import numpy as np

        with self._lock:
            if self._mss is None and not self.open():
                self._failures += 1
                return None
            backend = self._mss
            if backend is None:
                self._failures += 1
                return None
            try:
                shot = backend.grab(self._union)
            except Exception as exc:
                self._failures += 1
                self._error = f"Screen capture failed: {exc}"
                # Force a re-open on the next attempt: the handle may be dead.
                self._mss = None
                try:
                    backend.close()
                except Exception:
                    pass
                return None

            try:
                pixels = np.frombuffer(shot.raw, dtype=np.uint8).reshape(
                    shot.height, shot.width, 4
                )
            except Exception as exc:
                self._failures += 1
                self._error = f"Screen capture produced an unreadable buffer: {exc}"
                return None

            self._captures += 1
            self._error = None
            signature = self._signature(pixels)
            frame = CaptureFrame(
                timestamp=time.time(),
                signature=signature,
                monitors=self.monitors(),
                width=int(shot.width),
                height=int(shot.height),
                origin_x=int(self._union["left"]) if self._union else 0,
                origin_y=int(self._union["top"]) if self._union else 0,
            )
            if want_full:
                import cv2

                frame.image = cv2.cvtColor(pixels, cv2.COLOR_BGRA2BGR)
            return frame

    def _signature(self, pixels: Any) -> Any:
        """Downscale to a small grayscale thumbnail used for change detection."""
        import cv2

        width, height = self._config.signature_size
        reduced = cv2.resize(
            pixels, (max(8, int(width)), max(8, int(height))), interpolation=cv2.INTER_AREA
        )
        return cv2.cvtColor(reduced, cv2.COLOR_BGRA2GRAY)


__all__ = ["ScreenCapture", "CaptureFrame", "MonitorInfo"]

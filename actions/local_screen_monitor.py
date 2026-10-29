"""Local-only screen change sampling; screenshots are never persisted or uploaded."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Callable

SAMPLE_INTERVAL_SECONDS = 0.03
CHANGE_THRESHOLD = 4.0
SAMPLE_SIZE = (64, 36)


class LocalScreenMonitor:
    def __init__(
        self,
        capture_provider: Callable[[], tuple[bytes, int, int]] | None = None,
    ) -> None:
        self._capture_provider = capture_provider
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._error: str | None = None
        self._samples = 0
        self._changes = 0
        self._last_change_at: str | None = None
        self._last_difference = 0.0
        self._last_sample_at: float | None = None
        self._first_sample_at: float | None = None
        self._width: int | None = None
        self._height: int | None = None
        self._previous_frame: bytes | None = None

    def start(self) -> dict:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self.status()
            self._stop_event.clear()
            self._error = None
            self._samples = 0
            self._changes = 0
            self._last_change_at = None
            self._last_difference = 0.0
            self._last_sample_at = None
            self._first_sample_at = None
            self._width = None
            self._height = None
            self._previous_frame = None
            self._thread = threading.Thread(
                target=self._run,
                name="NIANG-LocalScreenMonitor",
                daemon=True,
            )
            self._thread.start()
            return self.status()

    def stop(self) -> dict:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        return self.status()

    def status(self) -> dict:
        with self._lock:
            alive = self._thread is not None and self._thread.is_alive()
            if self._error:
                state = "error"
            elif alive and self._samples == 0:
                state = "starting"
            elif alive:
                state = "running"
            else:
                state = "stopped"
            elapsed = (
                max(0.0, self._last_sample_at - self._first_sample_at)
                if self._first_sample_at is not None and self._last_sample_at is not None
                else 0.0
            )
            return {
                "state": state,
                "target_interval_ms": int(SAMPLE_INTERVAL_SECONDS * 1000),
                "samples": self._samples,
                "changes_detected": self._changes,
                "last_change_utc": self._last_change_at,
                "last_mean_pixel_difference": round(self._last_difference, 2),
                "average_samples_per_second": (
                    round((self._samples - 1) / elapsed, 1)
                    if elapsed > 0 and self._samples > 1
                    else None
                ),
                "screen_width": self._width,
                "screen_height": self._height,
                "privacy": "local only; no screenshot or screen text is saved or sent to Gemini",
                "error": self._error,
            }

    def _record_frame(
        self,
        frame: bytes,
        width: int,
        height: int,
        sampled_at: float,
    ) -> None:
        with self._lock:
            previous = self._previous_frame
            self._previous_frame = frame
            self._samples += 1
            self._width = int(width)
            self._height = int(height)
            self._last_sample_at = sampled_at
            if self._first_sample_at is None:
                self._first_sample_at = sampled_at
            if previous is None or len(previous) != len(frame):
                return

            difference = sum(abs(left - right) for left, right in zip(previous, frame))
            mean_difference = difference / max(1, len(frame))
            self._last_difference = mean_difference
            if mean_difference >= CHANGE_THRESHOLD:
                self._changes += 1
                self._last_change_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def _capture_small_frame(screens) -> tuple[bytes, int, int]:
        import cv2
        import numpy as np

        monitor = screens.monitors[0]
        shot = screens.grab(monitor)
        raw = np.frombuffer(shot.raw, dtype=np.uint8).reshape(
            shot.size.height,
            shot.size.width,
            4,
        )
        reduced = cv2.resize(raw, SAMPLE_SIZE, interpolation=cv2.INTER_AREA)
        grayscale = cv2.cvtColor(reduced, cv2.COLOR_BGRA2GRAY)
        return grayscale.tobytes(), int(shot.size.width), int(shot.size.height)

    def _run(self) -> None:
        try:
            if self._capture_provider is None:
                import mss

                with mss.MSS() as screens:
                    self._sample_loop(lambda: self._capture_small_frame(screens))
            else:
                self._sample_loop(self._capture_provider)
        except Exception as exc:
            with self._lock:
                self._error = f"Local screen monitor failed: {exc}"

    def _sample_loop(self, capture: Callable[[], tuple[bytes, int, int]]) -> None:
        next_sample = time.monotonic()
        while not self._stop_event.is_set():
            frame, width, height = capture()
            self._record_frame(frame, width, height, time.monotonic())
            next_sample += SAMPLE_INTERVAL_SECONDS
            remaining = next_sample - time.monotonic()
            if remaining > 0:
                self._stop_event.wait(remaining)
            else:
                next_sample = time.monotonic()


_MONITOR = LocalScreenMonitor()


def start_monitor() -> dict:
    return _MONITOR.start()


def stop_monitor() -> dict:
    return _MONITOR.stop()


def monitor_status() -> dict:
    return _MONITOR.status()

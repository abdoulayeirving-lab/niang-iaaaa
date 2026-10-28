"""Opt-in webcam capture for Gemini Live video input."""

from __future__ import annotations

import threading
from collections.abc import Callable

from vision.camera_manager import CameraConfig, CameraManager, FramePacket


class LiveCamera:
    """Own a lightweight webcam capture used only while live video is enabled."""

    def __init__(
        self,
        manager_factory: Callable[[], CameraManager] | None = None,
    ):
        self._manager_factory = manager_factory or (
            lambda: CameraManager(CameraConfig(index=0, width=640, height=480, fps=15))
        )
        self._lock = threading.Lock()
        self._manager: CameraManager | None = None

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._manager is not None

    def start(self) -> None:
        with self._lock:
            if self._manager is not None:
                return
            manager = self._manager_factory()
            if not manager.start():
                error = manager.error or "The webcam could not be opened."
                manager.stop()
                raise RuntimeError(error)
            self._manager = manager

    def stop(self) -> bool:
        with self._lock:
            manager = self._manager
            self._manager = None
        if manager is None:
            return False
        manager.stop()
        return True

    def latest_jpeg(self) -> tuple[int, bytes] | None:
        with self._lock:
            manager = self._manager
        if manager is None:
            return None

        packet: FramePacket | None = manager.latest()
        if packet is None:
            return None

        import cv2

        ok, encoded = cv2.imencode(
            ".jpg",
            packet.frame,
            [cv2.IMWRITE_JPEG_QUALITY, 70],
        )
        if not ok:
            raise RuntimeError("Could not encode the webcam frame.")
        return packet.sequence, encoded.tobytes()

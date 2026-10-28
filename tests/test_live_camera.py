import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from vision.live_camera import LiveCamera


class FakeCamera:
    def __init__(self, starts=True, error=None):
        self.starts = starts
        self.error = error
        self.stopped = False

    def start(self):
        return self.starts

    def stop(self):
        self.stopped = True

    def latest(self):
        return SimpleNamespace(frame="frame", sequence=4)


class LiveCameraTest(unittest.TestCase):
    def test_camera_requires_successful_start(self):
        camera = FakeCamera(starts=False, error="permission denied")
        live = LiveCamera(lambda: camera)

        with self.assertRaisesRegex(RuntimeError, "permission denied"):
            live.start()

        self.assertTrue(camera.stopped)
        self.assertFalse(live.is_active)

    def test_camera_stream_encodes_latest_frame_and_stops(self):
        camera = FakeCamera()
        live = LiveCamera(lambda: camera)
        cv2 = SimpleNamespace(
            IMWRITE_JPEG_QUALITY=1,
            imencode=lambda *args: (True, SimpleNamespace(tobytes=lambda: b"jpeg")),
        )

        live.start()
        with patch.dict(sys.modules, {"cv2": cv2}):
            self.assertEqual(live.latest_jpeg(), (4, b"jpeg"))

        self.assertTrue(live.stop())
        self.assertTrue(camera.stopped)
        self.assertFalse(live.is_active)


if __name__ == "__main__":
    unittest.main()

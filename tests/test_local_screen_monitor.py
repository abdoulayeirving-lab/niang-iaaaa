import threading
import unittest

from actions.local_screen_monitor import LocalScreenMonitor, SAMPLE_INTERVAL_SECONDS


class LocalScreenMonitorTests(unittest.TestCase):
    def test_monitor_samples_locally_and_reports_only_change_metadata(self):
        captured = threading.Event()
        calls = 0

        def capture():
            nonlocal calls
            calls += 1
            captured.set()
            return (bytes([0 if calls == 1 else 255]) * (64 * 36), 1920, 1080)

        monitor = LocalScreenMonitor(capture_provider=capture)
        try:
            started = monitor.start()
            self.assertIn(started["state"], {"starting", "running"})
            self.assertTrue(captured.wait(timeout=2))
            self.assertTrue(
                self._wait_for(lambda: monitor.status()["samples"] >= 2),
                "monitor did not collect two local samples",
            )
            status = monitor.status()
        finally:
            stopped = monitor.stop()

        self.assertEqual(status["target_interval_ms"], 30)
        self.assertGreaterEqual(status["changes_detected"], 1)
        self.assertEqual(status["screen_width"], 1920)
        self.assertEqual(status["screen_height"], 1080)
        self.assertIn("no screenshot", status["privacy"])
        self.assertNotIn("image", status)
        self.assertNotIn("frame", status)
        self.assertEqual(stopped["state"], "stopped")

    def test_status_does_not_expose_frame_pixels_or_screen_text(self):
        monitor = LocalScreenMonitor()
        monitor._record_frame(b"\x10" * (64 * 36), 800, 600, 1.0)
        monitor._record_frame(b"\x20" * (64 * 36), 800, 600, 1.03)

        status = monitor.status()

        self.assertEqual(status["changes_detected"], 1)
        self.assertNotIn("pixels", status)
        self.assertNotIn("text", status)
        self.assertNotIn("screenshot", status)

    @staticmethod
    def _wait_for(predicate, timeout=2):
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(SAMPLE_INTERVAL_SECONDS / 2)
        return predicate()


if __name__ == "__main__":
    unittest.main()

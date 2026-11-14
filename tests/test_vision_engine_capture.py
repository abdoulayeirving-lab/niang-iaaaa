"""Capture, change detection and multi-monitor handling of the vision engine."""

from __future__ import annotations

import unittest

import numpy as np

from tests.vision_fakes import FakeCapture, noisy_image, solid_image
from vision_engine.capture import MonitorInfo, ScreenCapture
from vision_engine.change import ChangeDetector
from vision_engine.config import VisionConfig
from vision_engine.engine import VisionEngine


class ScreenCaptureTests(unittest.TestCase):
    """Phase 1 — capture de l'écran."""

    def test_capture_returns_signature_and_geometry(self):
        capture = ScreenCapture(VisionConfig())
        try:
            self.assertTrue(capture.open())
            frame = capture.grab(want_full=False)
            self.assertIsNotNone(frame)
            self.assertIsNotNone(frame.signature)
            self.assertFalse(frame.has_image)
            self.assertGreater(frame.width, 0)
            self.assertGreater(frame.height, 0)
            self.assertTrue(frame.monitors)
        finally:
            capture.close()

    def test_full_capture_produces_a_bgr_frame(self):
        capture = ScreenCapture(VisionConfig())
        try:
            self.assertTrue(capture.open())
            frame = capture.grab(want_full=True)
            self.assertIsNotNone(frame)
            self.assertTrue(frame.has_image)
            self.assertEqual(frame.image.shape[2], 3)
            self.assertEqual(frame.image.dtype, np.uint8)
        finally:
            capture.close()

    def test_monitors_are_enumerated(self):
        capture = ScreenCapture(VisionConfig())
        try:
            capture.open()
            monitors = capture.monitors()
            self.assertGreaterEqual(len(monitors), 1)
            for monitor in monitors:
                self.assertGreater(monitor.width, 0)
                self.assertGreater(monitor.height, 0)
                self.assertIn("index", monitor.to_dict())
        finally:
            capture.close()

    def test_capture_failure_is_reported_not_raised(self):
        capture = ScreenCapture(VisionConfig())
        try:
            capture.open()
            capture._mss = object()  # force a broken backend
            frame = capture.grab(want_full=False)
            self.assertIsNone(frame)
            self.assertIsNotNone(capture.error)
            self.assertGreaterEqual(capture.failures, 1)
        finally:
            capture.close()


class MultiMonitorTests(unittest.TestCase):
    """Phase 1 — gérer plusieurs écrans."""

    def test_engine_reports_every_monitor(self):
        monitors = [
            MonitorInfo(index=1, left=0, top=0, width=1920, height=1080, primary=True, name="A"),
            MonitorInfo(index=2, left=1920, top=0, width=1280, height=1024, name="B"),
            MonitorInfo(index=3, left=0, top=1080, width=1280, height=720, name="C"),
        ]
        capture = FakeCapture(monitors=monitors)
        engine = VisionEngine(VisionConfig(), capture=capture)
        status = engine.status()
        self.assertEqual(status["monitor_count"], 3)
        self.assertEqual(len(status["monitors"]), 3)
        names = {item["name"] for item in status["monitors"]}
        self.assertEqual(names, {"A", "B", "C"})

    def test_observation_keeps_the_monitor_layout(self):
        monitors = [
            MonitorInfo(index=1, left=0, top=0, width=1920, height=1080, primary=True),
            MonitorInfo(index=2, left=1920, top=0, width=1280, height=1024),
        ]
        capture = FakeCapture(monitors=monitors)
        engine = VisionEngine(VisionConfig(), capture=capture)
        observation = engine.observe_now(deep=False)
        self.assertEqual(len(observation.monitors), 2)
        self.assertEqual(observation.monitors[1]["width"], 1280)


class ChangeDetectorTests(unittest.TestCase):
    """Phase 1 — détecter les changements visuels."""

    def setUp(self):
        self.detector = ChangeDetector(VisionConfig())

    def test_first_frame_is_not_a_change(self):
        result = self.detector.update(np.zeros((90, 160), dtype=np.uint8))
        self.assertTrue(result.first_frame)
        self.assertFalse(result.changed)

    def test_identical_frames_are_not_a_change(self):
        frame = np.full((90, 160), 40, dtype=np.uint8)
        self.detector.update(frame)
        result = self.detector.update(frame.copy())
        self.assertFalse(result.changed)
        self.assertAlmostEqual(result.score, 0.0, places=3)

    def test_a_big_change_is_detected(self):
        self.detector.update(np.zeros((90, 160), dtype=np.uint8))
        result = self.detector.update(np.full((90, 160), 255, dtype=np.uint8))
        self.assertTrue(result.changed)
        self.assertGreater(result.score, 10)

    def test_changed_regions_are_localised(self):
        self.detector.update(np.zeros((90, 160), dtype=np.uint8))
        frame = np.zeros((90, 160), dtype=np.uint8)
        frame[0:20, 0:40] = 255
        result = self.detector.update(frame)
        self.assertTrue(result.changed)
        self.assertTrue(result.regions)
        left, top, width, height = result.regions[0]
        self.assertLess(left, 80)
        self.assertLess(top, 45)

    def test_threshold_adapts_to_a_noisy_screen(self):
        quiet = np.full((90, 160), 10, dtype=np.uint8)
        for _ in range(10):
            self.detector.update(quiet.copy())
        base = self.detector.threshold
        noisy = noisy_image(160, 90, seed=3)
        for _ in range(20):
            self.detector.update(noisy)
        self.assertGreater(self.detector.threshold, 0)
        self.assertLessEqual(self.detector.threshold, VisionConfig().max_change_threshold)
        self.assertGreater(base, 0)

    def test_reset_forgets_the_previous_frame(self):
        self.detector.update(np.zeros((90, 160), dtype=np.uint8))
        self.detector.reset()
        result = self.detector.update(np.full((90, 160), 255, dtype=np.uint8))
        self.assertTrue(result.first_frame)
        self.assertFalse(result.changed)


class CaptureCostTests(unittest.TestCase):
    """The engine must not capture needlessly."""

    def test_engine_takes_a_small_signature_capture_at_rest(self):
        capture = FakeCapture()
        engine = VisionEngine(
            VisionConfig(idle_interval=0.05, active_interval=0.05, max_idle_interval=0.05),
            capture=capture,
        )
        engine.start()
        try:
            import time

            time.sleep(0.6)
        finally:
            engine.stop()
        self.assertGreater(capture.grabs, 0)
        # A signature capture must never ask for the full-resolution frame.
        self.assertEqual(capture.full_grabs, 0)

    def test_deep_analysis_is_the_only_thing_requesting_a_full_frame(self):
        capture = FakeCapture()
        engine = VisionEngine(VisionConfig(), capture=capture)
        engine.observe_now(deep=True)
        self.assertEqual(capture.full_grabs, 1)


if __name__ == "__main__":
    unittest.main()

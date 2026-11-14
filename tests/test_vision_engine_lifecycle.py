"""Engine lifecycle: capture loss, restart, emergency stop, privacy mode."""

from __future__ import annotations

import time
import unittest

from tests.vision_fakes import FakeCapture, FakeInspector, FakeOCR, FakeTracker, window
from vision_engine.config import VisionConfig
from vision_engine.engine import (
    STATE_DEGRADED,
    STATE_EMERGENCY,
    STATE_PRIVACY,
    STATE_RUNNING,
    STATE_STOPPED,
    VisionEngine,
)
from vision_engine.events import (
    EVENT_CAPTURE_LOST,
    EVENT_CAPTURE_RESTORED,
    EVENT_EMERGENCY_STOP,
    EVENT_ENGINE_STARTED,
    EVENT_ENGINE_STOPPED,
)


def _fast_config(**overrides) -> VisionConfig:
    config = VisionConfig(
        idle_interval=0.05,
        active_interval=0.05,
        max_idle_interval=0.05,
        window_poll_interval=0.05,
        deep_min_interval=0.0,
        stable_samples=1,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


class CaptureLossTests(unittest.TestCase):
    """Phase 7 — perte de capture."""

    def test_engine_degrades_and_recovers_when_capture_breaks(self):
        capture = FakeCapture()
        engine = VisionEngine(_fast_config(), capture=capture)
        events = []
        engine.subscribe(events.append)
        engine.start()
        try:
            time.sleep(0.25)
            self.assertEqual(engine.status()["state"], STATE_RUNNING)

            capture.break_capture()
            self.assertTrue(
                _wait_for(lambda: engine.status()["state"] == STATE_DEGRADED, 3),
                "the engine did not report the capture loss",
            )
            self.assertEqual(engine.status()["state"], STATE_DEGRADED)
            self.assertGreaterEqual(engine.status()["capture_failures"], 1)
            self.assertTrue(
                any(event.type == EVENT_CAPTURE_LOST for event in events),
                "the capture loss was not published",
            )

            capture.repair_capture()
            self.assertTrue(
                _wait_for(lambda: engine.status()["state"] == STATE_RUNNING, 3),
                "the engine did not recover after the capture was restored",
            )
            self.assertEqual(engine.status()["state"], STATE_RUNNING)
            self.assertTrue(
                any(event.type == EVENT_CAPTURE_RESTORED for event in events),
                "the capture recovery was not published",
            )
        finally:
            engine.stop()

    def test_degraded_observation_is_explicit(self):
        capture = FakeCapture()
        capture.break_capture()
        engine = VisionEngine(_fast_config(), capture=capture)
        observation = engine.observe_now(deep=True)
        self.assertEqual(observation.state, STATE_DEGRADED)
        self.assertIn("could not be captured", observation.note)


class EngineRestartTests(unittest.TestCase):
    """Phase 7 — redémarrage du moteur."""

    def test_restart_reinitialises_the_engine(self):
        capture = FakeCapture()
        engine = VisionEngine(_fast_config(), capture=capture)
        engine.start()
        time.sleep(0.2)
        self.assertGreater(engine.status()["captures"], 0)

        engine.restart()
        try:
            self.assertTrue(
                _wait_for(lambda: engine.status()["state"] == STATE_RUNNING, 3),
                "the engine did not restart",
            )
            self.assertTrue(capture.closed)
        finally:
            engine.stop()
        self.assertEqual(engine.status()["state"], STATE_STOPPED)

    def test_start_is_idempotent(self):
        engine = VisionEngine(_fast_config(), capture=FakeCapture())
        engine.start()
        engine.start()
        try:
            self.assertTrue(
                _wait_for(lambda: engine.status()["state"] == STATE_RUNNING, 3)
            )
        finally:
            engine.stop()

    def test_stop_releases_the_capture_backend(self):
        capture = FakeCapture()
        engine = VisionEngine(_fast_config(), capture=capture)
        engine.start()
        time.sleep(0.1)
        engine.stop()
        self.assertTrue(capture.closed)
        self.assertEqual(engine.status()["state"], STATE_STOPPED)


class EmergencyStopTests(unittest.TestCase):
    """Phase 5 + 7 — arrêt d'urgence."""

    def test_emergency_stop_cancels_every_capture(self):
        capture = FakeCapture()
        engine = VisionEngine(_fast_config(), capture=capture)
        events = []
        engine.subscribe(events.append)
        engine.start()
        time.sleep(0.15)

        engine.emergency_stop()
        status = engine.status()
        self.assertEqual(status["state"], STATE_EMERGENCY)
        self.assertTrue(status["emergency_stopped"])
        self.assertIsNone(engine.last_observation)
        self.assertTrue(
            any(event.type == EVENT_EMERGENCY_STOP for event in events),
            "the emergency stop was not published",
        )

        grabs_at_stop = capture.grabs
        time.sleep(0.25)
        self.assertEqual(capture.grabs, grabs_at_stop, "captures continued after the emergency stop")

    def test_emergency_stop_revokes_the_ocr_permission(self):
        engine = VisionEngine(_fast_config(), capture=FakeCapture())
        engine.set_ocr_permitted(True)
        self.assertTrue(engine.ocr_permitted)
        engine.emergency_stop()
        self.assertFalse(engine.ocr_permitted)

    def test_engine_refuses_to_restart_after_an_emergency_stop(self):
        engine = VisionEngine(_fast_config(), capture=FakeCapture())
        engine.start()
        engine.emergency_stop()
        status = engine.start()
        self.assertEqual(status["state"], STATE_EMERGENCY)
        self.assertFalse(status["running"])


class PrivacyModeTests(unittest.TestCase):
    """Phase 5 — mode confidentialité."""

    def test_privacy_mode_stops_every_capture(self):
        capture = FakeCapture()
        engine = VisionEngine(_fast_config(), capture=capture)
        engine.start()
        time.sleep(0.15)
        engine.set_privacy_mode(True)
        try:
            self.assertEqual(engine.status()["state"], STATE_PRIVACY)
            grabs = capture.grabs
            time.sleep(0.3)
            self.assertEqual(capture.grabs, grabs, "a capture happened during privacy mode")
        finally:
            engine.stop()

    def test_privacy_mode_returns_an_empty_observation(self):
        engine = VisionEngine(_fast_config(), capture=FakeCapture())
        engine.set_privacy_mode(True)
        observation = engine.observe_now(deep=True)
        self.assertTrue(observation.privacy_mode)
        self.assertEqual(observation.text, "")
        self.assertEqual(observation.elements, [])
        self.assertEqual(observation.app_name, "")


class ObservationTests(unittest.TestCase):
    """Phase 2 — représentation structurée de l'écran."""

    def test_observation_describes_the_active_application(self):
        tracker = FakeTracker([window(hwnd=1, title="Editor", process="editor.exe", foreground=True)])
        engine = VisionEngine(_fast_config(), capture=FakeCapture(), tracker=tracker)
        observation = engine.observe_now(deep=False)
        self.assertEqual(observation.app_name, "editor.exe")
        self.assertEqual(observation.window_title, "Editor")
        self.assertTrue(observation.foreground)
        self.assertIn("editor.exe", observation.summary())

    def test_deep_observation_collects_text_and_elements(self):
        from vision_engine.elements import InteractiveElement
        from vision_engine.ocr import TextBlock

        tracker = FakeTracker([window(hwnd=1, title="Editor", process="editor.exe", foreground=True)])
        inspector = FakeInspector(
            [
                InteractiveElement(name="Save", role="Button", kind="button", bounds={"left": 1, "top": 2, "width": 3, "height": 4}),
                InteractiveElement(name="Search", role="Edit", kind="field", bounds={"left": 5, "top": 6, "width": 7, "height": 8}),
            ]
        )
        ocr = FakeOCR([TextBlock(text="hello", confidence=0.9, left=10, top=20, width=30, height=10)])
        engine = VisionEngine(
            _fast_config(), capture=FakeCapture(), tracker=tracker, inspector=inspector, ocr=ocr
        )
        engine.set_ocr_permitted(True)
        observation = engine.observe_now(deep=True)
        self.assertTrue(observation.deep)
        self.assertEqual(len(observation.elements), 2)
        self.assertIn("hello", observation.text)
        self.assertEqual(observation.element_names("button"), ["Save"])
        self.assertEqual(observation.element_names("field"), ["Search"])

    def test_ocr_is_skipped_without_permission(self):
        from vision_engine.ocr import TextBlock

        ocr = FakeOCR([TextBlock(text="secret-ish", confidence=0.9)])
        engine = VisionEngine(_fast_config(), capture=FakeCapture(), ocr=ocr)
        observation = engine.observe_now(deep=True)
        self.assertEqual(observation.text, "")
        self.assertEqual(ocr.reads, 0)

    def test_ocr_is_restricted_to_the_focused_window(self):
        from vision_engine.ocr import TextBlock

        ocr = FakeOCR([TextBlock(text="x")])
        tracker = FakeTracker(
            [
                window(
                    hwnd=1,
                    title="Editor",
                    foreground=True,
                    bounds={"left": 100, "top": 50, "width": 400, "height": 300},
                )
            ]
        )
        engine = VisionEngine(_fast_config(), capture=FakeCapture(), tracker=tracker, ocr=ocr)
        engine.set_ocr_permitted(True)
        engine.observe_now(deep=True)
        self.assertEqual(ocr.regions[-1], (100, 50, 400, 300))


class ProblemDetectionTests(unittest.TestCase):
    """Phase 1 — détecter les nouveaux messages et erreurs."""

    def test_error_titles_are_reported(self):
        tracker = FakeTracker(
            [window(hwnd=1, title="Fatal error: cannot continue", foreground=True)]
        )
        engine = VisionEngine(_fast_config(), capture=FakeCapture(), tracker=tracker)
        observation = engine.observe_now(deep=True)
        self.assertTrue(observation.problems)
        self.assertIn(observation.problems[0]["kind"], {"error", "failure", "blocked"})

    def test_normal_windows_do_not_raise_problems(self):
        tracker = FakeTracker([window(hwnd=1, title="Untitled - Notepad", foreground=True)])
        engine = VisionEngine(_fast_config(), capture=FakeCapture(), tracker=tracker)
        observation = engine.observe_now(deep=True)
        self.assertEqual(observation.problems, [])


if __name__ == "__main__":
    unittest.main()

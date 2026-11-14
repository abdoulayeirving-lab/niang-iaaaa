"""Window recognition and interactive element discovery."""

from __future__ import annotations

import os
import unittest

from tests.vision_fakes import FakeTracker, window
from vision_engine.config import VisionConfig
from vision_engine.elements import UIAInspector
from vision_engine.engine import VisionEngine
from vision_engine.windows import WindowTracker

WINDOWS_ONLY = os.name == "nt"


class WindowTrackerTests(unittest.TestCase):
    """Phase 1 — identifier les fenêtres ouvertes."""

    @unittest.skipUnless(WINDOWS_ONLY, "Windows API required")
    def test_tracker_lists_the_real_desktop_windows(self):
        tracker = WindowTracker()
        windows = tracker.snapshot()
        self.assertIsInstance(windows, list)
        self.assertTrue(windows, "no window was found on this desktop")
        for item in windows:
            self.assertGreater(item.hwnd, 0)
            self.assertIsInstance(item.to_dict(), dict)
            self.assertIn("process_name", item.to_dict())

    @unittest.skipUnless(WINDOWS_ONLY, "Windows API required")
    def test_tracker_finds_a_foreground_window(self):
        tracker = WindowTracker()
        foreground = tracker.foreground()
        if foreground is None:
            self.skipTest("no foreground window in this session")
        self.assertTrue(foreground.foreground)
        self.assertGreater(foreground.hwnd, 0)

    @unittest.skipUnless(WINDOWS_ONLY, "Windows API required")
    def test_diff_detects_a_closed_window(self):
        tracker = WindowTracker()
        first = tracker.snapshot()
        tracker.remember(first)
        second = tracker.snapshot()
        diff = tracker.diff(second)
        self.assertIn("opened", diff)
        self.assertIn("closed", diff)
        self.assertIn("focus_changed", diff)

    def test_tracker_is_safe_on_other_platforms(self):
        tracker = WindowTracker()
        if os.name == "nt":
            self.skipTest("Windows only")
        self.assertEqual(tracker.snapshot(), [])


class WindowDiffTests(unittest.TestCase):
    """Phase 3 — comprendre les changements de l'écran."""

    def test_opened_and_closed_windows_are_detected(self):
        tracker = WindowTracker()
        tracker.remember([window(hwnd=1, title="One")])
        diff = tracker.diff([window(hwnd=2, title="Two", foreground=True)])
        self.assertEqual(len(diff["closed"]), 1)
        self.assertEqual(len(diff["opened"]), 1)
        self.assertTrue(diff["focus_changed"])

    def test_focus_change_is_reported(self):
        tracker = WindowTracker()
        tracker.remember([window(hwnd=1, foreground=True)])
        diff = tracker.diff([window(hwnd=1, foreground=False), window(hwnd=2, foreground=True)])
        self.assertTrue(diff["focus_changed"])
        self.assertEqual(diff["focused_hwnd"], 2)


class EngineWindowTests(unittest.TestCase):
    """Phase 2 — application active et fenêtre active."""

    def test_observation_exposes_the_active_window(self):
        tracker = FakeTracker(
            [
                window(hwnd=1, title="Explorer", process="explorer.exe", foreground=True),
                window(hwnd=2, title="Editor", process="editor.exe"),
            ]
        )
        engine = VisionEngine(VisionConfig(), capture=None, tracker=tracker)
        observation = engine.observe_now(deep=False)
        self.assertEqual(observation.app_name, "explorer.exe")
        self.assertEqual(observation.window_title, "Explorer")
        self.assertEqual(len(observation.windows), 2)
        self.assertEqual(observation.foreground["hwnd"], 1)

    def test_engine_publishes_window_events(self):
        tracker = FakeTracker([window(hwnd=1, title="Explorer", foreground=True)])
        engine = VisionEngine(VisionConfig(), capture=None, tracker=tracker)
        events = []
        engine.subscribe(events.append)
        engine._refresh_windows()
        kinds = {event.type for event in events}
        self.assertIn("window_opened", kinds)


class UIAInspectorTests(unittest.TestCase):
    """Phase 1 — identifier boutons, menus, champs et icônes."""

    @unittest.skipUnless(WINDOWS_ONLY, "UI Automation requires Windows")
    def test_inspector_reports_the_controls_of_a_real_window(self):
        inspector = UIAInspector(max_controls=40, timeout=8)
        tracker = WindowTracker()
        foreground = tracker.foreground()
        if foreground is None:
            self.skipTest("no foreground window in this session")
        elements = inspector.inspect(foreground.hwnd)
        self.assertIsInstance(elements, list)
        for element in elements:
            self.assertIn(element.kind, {
                "button", "field", "menu", "item", "icon", "other", "text",
            })
            self.assertIn("bounds", element.to_dict())

    def test_inspector_refuses_an_invalid_handle(self):
        inspector = UIAInspector(timeout=1)
        self.assertEqual(inspector.inspect(0), [])
        self.assertIsNotNone(inspector.error)

    def test_inspector_timeout_is_bounded(self):
        inspector = UIAInspector(timeout=0.2)
        inspector._collect = lambda hwnd: (_ for _ in ()).throw(RuntimeError("boom"))
        started = __import__("time").monotonic()
        elements = inspector.inspect(12345)
        elapsed = __import__("time").monotonic() - started
        self.assertEqual(elements, [])
        self.assertLess(elapsed, 3.0)
        self.assertIsNotNone(inspector.error)


if __name__ == "__main__":
    unittest.main()

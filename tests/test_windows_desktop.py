import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from agent.project_execution import ProjectExecutionManager
from agent.terminal_agent import TerminalAgent
from agent.windows_desktop import WindowsDesktopAgent, WindowsDesktopError
from vision.ocr_engine import OCRConfig, OCREngine


FIXTURE = Path(__file__).parent / "fixtures" / "desktop_app.py"


class WindowsDesktopUnitTests(unittest.TestCase):
    def test_native_window_enumeration_is_available_on_windows(self):
        if os.name != "nt":
            self.skipTest("Native window enumeration requires Windows.")
        windows = WindowsDesktopAgent().list_windows(include_untitled=True)
        self.assertIsInstance(windows, list)
        for window in windows:
            self.assertIn("pid", window)
            self.assertIn("hwnd", window)
            self.assertIn("minimized", window)
            self.assertIn(window["role"], {"main", "secondary"})

    def test_local_tesseract_recognizes_text_with_position(self):
        image = np.full((120, 700, 3), 255, dtype=np.uint8)
        cv2.putText(
            image,
            "LOCAL OCR TEST",
            (20, 82),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.8,
            (0, 0, 0),
            4,
            cv2.LINE_AA,
        )
        engine = OCREngine(OCRConfig(languages="eng", min_confidence=20, scale=1.0))

        events = engine.extract(image)

        self.assertTrue(engine.is_ready, engine.error)
        self.assertTrue(events)
        self.assertTrue(any(event.bbox and event.label for event in events))
        self.assertIn("LOCAL", " ".join(event.label.upper() for event in events))

    def test_targeted_actions_are_still_approval_gated(self):
        import safety

        for action in ("window_list", "window_observe", "window_click", "window_close"):
            with self.subTest(action=action):
                args = {"action": action}
                self.assertTrue(safety.needs_confirmation("computer_control", args))

    def test_coordinates_are_scoped_to_the_selected_window(self):
        window = {
            "bounds": {"left": 100, "top": 100, "width": 200, "height": 100},
        }

        WindowsDesktopAgent._validate_point(window, 150, 150)
        with self.assertRaises(WindowsDesktopError):
            WindowsDesktopAgent._validate_point(window, 20, 20)

    def test_window_handle_lookup_does_not_enumerate_the_entire_desktop(self):
        expected = {"hwnd": 42, "title": "Target"}
        with (
            patch("agent.windows_desktop._user32", return_value=object()),
            patch("agent.windows_desktop._window_record", return_value=expected),
            patch.object(
                WindowsDesktopAgent,
                "list_windows",
                side_effect=AssertionError("A direct handle lookup must not enumerate all windows."),
            ),
        ):
            self.assertEqual(WindowsDesktopAgent().window(hwnd=42), expected)

    def test_ocr_phrase_matching_combines_neighboring_words(self):
        events = [
            {"text": "Save", "bounds": (100, 100, 35, 18)},
            {"text": "project", "bounds": (141, 100, 58, 18)},
            {"text": "Cancel", "bounds": (100, 150, 50, 18)},
        ]

        matches = WindowsDesktopAgent._matching_text(events, "Save project")

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["text"], "Save project")
        self.assertEqual(matches[0]["bounds"], (100, 100, 99, 18))


@unittest.skipUnless(os.name == "nt", "Tkinter desktop integration requires Windows.")
class WindowsDesktopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "main.py").write_bytes(FIXTURE.read_bytes())
        (self.root / "requirements.txt").write_text("", encoding="utf-8")
        self.scenario_path = self.root / "scenario.json"
        self.environment = patch.dict(
            os.environ,
            {"NIANG_IA_WORKSPACE_ROOT": str(self.root)},
            clear=False,
        )
        self.environment.start()
        self.manager = ProjectExecutionManager(TerminalAgent())
        self.desktop = WindowsDesktopAgent()
        self.process_id = None
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        if self.process_id:
            try:
                status = self.manager.status(self.process_id)
                if status["state"] == "running":
                    self.manager.stop(self.process_id)
            except Exception:
                pass
        self.manager.terminal.close()
        self.environment.stop()
        self.temp.cleanup()

    def _start(self, mode):
        self.scenario_path.write_text(json.dumps({"mode": mode}), encoding="utf-8")
        result = self.manager.start(health_timeout_seconds=8)
        self.process_id = result.get("process_id")
        self.assertIsNotNone(self.process_id, result)
        return result

    def _wait_exited(self, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.manager.status(self.process_id)
            if status["state"] == "exited":
                return status
            time.sleep(0.05)
        self.fail("The test application did not exit within the timeout.")

    def _close_cleanly(self, hwnd):
        result = self.desktop.close(hwnd)
        self.assertTrue(result["verified"], result)
        status = self._wait_exited()
        self.assertEqual(status["exit_code"], 0)

    def test_tk_button_discovery_click_and_visible_state_verification(self):
        started = self._start("button")
        self.assertEqual(started["status"], "started", started)
        self.assertTrue(started["verified"])
        self.assertEqual(started["pid"], self.manager.status(self.process_id)["pid"])
        window = self.desktop.window(hwnd=started["hwnd"])
        observed = self.desktop.inspect(hwnd=window["hwnd"])
        self.assertTrue(observed["ocr_text"], observed)
        result = self.desktop.click_text(window["hwnd"], "Increment")
        self.assertTrue(result["verified"], result)
        verification = self.desktop.verify_text(window["hwnd"], "Count: 1")
        self.assertTrue(verification["verified"], verification)
        self._close_cleanly(window["hwnd"])

    def test_tk_form_fallback_types_and_saves_verified_value(self):
        started = self._start("form")
        self.assertTrue(started["verified"], started)
        window = self.desktop.window(hwnd=started["hwnd"])
        observation = self.desktop.inspect(hwnd=window["hwnd"])
        self.assertTrue(observation["ocr_text"], observation)
        bounds = window["bounds"]
        typed = self.desktop.type_text(
            window["hwnd"],
            "Local Test Project",
            x=bounds["left"] + 90,
            y=bounds["top"] + 170,
        )
        self.assertTrue(typed["verified"], typed)
        self.assertTrue(self.desktop.click_text(window["hwnd"], "Save project")["verified"])
        saved = self.desktop.verify_text(window["hwnd"], "Saved: Local Test Project")
        self.assertTrue(saved["verified"], saved)
        self._close_cleanly(window["hwnd"])

    def test_tk_multiple_windows_are_associated_with_process_and_owner(self):
        started = self._start("multi")
        self.assertTrue(started["verified"], started)
        windows = self.desktop.list_windows(pid=started["pid"])
        fixture_windows = [
            item for item in windows
            if item["title"].startswith("NIANG Desktop Fixture")
        ]
        self.assertGreaterEqual(len(fixture_windows), 2, windows)
        self.assertTrue(any(item["role"] == "main" for item in fixture_windows), windows)
        self.assertTrue(any(item["role"] == "secondary" for item in fixture_windows), windows)
        for item in fixture_windows:
            self.assertEqual(item["pid"], started["window_pid"])
        secondary = next(item for item in fixture_windows if item["role"] == "secondary")
        self.assertTrue(self.desktop.close(secondary["hwnd"])["verified"])
        self.assertFalse(any(
            item["hwnd"] == secondary["hwnd"]
            for item in self.desktop.list_windows(pid=started["pid"])
        ))
        main_window = self.desktop.window(hwnd=started["hwnd"])
        self._close_cleanly(main_window["hwnd"])

    def test_tk_dialog_is_discovered_and_closed_independently(self):
        started = self._start("dialog")
        self.assertTrue(started["verified"], started)
        windows = self.desktop.list_windows(pid=started["pid"])
        dialog = next(item for item in windows if item["title"].endswith("Dialog"))
        self.assertEqual(dialog["role"], "secondary")
        observed = self.desktop.inspect(hwnd=dialog["hwnd"])
        self.assertTrue(observed["ocr_text"], observed)
        self.assertTrue(self.desktop.click_text(dialog["hwnd"], "Close dialog")["verified"])
        self.assertFalse(any(
            item["hwnd"] == dialog["hwnd"]
            for item in self.desktop.list_windows(pid=started["pid"])
        ))
        main_window = self.desktop.window(hwnd=started["hwnd"])
        self._close_cleanly(main_window["hwnd"])

    def test_minimized_tk_window_is_detected_and_restored(self):
        started = self._start("minimized")
        self.assertTrue(started["verified"], started)
        time.sleep(1.0)
        window = self.desktop.window(hwnd=started["hwnd"])
        self.assertTrue(window["minimized"], window)
        restored = self.desktop.activate(window["hwnd"])
        self.assertTrue(restored["focused"], restored)
        self.assertFalse(restored["window"]["minimized"])
        self._close_cleanly(window["hwnd"])

    def test_tk_uncaught_exception_is_reported_with_exit_code_and_stderr(self):
        started = self._start("error")
        self.assertIn(started["status"], {"started", "failed"}, started)
        status = self._wait_exited()
        logs = self.manager.logs(self.process_id)
        self.assertNotEqual(status["exit_code"], 0)
        self.assertIn("INTENTIONAL_FIXTURE_ERROR", logs["stderr"])
        self.assertIn("intentional fixture stdout", logs["stdout"])
        self.assertEqual(self.desktop.list_windows(pid=status["pid"]), [])

    def test_selected_window_screenshot_is_saved_only_to_user_home(self):
        started = self._start("button")
        window = self.desktop.window(hwnd=started["hwnd"])
        screenshot_dir = Path(tempfile.mkdtemp(prefix="niang-desktop-test-"))
        try:
            path = screenshot_dir / "fixture.png"
            result = self.desktop.screenshot(window["hwnd"], str(path))
            self.assertTrue(path.is_file())
            self.assertTrue(result["saved_locally"])
            self.assertFalse(result["uploaded"])
        finally:
            shutil.rmtree(screenshot_dir)
        self._close_cleanly(window["hwnd"])


if __name__ == "__main__":
    unittest.main()

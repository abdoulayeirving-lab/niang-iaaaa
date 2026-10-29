import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions import computer_control, screen_processor


class ScreenPrivacyTests(unittest.TestCase):
    def test_screen_describe_and_visual_search_cannot_call_gemini(self):
        with self.assertRaisesRegex(RuntimeError, "never sends screenshots to Gemini"):
            computer_control._describe_screen()
        with self.assertRaisesRegex(RuntimeError, "never sends screenshots to Gemini"):
            computer_control._analyze_screen_for_element("a button")

    def test_computer_control_screen_visual_actions_are_blocked(self):
        for action in ("screen_describe", "screen_find", "screen_click"):
            with self.subTest(action=action):
                result = computer_control.computer_control({
                    "action": action,
                    "description": "a button",
                })
                self.assertIn("never sends screenshots to Gemini", result)

    def test_screen_process_reports_local_monitor_status_without_capture_or_upload(self):
        with (
            patch.object(screen_processor, "_capture_screenshot") as capture,
            patch.object(screen_processor, "_analyze_image_text") as analyze,
            patch(
                "actions.local_screen_monitor.monitor_status",
                return_value={"state": "running", "changes_detected": 4},
            ),
        ):
            result = screen_processor.screen_process({
                "angle": "screen",
                "text": "What is on screen?",
            })

        self.assertIn("never sends screenshots to Gemini", result)
        self.assertIn("changes detected: 4", result)
        capture.assert_not_called()
        analyze.assert_not_called()


if __name__ == "__main__":
    unittest.main()

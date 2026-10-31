import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions import computer_control, screen_processor
from vision.vision_events import VisionEvent


class ScreenPrivacyTests(unittest.TestCase):
    def test_local_vision_uses_ollama_and_never_uses_ocr_or_gemini(self):
        frame = object()
        with (
            patch.object(screen_processor, "_capture_screen_frame", return_value=frame),
            patch.object(screen_processor, "_encode_local_vision_frame", return_value=b"local-image"),
            patch.object(screen_processor, "_extract_screen_text") as extract_text,
            patch.object(screen_processor, "_analyze_image_text") as analyze,
            patch(
                "vision.local_vlm.describe_image",
                return_value="A browser window is open.",
            ) as describe,
        ):
            result = screen_processor.screen_process({
                "angle": "local_vision",
                "text": "What is shown?",
            })

        self.assertIn("A browser window is open.", result)
        self.assertIn("not sent to Gemini", result)
        describe.assert_called_once_with(b"local-image", "What is shown?")
        extract_text.assert_not_called()
        analyze.assert_not_called()

    def test_local_vision_reports_ollama_unavailable(self):
        with (
            patch.object(screen_processor, "_capture_screen_frame", return_value=object()),
            patch.object(screen_processor, "_encode_local_vision_frame", return_value=b"local-image"),
            patch(
                "vision.local_vlm.describe_image",
                side_effect=RuntimeError("Ollama is not running on this PC."),
            ),
        ):
            result = screen_processor.screen_process({
                "angle": "local_vision",
                "text": "Describe this screen.",
            })

        self.assertIn("Local screen vision failed", result)
        self.assertIn("Ollama is not running", result)

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

    def test_screen_process_sends_only_local_ocr_text_and_never_uploads_image(self):
        frame = object()
        with (
            patch.object(screen_processor, "_capture_screen_frame", return_value=frame) as capture_frame,
            patch.object(
                screen_processor,
                "_extract_screen_text",
                return_value="Browser title\nVisible page text",
            ) as extract_text,
            patch.object(screen_processor, "_analyze_image_text") as analyze,
            patch.object(screen_processor, "_capture_camera") as capture_camera,
        ):
            result = screen_processor.screen_process({
                "angle": "screen",
                "text": "What is on screen?",
            })

        self.assertIn("Browser title\nVisible page text", result)
        self.assertIn("screenshot itself was not sent", result)
        self.assertIn("untrusted", result.lower())
        capture_frame.assert_called_once_with()
        extract_text.assert_called_once_with(frame)
        analyze.assert_not_called()
        capture_camera.assert_not_called()

    def test_screen_process_reports_local_ocr_failures(self):
        with patch.object(
            screen_processor,
            "_capture_screen_frame",
            side_effect=RuntimeError("Tesseract is unavailable"),
        ):
            result = screen_processor.screen_process({
                "angle": "screen",
                "text": "Read this screen",
            })

        self.assertIn("Local screen OCR failed", result)
        self.assertIn("Tesseract is unavailable", result)

    def test_ocr_events_are_grouped_into_screen_lines(self):
        events = [
            VisionEvent(type="text_detected", label="world", bbox=(70, 12, 45, 16)),
            VisionEvent(type="text_detected", label="Hello", bbox=(10, 10, 50, 18)),
            VisionEvent(type="text_detected", label="Second line", bbox=(10, 42, 90, 18)),
        ]

        self.assertEqual(
            screen_processor._format_ocr_events(events),
            "Hello world\nSecond line",
        )

    def test_screen_process_limits_ocr_text(self):
        long_text = "A" * (screen_processor.MAX_SCREEN_OCR_CHARS + 10)
        with (
            patch.object(screen_processor, "_capture_screen_frame", return_value=object()),
            patch.object(screen_processor, "_extract_screen_text", return_value=long_text),
        ):
            result = screen_processor.screen_process({
                "angle": "screen",
                "text": "Read this screen",
            })

        self.assertIn("A" * screen_processor.MAX_SCREEN_OCR_CHARS, result)
        self.assertIn("OCR text truncated at 12,000 characters", result)
        self.assertNotIn("A" * (screen_processor.MAX_SCREEN_OCR_CHARS + 1), result)


if __name__ == "__main__":
    unittest.main()

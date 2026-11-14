"""Local OCR, redaction of sensitive data and privacy rules."""

from __future__ import annotations

import os
import unittest

import numpy as np

from vision_engine.ocr import ScreenOCR, TextBlock, join_lines
from vision_engine.privacy import REDACTED, PrivacyGuard
from vision_engine.scene import detect_problems

HAS_TESSERACT = os.name == "nt" and os.path.exists(
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


def text_image(text: str = "Count: 1", width: int = 700, height: int = 160) -> np.ndarray:
    import cv2

    image = np.full((height, width, 3), 255, dtype=np.uint8)
    cv2.putText(
        image, text, (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 0, 0), 4
    )
    return image


class ScreenOCRTests(unittest.TestCase):
    """Phase 1 — lire les textes avec OCR."""

    @unittest.skipUnless(HAS_TESSERACT, "Tesseract is not installed")
    def test_ocr_reads_the_text_of_an_image(self):
        ocr = ScreenOCR()
        self.assertTrue(ocr.available(), ocr.error)
        blocks = ocr.read(text_image("Count 42"), origin=(0, 0))
        self.assertTrue(blocks)
        joined = " ".join(block.text for block in blocks).casefold()
        self.assertIn("count", joined)
        self.assertIn("42", joined)

    @unittest.skipUnless(HAS_TESSERACT, "Tesseract is not installed")
    def test_ocr_returns_absolute_screen_coordinates(self):
        ocr = ScreenOCR()
        blocks = ocr.read(text_image("Hello"), origin=(100, 200))
        self.assertTrue(blocks)
        self.assertGreaterEqual(blocks[0].left, 100)
        self.assertGreaterEqual(blocks[0].top, 200)

    @unittest.skipUnless(HAS_TESSERACT, "Tesseract is not installed")
    def test_ocr_region_restricts_the_reading_area(self):
        image = text_image("Hello")
        ocr = ScreenOCR()
        blocks = ocr.read(image, origin=(0, 0), region=(0, 0, 350, 160))
        for block in blocks:
            self.assertLess(block.left, 350)

    def test_ocr_on_a_none_frame_is_safe(self):
        ocr = ScreenOCR()
        self.assertEqual(ocr.read(None), [])
        self.assertEqual(ocr.read_text(None), "")

    def test_join_lines_groups_words_by_position(self):
        blocks = [
            TextBlock(text="Hello", left=0, top=0, width=50, height=20),
            TextBlock(text="world", left=55, top=2, width=50, height=20),
            TextBlock(text="Second", left=0, top=60, width=50, height=20),
        ]
        text = join_lines(blocks)
        self.assertIn("Hello world", text)
        self.assertIn("Second", text)


class PrivacyGuardTests(unittest.TestCase):
    """Phase 5 — exclusion des champs de mots de passe."""

    def setUp(self):
        self.guard = PrivacyGuard()

    def test_password_labels_are_detected(self):
        for label in ("Password", "Pass word", "api_key", "API Key", "CVV", "One-time code"):
            self.assertTrue(self.guard.is_sensitive_label(label), label)

    def test_normal_labels_are_not_sensitive(self):
        for label in ("Save", "Search", "Username", "Cancel"):
            self.assertFalse(self.guard.is_sensitive_label(label), label)

    def test_sensitive_element_names_are_redacted(self):
        elements = [
            {"name": "Password", "kind": "field", "bounds": {"left": 10, "top": 20, "width": 100, "height": 20}},
            {"name": "Save", "kind": "button", "bounds": {"left": 10, "top": 50, "width": 40, "height": 20}},
        ]
        filtered = self.guard.filter_elements(elements)
        self.assertEqual(filtered[0]["name"], REDACTED)
        self.assertTrue(filtered[0]["sensitive"])
        self.assertEqual(filtered[1]["name"], "Save")

    def test_ocr_words_inside_a_password_field_are_dropped(self):
        elements = [
            {"name": "Password", "bounds": {"left": 100, "top": 100, "width": 200, "height": 30}}
        ]
        items = [
            {"text": "hunter2", "bounds": {"left": 110, "top": 105, "width": 60, "height": 20}},
            {"text": "Login", "bounds": {"left": 10, "top": 100, "width": 60, "height": 20}},
        ]
        redacted = self.guard.redact_ocr(items, elements)
        texts = [item["text"] for item in redacted]
        self.assertNotIn("hunter2", texts)
        self.assertIn("Login", texts)

    def test_credential_assignments_are_redacted(self):
        text = "password: hunter2 and api_key=AIzaSyABCDEFG and nothing else"
        redacted = self.guard.redact_text(text)
        self.assertNotIn("hunter2", redacted)
        self.assertNotIn("AIzaSyABCDEFG", redacted)
        self.assertIn(REDACTED, redacted)

    def test_known_token_shapes_are_redacted(self):
        for secret in (
            "sk-abcdefghijklmnop",
            "AKIAIOSFODNN7EXAMPLE",
            "ghp_abcdefghijklmnopqrstuvwxyz0123",
        ):
            redacted = self.guard.redact_text(f"here is {secret} ok")
            self.assertNotIn(secret, redacted, secret)


class EnginePrivacyTests(unittest.TestCase):
    """The engine never leaks what the privacy guard hides."""

    def test_password_field_is_not_reported_in_the_observation(self):
        from tests.vision_fakes import FakeCapture, FakeInspector, FakeOCR, FakeTracker, window
        from vision_engine.config import VisionConfig
        from vision_engine.elements import InteractiveElement
        from vision_engine.engine import VisionEngine

        tracker = FakeTracker([window(hwnd=1, title="Login", foreground=True)])
        inspector = FakeInspector(
            [
                InteractiveElement(
                    name="Password",
                    role="Edit",
                    kind="field",
                    bounds={"left": 100, "top": 100, "width": 200, "height": 30},
                )
            ]
        )
        ocr = FakeOCR(
            [
                TextBlock(text="hunter2", confidence=0.9, left=110, top=105, width=60, height=20),
                TextBlock(text="Welcome", confidence=0.9, left=10, top=10, width=60, height=20),
            ]
        )
        engine = VisionEngine(
            VisionConfig(), capture=FakeCapture(), tracker=tracker, inspector=inspector, ocr=ocr
        )
        engine.set_ocr_permitted(True)
        observation = engine.observe_now(deep=True)
        self.assertNotIn("hunter2", observation.text)
        self.assertNotIn("hunter2", str(observation.elements))
        self.assertIn("Welcome", observation.text)


class ProblemDetectionTests(unittest.TestCase):
    """Phase 1 — nouveaux messages et erreurs."""

    def test_error_windows_are_detected(self):
        problems = detect_problems(["Microsoft Word - Fatal error"], "")
        self.assertTrue(problems)
        self.assertEqual(problems[0]["source"], "window_title")

    def test_error_text_is_detected(self):
        problems = detect_problems([], "Saving failed\nplease retry")
        self.assertTrue(problems)
        self.assertEqual(problems[0]["source"], "screen_text")

    def test_french_errors_are_detected(self):
        problems = detect_problems(["Erreur de configuration"], "")
        self.assertTrue(problems)

    def test_normal_content_is_not_a_problem(self):
        problems = detect_problems(["Untitled - Notepad"], "Document saved successfully")
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()

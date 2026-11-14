"""Visual memory, decision brain and post-action verification."""

from __future__ import annotations

import json
import unittest

from tests.vision_fakes import FakeCapture, FakeOCR, FakeTracker, window
from vision_engine.config import VisionConfig
from vision_engine.decision import (
    DECISION_ABORT,
    DECISION_CONFIRM,
    DECISION_PROCEED,
    DecisionEngine,
)
from vision_engine.engine import VisionEngine
from vision_engine.memory import VisualMemory
from vision_engine.ocr import TextBlock
from vision_engine.scene import ScreenObservation


def make_engine(**overrides) -> VisionEngine:
    config = VisionConfig(**overrides)
    tracker = FakeTracker(
        [window(hwnd=1, title="Editor", process="editor.exe", foreground=True)]
    )
    return VisionEngine(
        config, capture=FakeCapture(), tracker=tracker, ocr=FakeOCR()
    )


class VisualMemoryTests(unittest.TestCase):
    """Phase 3 — mémoire visuelle."""

    def test_memory_keeps_the_previous_observation(self):
        memory = VisualMemory()
        first = ScreenObservation(app_name="a.exe", window_title="One", text="hello")
        second = ScreenObservation(app_name="b.exe", window_title="Two", text="world")
        memory.record(first)
        memory.record(second)
        self.assertEqual(memory.previous()["app_name"], "a.exe")
        self.assertEqual(memory.last().app_name, "b.exe")

    def test_diff_describes_what_changed(self):
        memory = VisualMemory()
        memory.record(ScreenObservation(app_name="a.exe", window_title="One", text="hello"))
        memory.record(
            ScreenObservation(app_name="b.exe", window_title="Two", text="hello world")
        )
        diff = memory.diff(ScreenObservation(app_name="b.exe", window_title="Two", text="hello world"))
        self.assertTrue(diff["app_changed"])
        self.assertTrue(diff["window_changed"])
        self.assertIn("hello world", diff["added_text"])

    def test_failed_actions_are_remembered(self):
        memory = VisualMemory()
        memory.remember_failure("computer_control", {"action": "click", "x": 1}, "button not found")
        self.assertTrue(memory.is_repeated_failure("computer_control", {"action": "click", "x": 1}))
        self.assertFalse(memory.is_repeated_failure("computer_control", {"action": "click", "x": 2}))
        self.assertEqual(memory.failure_count("computer_control", {"action": "click", "x": 1}), 1)

    def test_failure_history_is_persisted_without_pixels(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "memory.json"
            memory = VisualMemory(path=path)
            memory.remember_failure("computer_control", {"action": "click"}, "boom")
            self.assertTrue(path.exists())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["failures"]), 1)
            self.assertNotIn("image", json.dumps(payload))
            self.assertNotIn("frame", json.dumps(payload))

            reloaded = VisualMemory(path=path)
            self.assertTrue(reloaded.load())
            self.assertTrue(reloaded.is_repeated_failure("computer_control", {"action": "click"}))

    def test_mission_context_is_kept(self):
        memory = VisualMemory()
        memory.start_mission("mission-1", goal="send a report")
        memory.record(ScreenObservation(app_name="mail.exe"))
        context = memory.mission_context("mission-1")
        self.assertEqual(context["goal"], "send a report")
        self.assertEqual(len(context["observations"]), 1)

    def test_memory_keeps_no_pixels(self):
        memory = VisualMemory()
        memory.record(ScreenObservation(app_name="a.exe", text="visible text"))
        dumped = json.dumps(memory.history())
        self.assertNotIn("pixels", dumped)
        self.assertNotIn("bgr", dumped)


class DecisionEngineTests(unittest.TestCase):
    """Phase 4 — cerveau décisionnel."""

    def test_safe_action_is_allowed(self):
        engine = make_engine()
        brain = DecisionEngine(engine)
        decision = brain.evaluate(tool="system_status", params={})
        self.assertEqual(decision.action, DECISION_PROCEED)
        self.assertEqual(decision.app_name, "editor.exe")

    def test_sensitive_action_requires_confirmation(self):
        engine = make_engine()
        brain = DecisionEngine(
            engine,
            risk_classifier=lambda tool, params: "HIGH",
            confirmation_checker=lambda tool, params: True,
        )
        decision = brain.evaluate(tool="computer_control", params={"action": "click"})
        self.assertEqual(decision.action, DECISION_CONFIRM)
        self.assertIn("HIGH", decision.risks)

    def test_an_action_that_already_failed_is_refused(self):
        engine = make_engine()
        brain = DecisionEngine(engine)
        params = {"action": "click", "target": "Save"}
        brain.record_failure("computer_control", params, "the button was not found")
        decision = brain.evaluate(tool="computer_control", params=params)
        self.assertEqual(decision.action, DECISION_ABORT)
        self.assertTrue(decision.repeated_failure)

    def test_a_different_action_is_still_allowed(self):
        engine = make_engine()
        brain = DecisionEngine(engine)
        brain.record_failure("computer_control", {"action": "click", "target": "Save"}, "boom")
        decision = brain.evaluate(tool="computer_control", params={"action": "click", "target": "Open"})
        self.assertEqual(decision.action, DECISION_PROCEED)

    def test_observation_failure_blocks_the_action(self):
        class BrokenEngine(VisionEngine):
            def observe_now(self, **kwargs):
                raise RuntimeError("capture lost")

        engine = BrokenEngine(VisionConfig(), capture=FakeCapture())
        brain = DecisionEngine(engine)
        decision = brain.evaluate(tool="computer_control", params={})
        self.assertEqual(decision.action, DECISION_ABORT)
        self.assertIn("observation_failed", decision.risks)


class VerificationTests(unittest.TestCase):
    """Phase 4 — vérifier le résultat d'une action."""

    def test_verification_succeeds_when_the_expected_text_appears(self):
        tracker = FakeTracker(
            [window(hwnd=1, title="Editor", process="editor.exe", foreground=True)]
        )
        ocr = FakeOCR([TextBlock(text="Report saved", confidence=0.9)])
        engine = VisionEngine(VisionConfig(), capture=FakeCapture(), tracker=tracker, ocr=ocr)
        engine.set_ocr_permitted(True)
        brain = DecisionEngine(engine)
        result = brain.verify(expected_text="Report saved")
        self.assertTrue(result.ok, result.reason)
        self.assertTrue(result.matched)

    def test_verification_detects_a_wrong_action(self):
        tracker = FakeTracker(
            [window(hwnd=1, title="Editor", process="editor.exe", foreground=True)]
        )
        ocr = FakeOCR([TextBlock(text="Nothing happened", confidence=0.9)])
        engine = VisionEngine(VisionConfig(), capture=FakeCapture(), tracker=tracker, ocr=ocr)
        engine.set_ocr_permitted(True)
        brain = DecisionEngine(engine)
        result = brain.verify(expected_text="Report saved")
        self.assertFalse(result.ok)
        self.assertIn("not visible", result.reason)

    def test_verification_detects_a_new_error(self):
        tracker = FakeTracker(
            [window(hwnd=1, title="Fatal error: the file could not be saved", foreground=True)]
        )
        engine = VisionEngine(VisionConfig(), capture=FakeCapture(), tracker=tracker)
        brain = DecisionEngine(engine)
        before = ScreenObservation(app_name="editor.exe", window_title="Editor")
        result = brain.verify(before=before)
        self.assertFalse(result.ok)
        self.assertTrue(result.new_problems)

    def test_verification_detects_the_wrong_application(self):
        tracker = FakeTracker(
            [window(hwnd=1, title="Editor", process="editor.exe", foreground=True)]
        )
        engine = VisionEngine(VisionConfig(), capture=FakeCapture(), tracker=tracker)
        brain = DecisionEngine(engine)
        result = brain.verify(expected_app="chrome.exe")
        self.assertFalse(result.ok)
        self.assertIn("not in the foreground", result.reason)


class ToolActionTests(unittest.TestCase):
    """Phase 6 — l'outil vision_observe."""

    def setUp(self):
        from actions import vision_observe

        self.module = vision_observe
        vision_observe.reset_engine()

    def tearDown(self):
        self.module.reset_engine()

    def test_status_action_reports_the_engine(self):
        result = self.module.vision_observe({"action": "status"})
        self.assertIn("NIANG IA CONTINUOUS VISION", result)
        self.assertIn("State", result)

    def test_unknown_action_is_rejected(self):
        result = self.module.vision_observe({"action": "teleport"})
        self.assertIn("Unsupported vision action", result)

    def test_privacy_action_toggles_privacy_mode(self):
        engine = self.module.get_engine()
        result = self.module.vision_observe({"action": "privacy", "enabled": True})
        self.assertIn("Privacy mode ENABLED", result)
        self.assertTrue(engine.privacy.enabled)
        self.module.vision_observe({"action": "privacy", "enabled": False})
        self.assertFalse(engine.privacy.enabled)

    def test_observe_action_returns_a_structured_observation(self):
        result = self.module.vision_observe({"action": "observe"})
        self.assertIn("SCREEN OBSERVATION", result)
        self.assertIn("Application", result)

    def test_history_action_lists_events(self):
        result = self.module.vision_observe({"action": "history", "limit": 5})
        self.assertIn("VISION HISTORY", result)

    def test_decide_action_reports_a_decision(self):
        result = self.module.vision_observe(
            {"action": "decide", "tool": "system_status", "parameters": {}}
        )
        self.assertIn("VISION DECISION", result)
        self.assertIn("Decision", result)

    def test_verify_action_reports_the_verification(self):
        result = self.module.vision_observe({"action": "verify", "expected": "hello"})
        self.assertIn("POST-ACTION VERIFICATION", result)


class SafetyIntegrationTests(unittest.TestCase):
    """Phase 5 — le nouvel outil respecte la politique de sécurité."""

    def test_shallow_observation_is_low_risk(self):
        import safety

        self.assertEqual(safety.classify("vision_observe", {"action": "observe"}), safety.Risk.LOW)
        self.assertFalse(
            safety.needs_confirmation("vision_observe", {"action": "observe"})
        )

    def test_deep_observation_is_auto_permitted_in_this_deployment(self):
        import safety

        self.assertEqual(
            safety.classify("vision_observe", {"action": "observe", "deep": True}),
            safety.Risk.HIGH,
        )
        self.assertFalse(
            safety.needs_confirmation("vision_observe", {"action": "observe", "deep": True})
        )

    def test_starting_the_engine_is_a_medium_risk_action(self):
        import safety

        self.assertEqual(
            safety.classify("vision_observe", {"action": "start"}), safety.Risk.MEDIUM
        )
        self.assertFalse(
            safety.needs_confirmation("vision_observe", {"action": "start"})
        )

    def test_no_privilege_escalation_in_the_vision_tool(self):
        import safety

        for action in ("status", "observe", "start", "stop", "privacy", "history"):
            described = safety.describe("vision_observe", {"action": action}).casefold()
            for forbidden in ("admin", "elevat", "uac", "runas", "sudo"):
                self.assertNotIn(forbidden, described)


if __name__ == "__main__":
    unittest.main()

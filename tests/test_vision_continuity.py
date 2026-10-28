import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class VisionContinuityPromptTests(unittest.TestCase):
    def test_windows_prompt_requires_fresh_observation_and_context_continuity(self):
        prompt = (ROOT / "core" / "prompt.txt").read_text(encoding="utf-8")

        self.assertIn("VISION, DESKTOP CONTROL & TASK CONTINUITY", prompt)
        self.assertIn('computer_control with action="screen_describe"', prompt)
        self.assertIn("point-in-time observation, not continuous vision", prompt)
        self.assertIn("The live screen and current tool results override remembered context", prompt)
        self.assertIn("reuse that page", prompt)
        self.assertIn("Never report a desktop action as complete", prompt)

    def test_tool_declarations_explain_screen_and_browser_scope(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("may not access the user's other browser windows or tabs", source)
        self.assertIn("Observe the current screen before any screen-dependent", source)
        self.assertIn("not continuous monitoring", source)

    def test_fallback_prompt_preserves_vision_limits_and_context(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("keep task ", source)
        self.assertIn("context across turns", source)
        self.assertIn("point-in-time only, not continuous", source)
        self.assertIn("when a window or tab is inaccessible", source)


if __name__ == "__main__":
    unittest.main()

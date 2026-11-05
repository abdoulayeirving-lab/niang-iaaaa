import unittest
from unittest.mock import patch

from agent import error_handler, planner


class AgentErrorPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.step = {
            "step": 2,
            "tool": "browser_control",
            "description": "Enter a confidential password",
            "parameters": {
                "action": "type",
                "text": "very-secret-password",
                "url": "https://example.com/?token=private-token",
            },
            "critical": True,
        }

    def test_error_analysis_sends_only_safe_step_metadata_and_error_summary(self):
        response = unittest.mock.Mock()
        response.text = (
            '{"decision":"replan","reason":"Try another method",'
            '"fix_suggestion":"","max_retries":0,"user_message":""}'
        )
        model = unittest.mock.Mock()
        model.generate_content.return_value = response
        with (
            patch("api_keys.GeminiModel", return_value=model),
        ):
            error_handler.analyze_error(
                self.step,
                "Navigation failed for very-secret-password token=private-token",
            )

        prompt = model.generate_content.call_args.args[0]
        self.assertIn("Tool: browser_control", prompt)
        self.assertIn("Action: type", prompt)
        self.assertNotIn("very-secret-password", prompt)
        self.assertNotIn("private-token", prompt)
        self.assertNotIn("example.com", prompt)
        self.assertNotIn("confidential password", prompt)

    def test_replan_omits_failed_parameters_and_raw_error(self):
        response = unittest.mock.Mock()
        response.text = (
            '{"steps":[{"step":3,"tool":"web_search","description":"Search",'
            '"parameters":{"query":"safe query"},"critical":true}]}'
        )
        model = unittest.mock.Mock()
        model.generate_content.return_value = response
        with (
            patch("api_keys.GeminiModel", return_value=model),
            patch.object(
                planner,
                "_validate_plan",
                side_effect=lambda plan, _goal, registry=None: plan,
            ),
        ):
            planner.replan(
                "Find a general public fact.",
                [],
                self.step,
                "Failed with very-secret-password and private-token",
            )

        prompt = model.generate_content.call_args.args[0]
        self.assertIn("Failed step: [browser_control] type", prompt)
        self.assertNotIn("very-secret-password", prompt)
        self.assertNotIn("private-token", prompt)
        self.assertNotIn("example.com", prompt)
        self.assertNotIn("confidential password", prompt)

    def test_recovery_failure_returns_generic_reason_instead_of_raising_name_error(self):
        model = unittest.mock.Mock()
        model.generate_content.side_effect = RuntimeError("private-token")
        with (
            patch("api_keys.GeminiModel", return_value=model),
        ):
            result = error_handler.analyze_error(self.step, "network failure")

        self.assertEqual(result["reason"], "Recovery analysis failed.")

    def test_fix_generation_omits_raw_step_values_and_errors(self):
        response = unittest.mock.Mock()
        response.text = "print('safe')"
        model = unittest.mock.Mock()
        model.generate_content.return_value = response
        with (
            patch("api_keys.GeminiModel", return_value=model),
        ):
            error_handler.generate_fix(
                self.step,
                "Failed with very-secret-password and private-token",
                "Retry through another browser control action.",
            )

        prompt = model.generate_content.call_args.args[0]
        self.assertIn("Tool: browser_control", prompt)
        self.assertIn("Action: type", prompt)
        self.assertNotIn("very-secret-password", prompt)
        self.assertNotIn("private-token", prompt)
        self.assertNotIn("example.com", prompt)
        self.assertNotIn("confidential password", prompt)

    def test_error_summary_classifies_common_failures_without_echoing_details(self):
        summary = error_handler._safe_error_summary(
            "HTTP status: 503 for https://example.com/?token=private-token"
        )

        self.assertEqual(summary, "The remote server returned HTTP status 503.")
        self.assertNotIn("private-token", summary)


if __name__ == "__main__":
    unittest.main()

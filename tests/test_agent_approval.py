import unittest
from unittest.mock import patch

from agent import executor


class AgentApprovalTests(unittest.TestCase):
    def test_denied_sensitive_action_is_not_dispatched(self):
        approval = unittest.mock.Mock(return_value=False)
        with patch("actions.browser_control.browser_control") as browser:
            result = executor._call_tool(
                "browser_control",
                {"action": "submit_form", "description": "Submit order"},
                None,
                approval_callback=approval,
            )

        self.assertIn("approval was denied", result)
        browser.assert_not_called()
        approval.assert_called_once()

    def test_approved_sensitive_action_is_dispatched_once(self):
        approval = unittest.mock.Mock(return_value=True)
        with patch(
            "actions.browser_control.browser_control",
            return_value="Form submitted.",
        ) as browser:
            result = executor._call_tool(
                "browser_control",
                {"action": "submit_form", "description": "Submit order"},
                None,
                approval_callback=approval,
            )

        self.assertEqual(result, "Form submitted.")
        approval.assert_called_once()
        browser.assert_called_once()

    def test_mission_action_limit_is_enforced(self):
        plan = {
            "steps": [
                {
                    "step": index,
                    "tool": "workspace_list_files",
                    "description": "Read a workspace listing",
                    "parameters": {},
                }
                for index in range(1, executor.AgentExecutor.MAX_ACTIONS_PER_MISSION + 2)
            ]
        }
        with (
            patch("agent.executor.create_plan", return_value=plan),
            patch("agent.executor._call_tool_with_timeout", return_value="OK") as call,
        ):
            result = executor.AgentExecutor().execute("bounded test")

        self.assertIn("20-action mission limit", result)
        self.assertEqual(call.call_count, executor.AgentExecutor.MAX_ACTIONS_PER_MISSION)

    def test_action_audit_log_omits_parameters_and_results(self):
        with patch("logger.log") as log:
            executor.AgentExecutor._report_action(
                None,
                3,
                "browser_control",
                "type private text",
                {"text": "private text"},
                "private text",
                "completed",
            )

        log.assert_called_once_with(
            "AGENT_ACTION number=3 tool=browser_control status=completed",
            level="INFO",
        )


if __name__ == "__main__":
    unittest.main()

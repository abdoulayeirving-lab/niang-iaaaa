import unittest
from unittest.mock import patch

from agent.executor import AgentExecutor


class SensitiveMissionTests(unittest.TestCase):
    def test_sensitive_mission_is_blocked_before_planning_by_default(self):
        with (
            patch("agent.secrets.detect_sensitive_data", return_value={"api_key"}),
            patch("agent.settings.sensitive_mission_policy", return_value="block"),
            patch("agent.executor.create_plan") as create_plan,
        ):
            result = AgentExecutor().execute("Use this key: private-value")

        self.assertIn("blocked before Gemini transmission", result)
        create_plan.assert_not_called()

    def test_sensitive_mission_requires_confirmation_before_planning(self):
        approval = unittest.mock.Mock(return_value=False)
        with (
            patch("agent.secrets.detect_sensitive_data", return_value={"password"}),
            patch("agent.settings.sensitive_mission_policy", return_value="confirm"),
            patch("agent.executor.create_plan") as create_plan,
        ):
            result = AgentExecutor().execute(
                "Use this password: private-value",
                approval_callback=approval,
            )

        self.assertIn("Mission blocked", result)
        approval.assert_called_once()
        self.assertNotIn("private-value", str(approval.call_args))
        create_plan.assert_not_called()

    def test_confirmed_sensitive_mission_can_reach_planner(self):
        approval = unittest.mock.Mock(return_value=True)
        with (
            patch("agent.secrets.detect_sensitive_data", return_value={"token"}),
            patch("agent.settings.sensitive_mission_policy", return_value="confirm"),
            patch("agent.executor.create_plan", return_value={"steps": []}) as create_plan,
        ):
            AgentExecutor().execute(
                "Use this token: private-value",
                approval_callback=approval,
            )

        approval.assert_called_once()
        create_plan.assert_called_once()


if __name__ == "__main__":
    unittest.main()

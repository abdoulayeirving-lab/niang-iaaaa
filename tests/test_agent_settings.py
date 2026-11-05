import os
import unittest
from unittest.mock import patch

from agent import settings


class AgentSettingsTests(unittest.TestCase):
    def test_action_and_mission_limits_use_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(settings.action_timeout_seconds(), 180)
            self.assertEqual(settings.windows_action_timeout_seconds(), 4200)
            self.assertEqual(settings.mission_timeout_seconds(), 1800)
            self.assertEqual(settings.max_actions_per_mission(), 20)
            self.assertEqual(settings.max_attempts_per_step(), 3)
            self.assertEqual(settings.max_replans_per_mission(), 2)

    def test_windows_action_timeout_is_configurable_and_bounded(self):
        with patch.dict(os.environ, {"NIANG_IA_WINDOWS_ACTION_TIMEOUT_S": "900"}):
            self.assertEqual(settings.windows_action_timeout_seconds(), 900)
        with patch.dict(os.environ, {"NIANG_IA_WINDOWS_ACTION_TIMEOUT_S": "7201"}):
            with self.assertRaises(ValueError):
                settings.windows_action_timeout_seconds()

    def test_action_limit_is_configurable_and_bounded(self):
        with patch.dict(os.environ, {"NIANG_IA_AGENT_MAX_ACTIONS": "45"}):
            self.assertEqual(settings.max_actions_per_mission(), 45)
        with patch.dict(os.environ, {"NIANG_IA_AGENT_MAX_ACTIONS": "1001"}):
            with self.assertRaises(ValueError):
                settings.max_actions_per_mission()

    def test_sensitive_data_policy_is_fail_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(settings.sensitive_mission_policy(), "block")
        with patch.dict(
            os.environ,
            {"NIANG_IA_SENSITIVE_MISSION_POLICY": "confirm"},
            clear=True,
        ):
            self.assertEqual(settings.sensitive_mission_policy(), "confirm")
        with patch.dict(
            os.environ,
            {"NIANG_IA_SENSITIVE_MISSION_POLICY": "allow"},
            clear=True,
        ):
            with self.assertRaises(ValueError):
                settings.sensitive_mission_policy()


if __name__ == "__main__":
    unittest.main()

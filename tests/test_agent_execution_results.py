import unittest

from agent.executor import _is_browser_failure, _is_process_tool_failure


class AgentExecutionResultTests(unittest.TestCase):
    def test_browser_failures_are_not_mistaken_for_completed_steps(self):
        failures = (
            "Blocked navigation: Local and internal hostnames are blocked.",
            "Navigation blocked: redirected to a private address.",
            "Timed out waiting for visible element: #submit",
            "Tab not found or closed: tab-4",
            "YouTube search failed in the existing tab.",
            "HTTP status: 429",
            "HTTP status: 503",
        )
        for result in failures:
            with self.subTest(result=result):
                self.assertTrue(_is_browser_failure(result))

    def test_observed_browser_results_are_not_marked_as_failures(self):
        results = (
            "Opened: https://example.com (title: Example)",
            "YouTube search completed in the existing tab.",
            "Selected option 'en' in #language.",
            "HTTP status: 200",
        )
        for result in results:
            with self.subTest(result=result):
                self.assertFalse(_is_browser_failure(result))

    def test_terminal_and_project_failures_are_detected_from_structured_results(self):
        self.assertTrue(_is_process_tool_failure(
            "terminal_control",
            {"action": "run"},
            '{"status":"failed","exit_code":1}',
        ))
        self.assertFalse(_is_process_tool_failure(
            "terminal_control",
            {"action": "run"},
            '{"status":"completed","exit_code":0}',
        ))
        self.assertTrue(_is_process_tool_failure(
            "project_execution",
            {"action": "start"},
            '{"status":"started_unverified","verified":false}',
        ))
        self.assertFalse(_is_process_tool_failure(
            "project_execution",
            {"action": "start"},
            '{"status":"healthy","verified":true}',
        ))


if __name__ == "__main__":
    unittest.main()

import unittest

from agent.executor import _is_browser_failure


class AgentExecutionResultTests(unittest.TestCase):
    def test_browser_failures_are_not_mistaken_for_completed_steps(self):
        failures = (
            "Blocked navigation: Local and internal hostnames are blocked.",
            "Navigation blocked: redirected to a private address.",
            "Timed out waiting for visible element: #submit",
            "Tab not found or closed: tab-4",
            "YouTube search failed in the existing tab.",
        )
        for result in failures:
            with self.subTest(result=result):
                self.assertTrue(_is_browser_failure(result))

    def test_observed_browser_results_are_not_marked_as_failures(self):
        results = (
            "Opened: https://example.com (title: Example)",
            "YouTube search completed in the existing tab.",
            "Selected option 'en' in #language.",
        )
        for result in results:
            with self.subTest(result=result):
                self.assertFalse(_is_browser_failure(result))


if __name__ == "__main__":
    unittest.main()

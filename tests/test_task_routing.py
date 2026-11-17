import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.task_routing import dispatch_project_creation, is_web_frontend_request
from safety import Risk, classify, describe, needs_confirmation
from niang_ia.integrations.opencode.opencode_process import _skill_prompt


class ProjectTaskRoutingTests(unittest.TestCase):
    def test_detects_website_requests_in_french_and_english(self):
        for goal in (
            "Crée-moi une landing page moderne",
            "Créer un site vitrine pour mon entreprise",
            "Build a responsive website",
            "Make a frontend for this product",
        ):
            with self.subTest(goal=goal):
                self.assertTrue(is_web_frontend_request(goal))

    def test_does_not_route_python_project_requests_as_websites(self):
        self.assertFalse(is_web_frontend_request("Create a Python file organizer"))
        self.assertFalse(is_web_frontend_request(""))
        self.assertFalse(is_web_frontend_request(None))

    def test_project_builder_sends_web_tasks_to_opencode(self):
        web_calls = []
        default_calls = []

        result = dispatch_project_creation(
            "Crée une landing page pour mon studio",
            "studio-site",
            web_handler=lambda goal: web_calls.append(goal) or "OpenCode queued",
            default_handler=lambda: default_calls.append(True) or "Python project",
        )

        self.assertEqual(result, "OpenCode queued")
        self.assertEqual(len(web_calls), 1)
        self.assertIn("landing page", web_calls[0])
        self.assertIn("studio-site", web_calls[0])
        self.assertEqual(default_calls, [])

    def test_project_builder_keeps_non_web_tasks_on_the_existing_path(self):
        web_calls = []

        result = dispatch_project_creation(
            "Create a Python file organizer",
            "",
            web_handler=lambda goal: web_calls.append(goal) or "OpenCode queued",
            default_handler=lambda: "Python project",
        )

        self.assertEqual(result, "Python project")
        self.assertEqual(web_calls, [])

    def test_web_requests_sent_to_the_python_builder_require_confirmation(self):
        args = {"description": "Crée une landing page pour mon studio"}

        self.assertEqual(classify("dev_agent", args), Risk.HIGH)
        self.assertTrue(needs_confirmation("dev_agent", args))
        self.assertIn("OpenCode website mission", describe("dev_agent", args))

        self.assertEqual(
            classify("dev_agent", {"description": "Create a Python utility"}),
            Risk.MEDIUM,
        )

    def test_opencode_prompt_requires_real_frontend_files_for_web_requests(self):
        prompt = _skill_prompt("Crée une landing page", ())

        self.assertIn("not a Python script", prompt)
        self.assertIn("index.html", prompt)
        self.assertIn("styles.css", prompt)
        self.assertIn("app.js", prompt)

        python_prompt = _skill_prompt("Create a Python utility", ())
        self.assertNotIn("WEB PROJECT DELIVERABLE", python_prompt)


if __name__ == "__main__":
    unittest.main()

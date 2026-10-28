import unittest

from agent.planner import _validate_plan


class PlanValidationTest(unittest.TestCase):
    def test_normalizes_step_numbers_and_defaults_parameters(self):
        plan = _validate_plan({
            "steps": [
                {"step": 8, "tool": "web_search", "description": " Search "},
                {"tool": "notify", "description": "Notify me"},
            ]
        }, "research")

        self.assertEqual([step["step"] for step in plan["steps"]], [1, 2])
        self.assertEqual(plan["steps"][0]["description"], "Search")
        self.assertEqual(plan["steps"][1]["parameters"], {})
        self.assertEqual(plan["goal"], "research")

    def test_rejects_unknown_tool(self):
        with self.assertRaisesRegex(ValueError, "Unsupported plan tool"):
            _validate_plan({
                "steps": [
                    {"tool": "generated_code", "description": "run code", "parameters": {}}
                ]
            }, "goal")

    def test_rejects_malformed_and_unbounded_plans(self):
        with self.assertRaisesRegex(ValueError, "parameters must be an object"):
            _validate_plan({
                "steps": [
                    {"tool": "web_search", "description": "search", "parameters": []}
                ]
            }, "goal")

        with self.assertRaisesRegex(ValueError, "1 to 5 steps"):
            _validate_plan({
                "steps": [
                    {"tool": "web_search", "description": str(index), "parameters": {}}
                    for index in range(6)
                ]
            }, "goal")


if __name__ == "__main__":
    unittest.main()

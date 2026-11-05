import json
import unittest
from unittest.mock import patch

from agent.planner import (
    PlanGenerationError,
    _planner_system_prompt,
    _validate_plan,
    create_plan,
)
from agent.tool_registry import (
    AGENT_ENABLED_TOOLS,
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    ToolExecutionResult,
    ToolRegistryError,
    build_tool_registry,
)


class ToolRegistryTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.registry = build_tool_registry(
            [{
                "name": "workspace_read_file",
                "description": "Read a workspace file.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"path": {"type": "STRING"}},
                    "required": ["path"],
                },
            }],
            {
                "workspace_read_file": (
                    lambda args: self.calls.append(args) or "contents",
                    10,
                ),
            },
            agent_tools=frozenset({"workspace_read_file"}),
        )

    def test_invokes_registered_handler_with_validated_arguments(self):
        result = self.registry.invoke(
            "workspace_read_file",
            {"path": "src/main.py"},
            ToolExecutionContext(agent_mode=True),
        )

        self.assertEqual(result, "contents")
        self.assertEqual(self.calls, [{"path": "src/main.py"}])

    def test_rejects_missing_required_arguments_before_invoking_handler(self):
        with self.assertRaisesRegex(ToolRegistryError, "missing required"):
            self.registry.invoke(
                "workspace_read_file",
                {},
                ToolExecutionContext(agent_mode=True),
            )

        self.assertEqual(self.calls, [])

    def test_rejects_tools_not_enabled_for_autonomous_missions(self):
        self.registry.register(ToolDefinition(
            name="live_only",
            description="Live-only tool.",
            parameters={"type": "OBJECT", "properties": {}},
            handler=lambda _args, _context: "not available",
            timeout_seconds=1,
            agent_enabled=False,
        ))

        with self.assertRaisesRegex(ToolRegistryError, "not enabled"):
            self.registry.invoke(
                "live_only",
                {},
                ToolExecutionContext(agent_mode=True),
            )

    def test_planner_prompt_uses_registry_catalog(self):
        prompt = _planner_system_prompt(self.registry)

        self.assertIn('"workspace_read_file"', prompt)
        self.assertNotIn("\nopen_app\n", prompt)
        self.assertIn("EXAMPLES:", prompt)

    def test_plan_validation_uses_registry_and_schema(self):
        plan = _validate_plan({
            "steps": [{
                "tool": "workspace_read_file",
                "description": "Read the source file",
                "parameters": {"path": "src/main.py"},
            }],
        }, "inspect project", registry=self.registry)

        self.assertEqual(plan["steps"][0]["tool"], "workspace_read_file")
        with self.assertRaisesRegex(ValueError, "missing required"):
            _validate_plan({
                "steps": [{
                    "tool": "workspace_read_file",
                    "description": "Read a file",
                    "parameters": {},
                }],
            }, "inspect project", registry=self.registry)

    def test_invalid_model_plan_fails_closed_instead_of_using_a_fallback_action(self):
        response = type("Response", (), {"text": "not valid json"})()
        with patch("api_keys.GeminiModel") as model:
            model.return_value.generate_content.return_value = response
            with self.assertRaises(PlanGenerationError):
                create_plan("inspect the project")

        model.return_value.generate_content.assert_called_once()

    def test_agent_tool_catalog_is_the_planners_allowed_tool_source(self):
        from agent.planner import ALLOWED_TOOLS

        self.assertIs(ALLOWED_TOOLS, AGENT_ENABLED_TOOLS)
        self.assertIn("terminal_control", ALLOWED_TOOLS)
        self.assertIn("project_execution", ALLOWED_TOOLS)

    def test_empty_handler_result_is_reported_as_unknown(self):
        registry = build_tool_registry(
            [{
                "name": "workspace_read_file",
                "description": "Read a workspace file.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"path": {"type": "STRING"}},
                    "required": ["path"],
                },
            }],
            {"workspace_read_file": (lambda _args: None, 10)},
            agent_tools=frozenset({"workspace_read_file"}),
        )

        result = registry.invoke(
            "workspace_read_file",
            {"path": "src/main.py"},
            ToolExecutionContext(agent_mode=True),
        )

        self.assertIsInstance(result, ToolExecutionResult)
        self.assertFalse(result.ok)
        self.assertEqual(result.status, "unknown")
        self.assertIn("could not be verified", result)

    def test_approved_workspace_check_result_is_marked_verified(self):
        registry = build_tool_registry(
            [{
                "name": "workspace_run_check",
                "description": "Run an approved workspace check.",
                "parameters": {"type": "OBJECT", "properties": {}},
            }],
            {"workspace_run_check": (lambda _args: "Check python-tests passed.", 10)},
            agent_tools=frozenset({"workspace_run_check"}),
        )

        result = registry.invoke(
            "workspace_run_check",
            {},
            ToolExecutionContext(agent_mode=True),
        )

        self.assertTrue(result.verified)

    def test_terminal_success_and_project_health_are_verified_from_structured_results(self):
        declarations = [
            {
                "name": "terminal_control",
                "description": "Run or manage an approved terminal action.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"action": {"type": "STRING"}},
                    "required": ["action"],
                },
            },
            {
                "name": "project_execution",
                "description": "Inspect and manage an approved project.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"action": {"type": "STRING"}},
                    "required": ["action"],
                },
            },
        ]
        registry = build_tool_registry(
            declarations,
            {
                "terminal_control": (
                    lambda _args: '{"status":"completed","exit_code":0}',
                    10,
                ),
                "project_execution": (
                    lambda _args: '{"status":"healthy","verified":true}',
                    10,
                ),
            },
            agent_tools=frozenset({"terminal_control", "project_execution"}),
        )

        terminal_result = registry.invoke(
            "terminal_control",
            {"action": "run"},
            ToolExecutionContext(agent_mode=True),
        )
        project_result = registry.invoke(
            "project_execution",
            {"action": "start"},
            ToolExecutionContext(agent_mode=True),
        )

        self.assertTrue(terminal_result.verified)
        self.assertTrue(project_result.verified)
        catalog = json.loads(registry.planner_catalog())
        permissions = {item["name"]: item["permission_level"] for item in catalog}
        self.assertEqual(
            permissions["terminal_control"],
            "operation-specific-confirmation",
        )


if __name__ == "__main__":
    unittest.main()

import json
import queue
import re
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.task_queue import Task, TaskQueue, TaskStatus
from niang_ia.integrations.opencode.opencode_engine import (
    MAX_ACTIONS,
    OpenCodeEngine,
    OpenCodeEngineError,
    _permission_paths,
    _validate_workspace_integrations,
)
from niang_ia.integrations.opencode.opencode_health import (
    check_opencode_health,
    find_opencode_binary,
    get_opencode_version,
)
from niang_ia.integrations.opencode.opencode_process import (
    OpenCodeProcess,
    OpenCodeProcessError,
    _is_free_model_quota_error,
    _managed_config,
    _select_session_model,
    _safe_child_environment,
    _workspace_tools_server,
)
from niang_ia.integrations.opencode import opencode_process as opencode_process_module
from niang_ia.integrations.opencode.opencode_tools_server import (
    ALLOWED_CHECKS,
    _validate_arguments,
    execute_workspace_tool,
)
from niang_ia.skills.catalog import DEFAULT_SKILL_ROOT


class _Stream:
    def __init__(self):
        self.lines = queue.Queue()

    def __iter__(self):
        while True:
            line = self.lines.get()
            if line is None:
                return
            yield line

    def push(self, message):
        self.lines.put(json.dumps(message) + "\n")

    def close(self):
        self.lines.put(None)


class _Input:
    def __init__(self, process):
        self.process = process
        self.buffer = ""

    def write(self, text):
        self.buffer += text
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line:
                self.process.on_message(json.loads(line))

    def flush(self):
        pass

    def close(self):
        self.process.stdout.close()
        self.process.stderr.close()


class _FakeACPProcess:
    def __init__(
        self,
        permission_kind="edit",
        tool_name="write",
        raw_input=None,
        load_visual_skill=False,
    ):
        self.stdout = _Stream()
        self.stderr = _Stream()
        self.stdin = _Input(self)
        self.exit_code = None
        self.permission_kind = permission_kind
        self.tool_name = tool_name
        self.raw_input = raw_input
        self.approved = None
        self.model_id = "opencode/nemotron-3.5-super-vl-free"
        self.quota_exhausted = False
        self.load_visual_skill = load_visual_skill

    def on_message(self, message):
        method = message.get("method")
        if method == "initialize":
            self.stdout.push({
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {"protocolVersion": 1, "agentCapabilities": {}},
            })
        elif method == "session/new":
            self.stdout.push({
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "sessionId": "ses_test",
                    "configOptions": [{
                        "id": "mode",
                        "currentValue": "build",
                        "options": [
                            {"value": "plan"},
                            {"value": "build"},
                        ],
                    }, {
                        "id": "model",
                        "currentValue": self.model_id,
                        "options": [
                            {"value": "opencode/nemotron-3.5-super-vl-free"},
                            {"value": "opencode/nemotron-3.5-lightning-free"},
                        ],
                    }],
                },
            })
        elif method == "session/set_config_option":
            self.stdout.push({
                "jsonrpc": "2.0",
                "id": message["id"],
                "result": {
                    "configOptions": [
                        {
                            "id": "mode",
                            "currentValue": (
                                message["params"]["value"]
                                if message["params"]["configId"] == "mode"
                                else "build"
                            ),
                            "options": [{"value": "plan"}, {"value": "build"}],
                        },
                        {
                            "id": "model",
                            "currentValue": (
                                message["params"]["value"]
                                if message["params"]["configId"] == "model"
                                else self.model_id
                            ),
                            "options": [
                                {"value": "opencode/nemotron-3.5-super-vl-free"},
                                {"value": "opencode/nemotron-3.5-lightning-free"},
                            ],
                        },
                    ],
                },
            })
        elif method == "session/prompt":
            if self.quota_exhausted:
                self.stdout.push({
                    "jsonrpc": "2.0",
                    "id": message["id"],
                    "error": {"code": 429, "message": "Free model rate limit exceeded."},
                })
                self.sent.append(message)
                return
            if self.load_visual_skill:
                self.stdout.push({
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "ses_test",
                        "update": {
                            "sessionUpdate": "tool_call",
                            "toolCallId": "skill_1",
                            "name": "skill",
                            "title": "Load visual asset intelligence",
                            "rawInput": {"id": "visual-asset-intelligence"},
                        },
                    },
                })
                self.stdout.push({
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": "ses_test",
                        "update": {
                            "sessionUpdate": "tool_call_update",
                            "toolCallId": "skill_1",
                            "status": "completed",
                            "content": [{
                                "type": "content",
                                "content": {
                                    "type": "text",
                                    "text": '<skill_content name="visual-asset-intelligence">verified</skill_content>',
                                },
                            }],
                        },
                    },
                })
            self.stdout.push({
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "ses_test",
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
                        "content": {"type": "text", "text": "Updated source."},
                    },
                },
            })
            self.stdout.push({
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "ses_test",
                    "update": {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "tool_1",
                        "name": self.tool_name,
                        "title": "Write source file",
                        "kind": self.permission_kind,
                        "locations": [{"path": str(self.workspace_root / "new.py")}],
                    },
                },
            })
            self.stdout.push({
                "jsonrpc": "2.0",
                "id": 99,
                "method": "session/request_permission",
                "params": {
                    "sessionId": "ses_test",
                    "toolCall": {
                        "toolCallId": "tool_1",
                        "name": self.tool_name,
                        "title": "Write source file",
                        "kind": self.permission_kind,
                        "locations": [{"path": str(self.workspace_root / "new.py")}],
                        **({"rawInput": self.raw_input} if self.raw_input is not None else {}),
                    },
                    "options": [
                        {"optionId": "once", "kind": "allow_once"},
                        {"optionId": "reject", "kind": "reject_once"},
                    ],
                },
            })
        elif message.get("id") == 99:
            self.approved = message["result"]["outcome"]["optionId"] == "once"
            self.stdout.push({
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "sessionId": "ses_test",
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "tool_1",
                        "status": "completed" if self.approved else "failed",
                    },
                },
            })
            self.stdout.push({
                "jsonrpc": "2.0",
                "id": next(
                    item["id"] for item in self.sent
                    if item.get("method") == "session/prompt"
                ),
                "result": {"stopReason": "end_turn"},
            })
        self.sent.append(message)

    def poll(self):
        return self.exit_code

    def wait(self, timeout=None):
        self.exit_code = 0
        return self.exit_code

    def terminate(self):
        self.exit_code = 1
        self.stdout.close()

    def kill(self):
        self.exit_code = -9
        self.stdout.close()

    sent = []


class OpenCodeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name).resolve()

    def tearDown(self):
        self.directory.cleanup()

    def _process(self, fake):
        fake.sent = []
        fake.workspace_root = self.root
        executable = self.root / "opencode.exe"
        executable.touch()
        def popen(*_args, **kwargs):
            managed = json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])
            fake.model_id = managed["model"]
            return fake

        return OpenCodeProcess(
            binary=executable,
            free_model_ids=[
                "opencode/nemotron-3.5-super-vl-free",
                "opencode/nemotron-3.5-lightning-free",
            ],
            popen=popen,
        )

    def test_acp_handshake_requests_one_time_approval_and_returns_result(self):
        fake = _FakeACPProcess()
        approvals = []
        engine = OpenCodeEngine(self._process(fake))

        result = engine.execute(
            "Create new.py",
            self.root,
            "assisted",
            approval_callback=lambda tool, args, description, cancel: approvals.append(
                (tool, args, description)
            ) or True,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["text"], "Updated source.")
        self.assertEqual(result["actions"], 1)
        self.assertTrue(fake.approved)
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0][1]["paths"], ["new.py"])
        self.assertEqual(
            next(item for item in fake.sent if item.get("method") == "session/new")["params"]["cwd"],
            str(self.root),
        )

    def test_free_quota_uses_the_next_verified_free_model(self):
        first = _FakeACPProcess()
        first.quota_exhausted = True
        second = _FakeACPProcess()
        fakes = iter((first, second))
        progress = []
        executable = self.root / "opencode.exe"
        executable.touch()

        def popen(*_args, **kwargs):
            fake = next(fakes)
            fake.sent = []
            fake.workspace_root = self.root
            fake.launch_kwargs = kwargs
            fake.model_id = json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])["model"]
            return fake

        process = OpenCodeProcess(
            binary=executable,
            free_model_ids=[
                "opencode/nemotron-3.5-super-vl-free",
                "opencode/nemotron-3.5-lightning-free",
            ],
            popen=popen,
        )
        result = OpenCodeEngine(process).execute(
            "Create new.py",
            self.root,
            "assisted",
            approval_callback=lambda *_: True,
            on_progress=progress.append,
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            [
                json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])["model"]
                for kwargs in (first.launch_kwargs, second.launch_kwargs)
            ],
            [
                "opencode/nemotron-3.5-super-vl-free",
                "opencode/nemotron-3.5-lightning-free",
            ],
        )
        self.assertIn(
            "Continue from the current workspace state",
            next(item for item in second.sent if item.get("method") == "session/prompt")["params"]["prompt"][0]["text"],
        )
        self.assertTrue(all(
            json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])["model"].startswith("opencode/")
            for kwargs in (first.launch_kwargs, second.launch_kwargs)
        ))
        self.assertEqual(
            [
                event["current_step"]
                for event in progress
                if event["current_step"].startswith("Modèle gratuit OpenCode")
            ],
            [
                "Modèle gratuit OpenCode : opencode/nemotron-3.5-super-vl-free (1/2)",
                "Modèle gratuit OpenCode : opencode/nemotron-3.5-lightning-free (2/2)",
            ],
        )

    def test_health_requires_an_available_free_model(self):
        executable = self.root / "opencode.exe"
        executable.touch()
        with patch(
            "niang_ia.integrations.opencode.opencode_health.find_opencode_binary",
            return_value=executable,
        ), patch(
            "niang_ia.integrations.opencode.opencode_health.get_opencode_version",
            return_value="1.0.0",
        ), patch.object(
            OpenCodeProcess,
            "_available_free_models",
            return_value=["opencode/nemotron-3.5-super-vl-free"],
        ):
            ready = check_opencode_health()
        self.assertTrue(ready["ready"])
        self.assertTrue(ready["free_models_available"])
        self.assertEqual(
            ready["free_models"],
            ["opencode/nemotron-3.5-super-vl-free"],
        )

        with patch(
            "niang_ia.integrations.opencode.opencode_health.find_opencode_binary",
            return_value=executable,
        ), patch(
            "niang_ia.integrations.opencode.opencode_health.get_opencode_version",
            return_value="1.0.0",
        ), patch.object(
            OpenCodeProcess,
            "_available_free_models",
            return_value=[],
        ):
            unavailable = check_opencode_health()
        self.assertFalse(unavailable["ready"])
        self.assertFalse(unavailable["free_models_available"])

    def test_health_requires_the_workspace_mcp_dependency(self):
        executable = self.root / "opencode.exe"
        executable.touch()
        with patch(
            "niang_ia.integrations.opencode.opencode_health.find_opencode_binary",
            return_value=executable,
        ), patch(
            "niang_ia.integrations.opencode.opencode_health.get_opencode_version",
            return_value="1.0.0",
        ), patch(
            "niang_ia.integrations.opencode.opencode_health.workspace_mcp_status",
            return_value=(False, "MCP package is missing."),
        ), patch.object(
            OpenCodeProcess,
            "_available_free_models",
            return_value=["opencode/nemotron-3.5-super-vl-free"],
        ):
            result = check_opencode_health()

        self.assertFalse(result["ready"])
        self.assertFalse(result["workspace_tools_available"])
        self.assertEqual(result["workspace_tools_error"], "MCP package is missing.")

    def test_engine_stops_before_starting_when_workspace_mcp_is_missing(self):
        class Process:
            called = False

            def run(self, *_args, **_kwargs):
                self.called = True
                raise AssertionError("OpenCode must not start without the MCP workspace server.")

        process = Process()
        with patch(
            "niang_ia.integrations.opencode.opencode_engine.workspace_mcp_status",
            return_value=(False, "MCP package is missing."),
        ):
            with self.assertRaisesRegex(OpenCodeEngineError, "MCP package is missing"):
                OpenCodeEngine(process).execute("Create a landing page", self.root, "assisted")
        self.assertFalse(process.called)

    def test_exhausted_opencode_quotas_stop_without_a_paid_fallback(self):
        executable = self.root / "opencode.exe"
        executable.touch()
        models = [
            "opencode/nemotron-3.5-super-vl-free",
            "opencode/nemotron-3.5-lightning-free",
        ]
        attempted = []

        def popen(*_args, **kwargs):
            fake = _FakeACPProcess()
            fake.quota_exhausted = True
            fake.sent = []
            fake.workspace_root = self.root
            fake.model_id = json.loads(kwargs["env"]["OPENCODE_CONFIG_CONTENT"])["model"]
            attempted.append(fake.model_id)
            return fake

        process = OpenCodeProcess(
            binary=executable,
            free_model_ids=models,
            popen=popen,
        )
        with self.assertRaisesRegex(OpenCodeEngineError, "No paid model was used"):
            OpenCodeEngine(process).execute(
                "Create new.py",
                self.root,
                "assisted",
                approval_callback=lambda *_: True,
            )
        self.assertEqual(attempted, models)

    def test_quota_classification_does_not_confuse_authentication_errors(self):
        self.assertTrue(_is_free_model_quota_error({
            "code": 429,
            "message": "Free model rate limit exceeded.",
        }))
        self.assertTrue(_is_free_model_quota_error({
            "code": -32000,
            "data": {"statusCode": 429},
        }))
        self.assertFalse(_is_free_model_quota_error({
            "code": 401,
            "message": "Authentication failed.",
        }))
        self.assertFalse(_is_free_model_quota_error({
            "code": -32000,
            "message": "Model is unavailable.",
        }))

    def test_model_selection_fails_closed_when_acp_hides_model_options(self):
        with self.assertRaisesRegex(OpenCodeProcessError, "did not expose model selection"):
            _select_session_model(
                lambda *_args, **_kwargs: {},
                {"sessionId": "ses_test", "configOptions": []},
                "ses_test",
                "opencode/nemotron-3.5-super-vl-free",
            )

    def test_free_model_catalog_requires_zero_cost_and_tool_support(self):
        catalog = {
            "opencode": {
                "models": {
                    "free": {
                        "cost": {"input": 0, "output": 0},
                        "tool_call": True,
                    },
                    "paid": {
                        "cost": {"input": 0, "output": 0.1},
                        "tool_call": True,
                    },
                    "cache-charged": {
                        "cost": {"input": 0, "output": 0, "cache_read": 0.01},
                        "tool_call": True,
                    },
                    "no-tools": {
                        "cost": {"input": 0, "output": 0},
                        "tool_call": False,
                    },
                },
            },
            "opencode-go": {
                "models": {
                    "go-free": {
                        "cost": {"input": 0, "output": 0},
                        "tool_call": True,
                    },
                },
            },
        }

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return json.dumps(catalog).encode("utf-8")

        with patch.object(opencode_process_module, "_FREE_MODEL_CACHE", None), patch(
            "niang_ia.integrations.opencode.opencode_process.urllib.request.urlopen",
            return_value=Response(),
        ):
            model_ids = opencode_process_module._verified_free_model_ids()

        self.assertEqual(
            model_ids,
            frozenset({"opencode/free", "opencode-go/go-free"}),
        )

    def test_available_models_are_intersected_with_verified_free_catalog(self):
        executable = self.root / "opencode.exe"
        executable.touch()
        process = OpenCodeProcess(binary=executable)
        with patch.object(
            opencode_process_module,
            "_verified_free_model_ids",
            return_value=frozenset({"opencode/free", "opencode/paid"}),
        ), patch(
            "niang_ia.integrations.opencode.opencode_process.subprocess.run",
            return_value=type(
                "Completed",
                (),
                {
                    "returncode": 0,
                    "stdout": "opencode/paid\nopencode/free\nopenrouter/external\n",
                },
            )(),
        ):
            model_ids = process._available_free_models(self.root, "assisted", ())

        self.assertEqual(model_ids, ["opencode/paid", "opencode/free"])

    def test_shell_or_non_edit_permission_is_denied(self):
        fake = _FakeACPProcess(permission_kind="delete")
        with self.assertRaisesRegex(OpenCodeEngineError, "without reporting a workspace action"):
            OpenCodeEngine(self._process(fake)).execute(
                "Delete a file", self.root, "assisted",
                approval_callback=lambda *_: self.fail("Delete permission must never be granted"),
            )
        self.assertFalse(fake.approved)

    def test_plan_mode_cannot_leave_read_only_agent(self):
        class PlanModeProcess:
            def run(
                self, _goal, _root, _mode, *, selected_skill_ids=(),
                on_permission, on_event, cancel_flag,
            ):
                on_event({
                    "update": {
                        "sessionUpdate": "current_mode_update",
                        "currentModeId": "build",
                    },
                })
                return {"session_id": "ses_test", "stop_reason": "end_turn"}

        with self.assertRaisesRegex(OpenCodeEngineError, "read-only plan mode"):
            OpenCodeEngine(PlanModeProcess()).execute("Plan", self.root, "plan")

    def test_result_records_only_selected_skills_reported_as_loaded(self):
        class SkillEventProcess:
            def run(self, _goal, _root, _mode, *, selected_skill_ids=(), on_permission, on_event, cancel_flag):
                on_event({
                    "update": {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "skill_1",
                        "name": "skill",
                        "rawInput": {},
                    },
                })
                on_event({
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "skill_1",
                        "status": "completed",
                        "content": [{
                            "type": "content",
                            "content": {
                                "type": "text",
                                "text": (
                                    '<skill_content name="testing-debugging-mastery">'
                                    "Skill instructions loaded."
                                    "</skill_content>"
                                ),
                            },
                        }],
                    },
                })
                on_event({
                    "update": {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "skill_2",
                        "name": "skill",
                        "rawInput": {},
                    },
                })
                on_event({
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "skill_2",
                        "status": "completed",
                        "content": [{
                            "type": "content",
                            "content": {
                                "type": "text",
                                "text": '<skill_content name="not-selected">Other instructions.</skill_content>',
                            },
                        }],
                    },
                })
                on_event({
                    "update": {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "read_1",
                        "name": "read",
                        "kind": "read",
                    },
                })
                on_event({
                    "update": {
                        "sessionUpdate": "tool_call_update",
                        "toolCallId": "read_1",
                        "status": "completed",
                    },
                })
                return {"session_id": "ses_test", "stop_reason": "end_turn"}

        result = OpenCodeEngine(SkillEventProcess()).execute(
            "Inspect project",
            self.root,
            "plan",
        )
        self.assertIn("testing-debugging-mastery", result["skills"]["selected"])
        self.assertEqual(result["skills"]["loaded"], ["testing-debugging-mastery"])

    def test_acp_switches_to_plan_with_config_options(self):
        fake = _FakeACPProcess()
        self._process(fake).run(
            "Plan the task",
            self.root,
            "plan",
            on_permission=lambda *_: False,
        )
        switch = next(
            item for item in fake.sent
            if item.get("method") == "session/set_config_option"
        )
        self.assertEqual(switch["params"]["configId"], "mode")
        self.assertEqual(switch["params"]["value"], "plan")

    def test_acp_registers_the_bounded_workspace_server(self):
        fake = _FakeACPProcess()
        self._process(fake).run(
            "Create a site",
            self.root,
            "assisted",
            selected_skill_ids=("premium-web-design",),
            on_permission=lambda *_: False,
        )
        prompt = next(item for item in fake.sent if item.get("method") == "session/prompt")
        self.assertIn("premium-web-design", prompt["params"]["prompt"][0]["text"])
        servers = next(
            item for item in fake.sent if item.get("method") == "session/new"
        )["params"]["mcpServers"]
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]["name"], "niang_workspace")
        self.assertEqual(
            Path(servers[0]["args"][1]).name,
            "opencode_tools_server.py",
        )
        self.assertEqual(servers[0]["args"][-1], str(self.root))

    def test_visual_asset_skill_is_loaded_before_its_approved_workspace_tool_is_available(self):
        fake = _FakeACPProcess(
            permission_kind="other",
            tool_name="niang_workspace_visual_asset_inspect",
            raw_input={"limit": 1},
            load_visual_skill=True,
        )
        approvals = []
        result = OpenCodeEngine(self._process(fake)).execute(
            "Create a landing page with real images.",
            self.root,
            "assisted",
            approval_callback=lambda tool, arguments, description, cancel: approvals.append(
                (tool, arguments, description)
            ) or True,
        )
        self.assertIn("visual-asset-intelligence", result["skills"]["loaded"])
        self.assertEqual(approvals[0][0], "opencode_visual_asset_inspect")
        server = next(
            item for item in fake.sent if item.get("method") == "session/new"
        )["params"]["mcpServers"][0]
        self.assertIn("--visual-assets", server["args"])

    def test_visual_asset_server_only_receives_authorized_provider_environment(self):
        keys = {
            "NIANG_IA_PIXABAY_API_KEY": "pixabay-key",
            "NIANG_IA_UNSPLASH_ACCESS_KEY": "unsplash-key",
            "NIANG_IA_PEXELS_API_KEY": "pexels-key",
            "OPENAI_API_KEY": "unrelated-key",
        }
        with patch.dict("os.environ", keys, clear=True):
            enabled = _workspace_tools_server(
                self.root, ("visual-asset-intelligence",)
            )
            disabled = _workspace_tools_server(self.root, ())
        self.assertEqual(
            enabled["env"],
            {
                "NIANG_IA_PIXABAY_API_KEY": "pixabay-key",
                "NIANG_IA_UNSPLASH_ACCESS_KEY": "unsplash-key",
                "NIANG_IA_PEXELS_API_KEY": "pexels-key",
            },
        )
        self.assertEqual(disabled["env"], {})
        self.assertNotIn("--visual-assets", disabled["args"])

    def test_visual_asset_tool_input_is_bounded_and_not_available_when_unselected(self):
        with self.assertRaisesRegex(ValueError, "sensitive information"):
            _validate_arguments(
                "visual_asset_search",
                {"query": "token is sk-123456789012345678901234"},
            )
        with self.assertRaisesRegex(ValueError, "not enabled"):
            execute_workspace_tool(
                "visual_asset_inspect",
                {},
                self.root,
            )
        self.assertEqual(
            _validate_arguments(
                "visual_asset_search",
                {"query": "landscape car", "orientation": "landscape"},
            )["orientation"],
            "landscape",
        )

    def test_bounded_workspace_tool_requires_approval_with_exact_arguments(self):
        fake = _FakeACPProcess(
            permission_kind="other",
            tool_name="niang_workspace_run_check",
            raw_input={"check": "npm-build", "timeout_seconds": 90},
        )
        approvals = []
        engine = OpenCodeEngine(self._process(fake))
        result = engine.execute(
            "Build the project",
            self.root,
            "assisted",
            approval_callback=lambda tool, arguments, description, cancel: approvals.append(
                (tool, arguments, description)
            ) or True,
        )
        self.assertEqual(result["status"], "completed")
        self.assertTrue(fake.approved)
        self.assertEqual(approvals[0][0], "opencode_run_check")
        self.assertEqual(
            approvals[0][1],
            {"check": "npm-build", "timeout_seconds": 90},
        )
        self.assertIn("npm-build", approvals[0][2])

    def test_controlled_mode_never_implicitly_approves_workspace_tools(self):
        for mode in ("autonomous_controlled", "plan"):
            fake = _FakeACPProcess(
                permission_kind="other",
                tool_name="niang_workspace_run_check",
                raw_input={"check": "npm-test"},
            )
            approvals = []
            with self.assertRaisesRegex(
                OpenCodeEngineError,
                "without reporting a workspace action",
            ):
                OpenCodeEngine(self._process(fake)).execute(
                    "Test the project",
                    self.root,
                    mode,
                    approval_callback=lambda *args: approvals.append(args) or False,
                )
            self.assertFalse(fake.approved)
            self.assertEqual(len(approvals), 0 if mode == "plan" else 1)

    def test_bounded_workspace_tool_rejects_unknown_checks_and_shells(self):
        with self.assertRaisesRegex(ValueError, "not available"):
            _validate_arguments("run_check", {"check": "custom-shell"})
        self.assertEqual(
            _validate_arguments("run_check", {"check": "npm-test"})["check"],
            "npm-test",
        )

        fake = _FakeACPProcess(
            permission_kind="other",
            tool_name="niang_workspace_run_check",
            raw_input={"check": "custom-shell"},
        )
        with self.assertRaisesRegex(OpenCodeEngineError, "without reporting a workspace action"):
            OpenCodeEngine(self._process(fake)).execute(
                "Run custom command",
                self.root,
                "assisted",
                approval_callback=lambda *_: self.fail("Invalid tool input must be rejected"),
            )
        self.assertFalse(fake.approved)

    def test_workspace_tool_allows_only_node_and_python_installation(self):
        with self.assertRaisesRegex(ValueError, "Only Node.js and Python"):
            _validate_arguments(
                "install_dependency",
                {"ecosystem": "go", "package": "example"},
            )
        with patch(
            "niang_ia.integrations.opencode.opencode_tools_server.workspace_tools.run_check",
            return_value="Check npm-test passed.",
        ) as run_check:
            result = execute_workspace_tool(
                "run_check",
                {"check": "npm-test"},
                self.root,
            )
        self.assertIn("passed", result)
        run_check.assert_called_once_with(
            "npm-test",
            60,
            workspace_root=self.root,
            cancel_flag=None,
        )

    def test_static_preview_is_loopback_only_and_rejects_sensitive_files(self):
        (self.root / "index.html").write_text(
            "<html><body>Local preview</body></html>",
            encoding="utf-8",
        )
        (self.root / ".env").write_text("SECRET=value", encoding="utf-8")
        (self.root / "settings.json").write_text(
            '{"token":"private"}',
            encoding="utf-8",
        )

        try:
            result = execute_workspace_tool("start_preview", {}, self.root)
            match = re.search(r"http://127\.0\.0\.1:(\d+)/", result)
            self.assertIsNotNone(match)
            url = match.group(0)
            with urllib.request.urlopen(url, timeout=5) as response:
                body = response.read().decode("utf-8")
                self.assertIn("Local preview", body)
                self.assertIn("Content-Security-Policy", response.headers)
            for path in (".env", "settings.json", "%2e%2e/.env"):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(url + path, timeout=5)
                self.assertEqual(error.exception.code, 404)
        finally:
            execute_workspace_tool("stop_preview", {}, self.root)

    def test_action_count_is_bounded(self):
        class TooManyActionsProcess:
            def run(
                self, _goal, _root, _mode, *, selected_skill_ids=(),
                on_permission, on_event, cancel_flag,
            ):
                for index in range(MAX_ACTIONS + 1):
                    on_event({
                        "update": {
                            "sessionUpdate": "tool_call",
                            "toolCallId": str(index),
                            "name": "read",
                            "title": "Read file",
                            "kind": "read",
                        },
                    })
                return {"session_id": "ses_test", "stop_reason": "end_turn"}

        with self.assertRaisesRegex(OpenCodeEngineError, "action limit"):
            OpenCodeEngine(TooManyActionsProcess()).execute("Inspect", self.root, "plan")

    def test_permission_paths_reject_outside_and_credential_files(self):
        outside = self.root.parent / "outside.txt"
        self.assertEqual(
            _permission_paths(
                {"locations": [{"path": str(outside)}]},
                self.root,
            ),
            [],
        )
        self.assertEqual(
            _permission_paths(
                {"locations": [{"path": str(self.root / ".env")} ]},
                self.root,
            ),
            [],
        )

    def test_workspace_local_plugins_and_mcp_config_are_rejected(self):
        plugin_directory = self.root / ".opencode" / "plugins"
        plugin_directory.mkdir(parents=True)
        (plugin_directory / "custom.js").write_text("export default {}", encoding="utf-8")
        with self.assertRaisesRegex(OpenCodeEngineError, "contains OpenCode plugins"):
            _validate_workspace_integrations(self.root)

        (plugin_directory / "custom.js").unlink()
        plugin_directory.rmdir()
        (plugin_directory.parent / "opencode.jsonc").write_text(
            '{"mcp": {"servers": {}}}', encoding="utf-8"
        )
        with self.assertRaisesRegex(OpenCodeEngineError, "plugins or MCP servers"):
            _validate_workspace_integrations(self.root)

    def test_managed_permissions_block_shell_and_outside_reads(self):
        config = _managed_config(
            "assisted",
            ("desktop-engineering", "testing-quality"),
        )
        for agent_name, agent in config["agents"].items():
            rules = agent["permissions"]
            self.assertEqual(
                next(rule["effect"] for rule in reversed(rules) if rule["action"] == "shell"),
                "deny",
            )
            self.assertEqual(
                next(rule["effect"] for rule in reversed(rules) if rule["action"] == "external_directory"),
                "deny",
            )
            self.assertEqual(
                next(rule["effect"] for rule in reversed(rules) if rule["action"] == "edit"),
                "deny" if agent_name == "plan" else "ask",
            )
            self.assertEqual(
                next(
                    rule["effect"] for rule in reversed(rules)
                    if rule["action"] == "niang_workspace_run_check"
                ),
                "deny" if agent_name == "plan" else "ask",
            )
            self.assertEqual(
                next(
                    rule["effect"] for rule in reversed(rules)
                    if rule["action"] == "read" and rule["resource"] == "*.env"
                ),
                "deny",
            )

        with patch.dict("os.environ", {"OPENAI_API_KEY": "not-forwarded"}):
            env = _safe_child_environment(
                "assisted",
                ("desktop-engineering", "testing-quality"),
            )
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertEqual(
            json.loads(env["OPENCODE_CONFIG_CONTENT"]),
            _managed_config("assisted", ("desktop-engineering", "testing-quality")),
        )
        for agent in config["agents"].values():
            rules = agent["permissions"]
            self.assertEqual(
                next(
                    rule["effect"] for rule in reversed(rules)
                    if rule["action"] == "skill" and rule["resource"] == "desktop-engineering"
                ),
                "allow",
            )
            self.assertEqual(
                next(
                    rule["effect"] for rule in reversed(rules)
                    if rule["action"] == "skill" and rule["resource"] == "testing-quality"
                ),
                "allow",
            )
            self.assertEqual(
                next(
                    rule["effect"] for rule in reversed(rules)
                    if rule["action"] == "skill" and rule["resource"] == "*"
                ),
                "deny",
            )
        self.assertEqual(config["skills"], [str(DEFAULT_SKILL_ROOT.resolve())])
        self.assertEqual(ALLOWED_CHECKS, {
            "python-tests", "python-unittest", "python-compile",
            "npm-test", "npm-build", "npm-lint", "tsc-check",
            "git-status", "git-diff-check",
        })

    def test_opencode_executable_detection_and_version_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "node_modules" / "@opencode" / "cli" / "bin" / "opencode.exe"
            executable.parent.mkdir(parents=True)
            executable.touch()
            shim = root / "opencode.cmd"
            shim.touch()
            with patch(
                "niang_ia.integrations.opencode.opencode_health.shutil.which",
                side_effect=lambda name: str(shim) if name == "opencode.cmd" else None,
            ):
                self.assertEqual(find_opencode_binary(), executable.resolve())
            with patch(
                "niang_ia.integrations.opencode.opencode_health.subprocess.run",
                return_value=type("Completed", (), {
                    "returncode": 0,
                    "stdout": "opencode v2.2.6\n",
                })(),
            ) as run:
                self.assertEqual(get_opencode_version(executable), "opencode v2.2.6")
                self.assertEqual(run.call_args.args[0], [str(executable), "--version"])

    def test_task_queue_dispatches_opencode_mission(self):
        task = Task(
            priority=2,
            created_at=1.0,
            task_id="opencode-task",
            goal="Inspect project",
            status=TaskStatus.RUNNING,
            executor_kind="opencode",
            opencode_workspace_root=str(self.root),
            opencode_mode="plan",
        )
        queue_instance = TaskQueue(persist=False)
        queue_instance._tasks[task.task_id] = task
        queue_instance._active_count = 1
        with patch(
            "niang_ia.integrations.cline.cline_vscode.open_vscode_workspace"
        ), patch(
            "niang_ia.integrations.opencode.opencode_engine.OpenCodeEngine"
        ) as engine_type:
            engine_type.return_value.execute.return_value = {
                "status": "completed",
                "text": "Plan generated.",
                "actions": 1,
                "skills": {
                    "selected": ["testing-debugging-mastery"],
                    "loaded": ["testing-debugging-mastery"],
                },
                "quality_gate": {
                    "status": "NOT_TESTED",
                    "checks": [{
                        "id": "tests",
                        "name": "Automated tests",
                        "status": "NOT_TESTED",
                        "evidence": [],
                    }],
                },
            }
            queue_instance._run_task(task)

        engine_type.return_value.execute.assert_called_once()
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIn("Plan generated.", task.result)
        self.assertIn("Skills loaded: testing-debugging-mastery", task.result)
        self.assertIn("QUALITY GATE: NON TESTÉ", task.result)


if __name__ == "__main__":
    unittest.main()

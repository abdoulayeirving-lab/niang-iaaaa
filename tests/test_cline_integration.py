import json
import os
import queue
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.task_queue import TaskQueue
from agent.workspace_tools import WorkspaceError, open_folder, read_file, write_file
from agent.windows_desktop import WindowsDesktopError
from niang_ia.integrations.cline.cline_config import (
    CLINE_FREE_MODELS,
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_PROVIDER,
    MAX_ACTIONS,
    MAX_ACTION_SECONDS,
    ClineConfig,
)
from niang_ia.integrations.cline.cline_engine import ClineEngine, ClineEngineError
from niang_ia.integrations.cline.cline_health import check_cline_health, get_cline_version
from niang_ia.integrations.cline.cline_manager import ClineExecutionError, ClineManager
from niang_ia.integrations.cline.cline_models import ClineMode, ClineResult
from niang_ia.integrations.cline.cline_process import (
    ClineCancelled,
    ClineFreeModelLimitError,
    ClineProcess,
    ClineProcessError,
)
from niang_ia.integrations.cline.cline_protocol import (
    ClineProtocolError,
    decode_message,
    encode_message,
)
from niang_ia.integrations.cline.cline_vscode import open_vscode_workspace
from niang_ia.integrations.cline.cline_process import _safe_child_environment
from niang_ia.integrations.cline.cline_policy import (
    approval_required,
    validate_tool_input,
)


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
        pass


class _FakeProcess:
    def __init__(self, scenario):
        self.scenario = scenario
        self.stdout = _Stream()
        self.stderr = _Stream()
        self.stderr.close()
        self.stdin = _Input(self)
        self.exit_code = None
        self.messages = []

    def on_message(self, message):
        self.messages.append(message)
        message_type = message.get("type")
        if message_type == "start":
            if self.scenario == "result":
                self.stdout.push({"type": "agent_event", "eventType": "run-started"})
                self.stdout.push({"type": "run_result", "status": "completed", "outputText": "Plan ready."})
                self.stdout.close()
                self.exit_code = 0
            elif self.scenario == "quota":
                self.stdout.push({
                    "type": "agent_event",
                    "eventType": "run-failed",
                    "message": "Free model usage limit reached.",
                    "quotaExhausted": True,
                })
                self.stdout.push({
                    "type": "run_result",
                    "status": "failed",
                    "outputText": "Free model usage limit reached.",
                    "quotaExhausted": True,
                })
                self.stdout.close()
                self.exit_code = 0
            elif self.scenario == "tool":
                self.stdout.push({
                    "type": "tool_request",
                    "requestId": "r1",
                    "toolName": "workspace_read_file",
                    "input": {"path": "main.py"},
                })
            elif self.scenario == "approval":
                self.stdout.push({
                    "type": "approval_request",
                    "requestId": "a1",
                    "toolName": "workspace_write_file",
                    "input": {"path": "new.py", "content": "secret source is not exposed"},
                })
            elif self.scenario == "fatal":
                self.stdout.push({"type": "fatal", "message": "worker failed"})
                self.stdout.close()
                self.exit_code = 1
        elif message_type == "tool_result":
            self.stdout.push({"type": "run_result", "status": "completed", "outputText": "Task complete."})
            self.stdout.close()
            self.exit_code = 0
        elif message_type == "approval_result":
            if message.get("approved"):
                self.stdout.push({
                    "type": "tool_request",
                    "requestId": "r2",
                    "toolName": "workspace_write_file",
                    "input": {"path": "new.py", "content": "safe"},
                })
            else:
                self.stdout.push({"type": "run_result", "status": "failed", "outputText": "Approval denied."})
                self.stdout.close()
                self.exit_code = 0
        elif message_type == "cancel":
            self.stdout.push({"type": "run_result", "status": "aborted", "outputText": ""})
            self.stdout.close()
            self.exit_code = 0

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


class _FakeEngineProcess:
    def __init__(self, action):
        self.action = action

    def run(
        self, goal, config, mode, *, on_tool_request, on_approval_request,
        selected_skills=(), on_event, cancel_flag,
    ):
        self.selected_skills = tuple(selected_skills)
        result = self.action(
            goal, config, mode, on_tool_request, on_approval_request, on_event, cancel_flag
        )
        return ClineResult(status="completed", text=result)


def _healthy():
    return {
        "ready": True,
        "cli_available": True,
        "sdk_available": True,
        "model_service": {
            "available": True,
            "models": [DEFAULT_MODEL],
            "error": None,
        },
    }


class ClineProtocolTests(unittest.TestCase):
    def test_ndjson_round_trip_and_reject_invalid_messages(self):
        encoded = encode_message({"type": "start", "goal": "Review code"})
        self.assertEqual(decode_message(encoded)["goal"], "Review code")
        with self.assertRaises(ClineProtocolError):
            decode_message('{"not_type": true}')
        with self.assertRaises(ClineProtocolError):
            decode_message("{invalid json}")

    def test_process_streams_events_and_returns_final_result(self):
        child = _FakeProcess("result")
        process = ClineProcess(
            node_executable="fake-node",
            worker_path=Path(__file__),
            sdk_entrypoint=Path(__file__),
            popen=lambda *args, **kwargs: child,
        )
        with tempfile.TemporaryDirectory() as directory:
            result = process.run(
                "Make a plan",
                ClineConfig(
                    Path(directory),
                    target_window_hwnd=101,
                    target_window_pid=202,
                ),
                ClineMode.PLAN,
                on_tool_request=lambda *_: "",
                on_approval_request=lambda *_: False,
                selected_skills=[{
                    "id": "testing-debugging-mastery",
                    "description": "Verify behavior with evidence.",
                }],
            )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.text, "Plan ready.")
        self.assertEqual(result.events[0].event_type, "run-started")
        self.assertEqual(child.messages[0]["type"], "start")
        self.assertEqual(
            child.messages[0]["selected_skills"],
            [{"id": "testing-debugging-mastery", "description": "Verify behavior with evidence."}],
        )
        self.assertEqual(child.messages[0]["target_window_hwnd"], 101)
        self.assertEqual(child.messages[0]["target_window_pid"], 202)

    def test_process_routes_tool_requests_without_real_cline(self):
        child = _FakeProcess("tool")
        process = ClineProcess(
            node_executable="fake-node",
            worker_path=Path(__file__),
            sdk_entrypoint=Path(__file__),
            popen=lambda *args, **kwargs: child,
        )
        with tempfile.TemporaryDirectory() as directory:
            result = process.run(
                "Read main.py",
                ClineConfig(Path(directory)),
                ClineMode.PLAN,
                on_tool_request=lambda name, args: f"{name}:{args['path']}",
                on_approval_request=lambda *_: False,
            )
        self.assertEqual(result.text, "Task complete.")
        response = next(item for item in child.messages if item["type"] == "tool_result")
        self.assertEqual(response["output"], "workspace_read_file:main.py")

    def test_process_requires_human_approval_and_never_approves_by_default(self):
        child = _FakeProcess("approval")
        process = ClineProcess(
            node_executable="fake-node",
            worker_path=Path(__file__),
            sdk_entrypoint=Path(__file__),
            popen=lambda *args, **kwargs: child,
        )
        with tempfile.TemporaryDirectory() as directory:
            result = process.run(
                "Create a file",
                ClineConfig(Path(directory)),
                ClineMode.ASSISTED,
                on_tool_request=lambda *_: "created",
                on_approval_request=lambda *_: True,
            )
        approval = next(item for item in child.messages if item["type"] == "approval_result")
        self.assertTrue(approval["approved"])
        self.assertEqual(result.status, "completed")

    def test_process_surfaces_worker_errors(self):
        child = _FakeProcess("fatal")
        process = ClineProcess(
            node_executable="fake-node",
            worker_path=Path(__file__),
            sdk_entrypoint=Path(__file__),
            popen=lambda *args, **kwargs: child,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ClineProcessError, "worker failed"):
                process.run(
                    "Read project",
                    ClineConfig(Path(directory)),
                    ClineMode.PLAN,
                    on_tool_request=lambda *_: "",
                    on_approval_request=lambda *_: False,
                )

    def test_process_denial_never_dispatches_the_write(self):
        child = _FakeProcess("approval")
        process = ClineProcess(
            node_executable="fake-node",
            worker_path=Path(__file__),
            sdk_entrypoint=Path(__file__),
            popen=lambda *args, **kwargs: child,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ClineProcessError):
                process.run(
                    "Create a file",
                    ClineConfig(Path(directory)),
                    ClineMode.ASSISTED,
                    on_tool_request=lambda *_: self.fail("Denied action must not run"),
                    on_approval_request=lambda *_: False,
                )
        self.assertFalse(any(item["type"] == "tool_result" for item in child.messages))

    def test_process_cancellation_interrupts_the_worker(self):
        child = _FakeProcess("waiting")
        process = ClineProcess(
            node_executable="fake-node",
            worker_path=Path(__file__),
            sdk_entrypoint=Path(__file__),
            popen=lambda *args, **kwargs: child,
        )
        cancelled = threading.Event()
        timer = threading.Timer(0.05, cancelled.set)
        timer.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ClineCancelled):
                    process.run(
                        "Wait",
                        ClineConfig(Path(directory)),
                        ClineMode.PLAN,
                        on_tool_request=lambda *_: "",
                        on_approval_request=lambda *_: False,
                        cancel_flag=cancelled,
                    )
        finally:
            timer.cancel()
        self.assertTrue(any(item["type"] == "cancel" for item in child.messages))


class ClineEngineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)

    def tearDown(self):
        self.directory.cleanup()

    def engine(self, action):
        return ClineEngine(process=_FakeEngineProcess(action), health_check=_healthy)

    def test_plan_mode_is_read_only(self):
        def action(goal, config, mode, run_tool, approve, *_):
            with self.assertRaises(ClineEngineError):
                run_tool("workspace_write_file", {"path": "new.py", "content": "no"})
            with self.assertRaises(ClineEngineError):
                run_tool("workspace_open_folder", {})
            with self.assertRaises(ClineEngineError):
                run_tool("workspace_window_observe", {})
            run_tool("workspace_list_files", {})
            return "Plan only."

        result = self.engine(action).execute(
            "Inspect the project",
            self.root,
            "plan",
            target_window_hwnd=123,
            target_window_pid=456,
        )
        self.assertEqual(result.text, "Plan only.")
        self.assertFalse((self.root / "new.py").exists())

    def test_open_folder_is_limited_to_workspace_and_requires_approval(self):
        project = self.root / "project"
        project.mkdir()
        args = validate_tool_input(
            "workspace_open_folder",
            {"path": "project"},
            self.root,
        )
        self.assertTrue(
            approval_required(
                ClineMode.AUTONOMOUS_CONTROLLED,
                "workspace_open_folder",
                args,
                self.root,
            )
        )
        with self.assertRaises(WorkspaceError):
            validate_tool_input(
                "workspace_open_folder",
                {"path": ".."},
                self.root,
            )
        with self.assertRaises(WorkspaceError):
            validate_tool_input(
                "workspace_open_folder",
                {"path": "missing"},
                self.root,
            )
        with patch("agent.workspace_tools.subprocess.Popen") as launch:
            result = open_folder("project", workspace_root=self.root)
        launch.assert_called_once()
        self.assertIn("Windows Explorer", result)

    def test_cline_opens_a_requested_folder_only_after_approval(self):
        project = self.root / "project"
        project.mkdir()
        prompts = []

        def action(_goal, _config, _mode, run_tool, approve, *_):
            args = {"path": "project"}
            self.assertTrue(approve("workspace_open_folder", args))
            return run_tool("workspace_open_folder", args)

        with patch("agent.workspace_tools.subprocess.Popen") as launch:
            result = self.engine(action).execute(
                "Open the project folder in Explorer",
                self.root,
                ClineMode.AUTONOMOUS_CONTROLLED,
                approval_callback=lambda _tool, _params, description, _cancel: (
                    prompts.append(description) or True
                ),
            )
        self.assertEqual(result.actions, 1)
        self.assertEqual(len(prompts), 1)
        self.assertIn("Explorateur Windows", prompts[0])
        self.assertEqual(launch.call_count, 1)

    def test_window_controls_require_a_selected_window_and_restrict_arguments(self):
        args = {"name": "Projects", "role": "Hyperlink"}
        with self.assertRaises(WorkspaceError):
            validate_tool_input("workspace_window_click", args, self.root)

        self.assertEqual(
            validate_tool_input(
                "workspace_window_click",
                args,
                self.root,
                target_window_hwnd=123,
                target_window_pid=456,
            ),
            args,
        )
        with self.assertRaises(WorkspaceError):
            validate_tool_input(
                "workspace_window_click",
                {**args, "x": 10},
                self.root,
                target_window_hwnd=123,
                target_window_pid=456,
            )
        with self.assertRaises(WorkspaceError):
            validate_tool_input(
                "workspace_window_press",
                {"key": "enter"},
                self.root,
                target_window_hwnd=123,
                target_window_pid=456,
            )

    def test_safe_window_navigation_is_autonomous_but_button_clicks_need_approval(self):
        link = {"name": "Projects", "role": "Hyperlink"}
        button = {"name": "Continue", "role": "Button"}
        self.assertFalse(approval_required(
            ClineMode.AUTONOMOUS_CONTROLLED,
            "workspace_window_click",
            link,
            self.root,
            target_window_hwnd=123,
            target_window_pid=456,
        ))
        self.assertTrue(approval_required(
            ClineMode.AUTONOMOUS_CONTROLLED,
            "workspace_window_click",
            button,
            self.root,
            target_window_hwnd=123,
            target_window_pid=456,
        ))

    def test_selected_window_is_passed_to_bounded_cline_control(self):
        args = {"name": "Projects", "role": "Hyperlink"}

        def action(_goal, _config, _mode, run_tool, approve, *_):
            self.assertTrue(approve("workspace_window_click", args))
            return run_tool("workspace_window_click", args)

        with patch(
            "niang_ia.integrations.cline.cline_desktop.click_control",
            return_value='{"clicked":true}',
        ) as click:
            result = self.engine(action).execute(
                "Open the Projects section",
                self.root,
                ClineMode.AUTONOMOUS_CONTROLLED,
                target_window_hwnd=123,
                target_window_pid=456,
            )
        click.assert_called_once_with(
            123,
            456,
            name="Projects",
            automation_id="",
            role="Hyperlink",
        )
        self.assertEqual(result.actions, 1)

    def test_window_button_click_uses_explicit_approval(self):
        args = {"name": "Continue", "role": "Button"}
        prompts = []

        def action(_goal, _config, _mode, run_tool, approve, *_):
            self.assertFalse(approve("workspace_window_click", args))
            return run_tool("workspace_window_click", args)

        with patch(
            "niang_ia.integrations.cline.cline_desktop.click_control",
            return_value='{"clicked":true}',
        ) as click:
            with self.assertRaises(ClineEngineError):
                self.engine(action).execute(
                    "Continue",
                    self.root,
                    ClineMode.AUTONOMOUS_CONTROLLED,
                    target_window_hwnd=123,
                    target_window_pid=456,
                )
            click.assert_not_called()

        def approved_action(_goal, _config, _mode, run_tool, approve, *_):
            self.assertTrue(approve("workspace_window_click", args))
            return run_tool("workspace_window_click", args)

        with patch(
            "niang_ia.integrations.cline.cline_desktop.click_control",
            return_value='{"clicked":true}',
        ):
            result = self.engine(approved_action).execute(
                "Continue",
                self.root,
                ClineMode.AUTONOMOUS_CONTROLLED,
                target_window_hwnd=123,
                target_window_pid=456,
                approval_callback=lambda tool, _params, description, _cancel: (
                    prompts.append((tool, description)) or True
                ),
            )
        self.assertEqual(result.actions, 1)
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0][0], "workspace_window_click")

    def test_completion_without_workspace_action_is_not_reported_as_success(self):
        response = '{"name":"workspace_write_file","arguments":{"path":"main.py"}}'
        with self.assertRaisesRegex(ClineEngineError, "without using a workspace tool"):
            self.engine(lambda *_: response).execute(
                "Create main.py", self.root, ClineMode.AUTONOMOUS_CONTROLLED
            )
        self.assertFalse((self.root / "main.py").exists())

    def test_selected_skill_is_loaded_through_the_host_and_injected_as_metadata(self):
        def action(_goal, _config, _mode, run_tool, *_):
            instructions = run_tool(
                "workspace_load_skill",
                {"skill_id": "desktop-engineering"},
            )
            run_tool("workspace_list_files", {})
            return instructions

        engine = self.engine(action)
        result = engine.execute(
            "Create a desktop Tkinter application",
            self.root,
            ClineMode.PLAN,
        )
        self.assertIn("# desktop-engineering", result.text)
        self.assertIn(
            "desktop-engineering",
            [skill["id"] for skill in engine.process.selected_skills],
        )
        self.assertIn("desktop-engineering", result.loaded_skills)
        self.assertIn("testing-debugging-mastery", result.selected_skills)

    def test_skill_loader_rejects_an_id_not_selected_for_the_mission(self):
        def action(_goal, _config, _mode, run_tool, *_):
            return run_tool("workspace_load_skill", {"skill_id": "mobile-engineering"})

        with self.assertRaisesRegex(ClineEngineError, "not selected"):
            self.engine(action).execute(
                "Create a desktop Tkinter application",
                self.root,
                ClineMode.PLAN,
            )

    def test_visual_asset_tools_require_the_skill_to_be_loaded_and_inspect_local_files(self):
        def action(_goal, _config, _mode, run_tool, *_):
            with self.assertRaisesRegex(ClineEngineError, "Load visual-asset-intelligence"):
                run_tool("workspace_visual_asset_inspect", {"limit": 1})
            run_tool(
                "workspace_load_skill",
                {"skill_id": "visual-asset-intelligence"},
            )
            result = json.loads(
                run_tool("workspace_visual_asset_inspect", {"limit": 1})
            )
            self.assertEqual(result["status"], "ok")
            return "Visual assets inspected."

        engine = self.engine(action)
        result = engine.execute(
            "Create a landing page with genuine images.",
            self.root,
            ClineMode.PLAN,
        )
        self.assertIn("visual-asset-intelligence", result.loaded_skills)
        self.assertEqual(result.status, "completed")

    def test_visual_provider_search_requires_approval_and_rejects_sensitive_queries(self):
        args = validate_tool_input(
            "workspace_visual_asset_search",
            {"query": "black luxury car"},
            self.root,
        )
        self.assertTrue(
            approval_required(
                ClineMode.AUTONOMOUS_CONTROLLED,
                "workspace_visual_asset_search",
                args,
                self.root,
            )
        )
        with self.assertRaisesRegex(WorkspaceError, "sensitive information"):
            validate_tool_input(
                "workspace_visual_asset_search",
                {"query": "token is sk-123456789012345678901234"},
                self.root,
            )

    def test_autonomous_mode_only_writes_new_files_inside_workspace(self):
        def action(goal, config, mode, run_tool, approve, *_):
            self.assertTrue(approve("workspace_write_file", {"path": "new.py"}))
            return run_tool("workspace_write_file", {"path": "new.py", "content": "safe"})

        result = self.engine(action).execute(
            "Create one file", self.root, ClineMode.AUTONOMOUS_CONTROLLED
        )
        self.assertEqual(result.actions, 1)
        self.assertEqual((self.root / "new.py").read_text(encoding="utf-8"), "safe")

    def test_assisted_mode_requires_explicit_approval_for_writes(self):
        prompts = []

        def action(goal, config, mode, run_tool, approve, *_):
            arguments = {"path": "new.py", "content": "ok"}
            self.assertTrue(approve("workspace_write_file", arguments))
            return run_tool("workspace_write_file", arguments)

        def approval(tool, parameters, description, cancel_flag):
            prompts.append((tool, parameters, description))
            return True

        self.engine(action).execute(
            "Create a file", self.root, "assisted", approval_callback=approval
        )
        self.assertEqual(len(prompts), 1)
        self.assertNotIn("content", prompts[0][1])

    def test_free_model_quota_switches_to_the_next_free_model(self):
        class QuotaThenSuccess:
            def __init__(self):
                self.calls = []

            def run(
                self, goal, config, mode, *, on_tool_request, on_approval_request,
                selected_skills=(), on_event, cancel_flag,
            ):
                self.calls.append((goal, config.model_id))
                if len(self.calls) == 1:
                    raise ClineFreeModelLimitError("Free model usage limit reached.")
                on_tool_request("workspace_list_files", {"path": "."})
                return ClineResult(status="completed", text="Continued.")

        process = QuotaThenSuccess()
        result = ClineEngine(process=process, health_check=_healthy).execute(
            "Create a project",
            self.root,
            ClineMode.PLAN,
        )

        self.assertEqual(
            [model_id for _, model_id in process.calls],
            list(CLINE_FREE_MODELS[:2]),
        )
        self.assertIn("Continue from the current workspace state", process.calls[1][0])
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.actions, 1)

    def test_non_quota_provider_errors_do_not_trigger_fallback(self):
        class FailedProcess:
            calls = 0

            def run(self, *_args, **_kwargs):
                self.calls += 1
                raise ClineProcessError("Authentication failed.")

        process = FailedProcess()
        with self.assertRaisesRegex(ClineEngineError, "Authentication failed"):
            ClineEngine(process=process, health_check=_healthy).execute(
                "Create a project", self.root, ClineMode.PLAN
            )
        self.assertEqual(process.calls, 1)

    def test_exhausted_cline_quotas_stop_without_a_paid_fallback(self):
        class AlwaysQuota:
            def __init__(self):
                self.models = []

            def run(self, _goal, config, *_args, **_kwargs):
                self.models.append(config.model_id)
                raise ClineFreeModelLimitError("Free model usage limit reached.")

        process = AlwaysQuota()
        with self.assertRaisesRegex(ClineEngineError, "No paid model was used"):
            ClineEngine(process=process, health_check=_healthy).execute(
                "Create a project", self.root, ClineMode.PLAN
            )
        self.assertEqual(process.models, list(CLINE_FREE_MODELS))

    def test_write_tool_cannot_run_without_an_engine_approval_grant(self):
        def action(_goal, _config, _mode, run_tool, *_):
            return run_tool(
                "workspace_write_file",
                {"path": "unapproved.py", "content": "blocked"},
            )

        with self.assertRaisesRegex(ClineEngineError, "explicit human approval"):
            self.engine(action).execute("Create a file", self.root, "assisted")

        self.assertFalse((self.root / "unapproved.py").exists())

    def test_install_and_executable_checks_still_require_approval_in_autonomous_mode(self):
        approval_requests = []

        def action(goal, config, mode, run_tool, approve, *_):
            for check in ("python-tests", "npm-lint", "tsc-check", "go-vet",
                          "cargo-check", "dotnet-build"):
                self.assertTrue(approve("workspace_run_check", {"check": check}))
            self.assertTrue(approve(
                "workspace_run_check",
                {"check": "git-status"},
            ))
            self.assertTrue(approve(
                "workspace_install_dependency",
                {"ecosystem": "node", "package": "example-package"},
            ))
            run_tool("workspace_list_files", {})
            return "checked"

        def request_approval(tool, parameters, description, cancel_flag):
            approval_requests.append((tool, parameters, description))
            return True

        result = self.engine(action).execute(
            "Inspect project", self.root, "autonomous_controlled",
            approval_callback=request_approval,
        )
        self.assertEqual(result.status, "completed")

        requested_checks = [
            item[1]["description"] for item in approval_requests
            if item[0] == "workspace_run_check"
        ]
        self.assertEqual(len(requested_checks), 6)
        self.assertTrue(all("Exécuter le contrôle" in item for item in requested_checks))
        self.assertEqual(
            sum(item[0] == "workspace_install_dependency" for item in approval_requests),
            1,
        )

    def test_action_limit_cannot_exceed_twenty(self):
        def action(goal, config, mode, run_tool, *_):
            for _ in range(MAX_ACTIONS + 1):
                run_tool("workspace_list_files", {})
            return "unreachable"

        with self.assertRaises(ClineEngineError):
            self.engine(action).execute("Inspect", self.root, "plan")

    def test_sensitive_goal_is_rejected_before_provider_use(self):
        health_called = []
        engine = ClineEngine(
            process=_FakeEngineProcess(lambda *_: "unreachable"),
            health_check=lambda: health_called.append(True) or _healthy(),
        )
        with self.assertRaises(ClineEngineError):
            engine.execute("Use api_key=sk-123456789012345678901", self.root, "plan")
        self.assertEqual(health_called, [])

    def test_outside_workspace_and_protected_files_are_rejected(self):
        outside = self.root.parent / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        try:
            with self.assertRaises(WorkspaceError):
                read_file(str(outside), workspace_root=self.root)
            with self.assertRaises(WorkspaceError):
                write_file(".env", "secret", workspace_root=self.root)
        finally:
            outside.unlink(missing_ok=True)

    def test_config_caps_per_action_and_per_mission_limits(self):
        with self.assertRaises(ValueError):
            ClineConfig(self.root, max_actions=MAX_ACTIONS + 1)
        with self.assertRaises(ValueError):
            ClineConfig(self.root, action_timeout_seconds=MAX_ACTION_SECONDS + 1)
        with self.assertRaisesRegex(ValueError, "requires both"):
            ClineConfig(self.root, target_window_hwnd=123)
        with self.assertRaisesRegex(ValueError, "handle is invalid"):
            ClineConfig(self.root, target_window_hwnd=123, target_window_pid=0)

    def test_config_allows_only_the_cline_free_fallback_models(self):
        config = ClineConfig(self.root)
        self.assertEqual(config.provider_id, DEFAULT_PROVIDER)
        self.assertEqual(config.model_id, DEFAULT_MODEL)
        self.assertEqual(
            ClineConfig(self.root, provider_id="ollama").model_id,
            DEFAULT_OLLAMA_MODEL,
        )
        with self.assertRaisesRegex(ValueError, "only the configured free models"):
            ClineConfig(self.root, provider_id="cline", model_id="anthropic/paid")

    def test_queue_accepts_specialized_missions_without_running_a_real_engine(self):
        queue_instance = TaskQueue(persist=False)
        task_id = queue_instance.submit(
            "Analyze the project",
            executor_kind="cline",
            cline_workspace_root=str(self.root),
            cline_mode="plan",
            cline_target_window_hwnd=123,
            cline_target_window_pid=456,
        )
        status = queue_instance.get_status(task_id)
        self.assertEqual(status["executor_kind"], "cline")
        self.assertEqual(status["status"], "pending")
        self.assertEqual(status["cline_workspace_root"], str(self.root))
        self.assertEqual(status["cline_target_window_hwnd"], 123)
        self.assertEqual(status["cline_target_window_pid"], 456)

    def test_queue_dispatches_cline_missions_to_the_engine(self):
        from agent.task_queue import Task, TaskStatus

        queue_instance = TaskQueue(persist=False)
        task = Task(
            priority=2,
            created_at=1.0,
            task_id="cline-task",
            goal="Inspect this project",
            status=TaskStatus.RUNNING,
            executor_kind="cline",
            cline_workspace_root=str(self.root),
            cline_mode="plan",
            cline_target_window_hwnd=123,
            cline_target_window_pid=456,
        )
        queue_instance._tasks[task.task_id] = task
        queue_instance._active_count = 1

        call_order = []
        with patch(
            "niang_ia.integrations.cline.cline_vscode.open_vscode_workspace",
            side_effect=lambda *_: call_order.append("vscode"),
        ) as open_vscode, patch(
            "niang_ia.integrations.cline.cline_engine.ClineEngine"
        ) as engine_type:
            engine_type.return_value.execute.side_effect = (
                lambda *_args, **_kwargs: call_order.append("engine")
                or ClineResult(
                    status="completed",
                    text="Plan generated.",
                    verified=True,
                    quality_gate={
                        "status": "NOT_TESTED",
                        "checks": [{
                            "id": "tests",
                            "name": "Automated tests",
                            "status": "NOT_TESTED",
                            "evidence": [],
                        }],
                    },
                    selected_skills=["testing-debugging-mastery"],
                    loaded_skills=["testing-debugging-mastery"],
                )
            )
            queue_instance._run_task(task)

        engine_type.return_value.execute.assert_called_once()
        self.assertEqual(
            engine_type.return_value.execute.call_args.kwargs[
                "target_window_hwnd"
            ],
            123,
        )
        self.assertEqual(
            engine_type.return_value.execute.call_args.kwargs[
                "target_window_pid"
            ],
            456,
        )
        open_vscode.assert_not_called()
        self.assertEqual(call_order, ["engine"])
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIn("Plan generated.", task.result)
        self.assertIn("Skills loaded: testing-debugging-mastery", task.result)
        self.assertIn("QUALITY GATE: NON TESTÉ", task.result)

    def test_queue_runs_cline_without_launching_vscode(self):
        from agent.task_queue import Task, TaskStatus

        queue_instance = TaskQueue(persist=False)
        task = Task(
            priority=2,
            created_at=1.0,
            task_id="vscode-unavailable",
            goal="Create a file",
            status=TaskStatus.RUNNING,
            executor_kind="cline",
            cline_workspace_root=str(self.root),
            cline_mode="assisted",
        )
        queue_instance._tasks[task.task_id] = task
        queue_instance._active_count = 1

        with patch(
            "niang_ia.integrations.cline.cline_vscode.open_vscode_workspace",
            side_effect=RuntimeError("VS Code unavailable"),
        ) as open_vscode, patch(
            "niang_ia.integrations.cline.cline_engine.ClineEngine"
        ) as engine_type:
            engine_type.return_value.execute.return_value = ClineResult(
                status="completed",
                text="Mission completed.",
            )
            queue_instance._run_task(task)

        open_vscode.assert_not_called()
        engine_type.return_value.execute.assert_called_once()
        self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_open_vscode_workspace_uses_new_window_and_selected_root(self):
        with patch(
            "niang_ia.integrations.cline.cline_vscode.find_vscode_executable",
            return_value=self.root / "Code.exe",
        ), patch(
            "niang_ia.integrations.cline.cline_vscode.subprocess.Popen"
        ) as popen:
            open_vscode_workspace(self.root)

        args, kwargs = popen.call_args
        self.assertEqual(args[0][1:], ["--new-window", str(self.root.resolve())])
        self.assertEqual(kwargs["cwd"], str(self.root.resolve()))
        self.assertFalse(kwargs["shell"])

    def test_child_environment_does_not_inherit_api_keys(self):
        with patch.dict(os.environ, {
            "GEMINI_API_KEY": "not-forwarded",
            "OPENAI_API_KEY": "not-forwarded",
            "CLINE_API_KEY": "not-forwarded",
        }):
            env = _safe_child_environment()
        self.assertNotIn("GEMINI_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("CLINE_API_KEY", env)

    def test_process_reports_a_typed_free_quota_failure(self):
        child = _FakeProcess("quota")
        process = ClineProcess(
            node_executable="fake-node",
            worker_path=Path(__file__),
            sdk_entrypoint=Path(__file__),
            popen=lambda *args, **kwargs: child,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ClineFreeModelLimitError):
                process.run(
                    "Create a project",
                    ClineConfig(Path(directory)),
                    ClineMode.PLAN,
                    on_tool_request=lambda *_: "",
                    on_approval_request=lambda *_: False,
                )


class ClineDesktopTests(unittest.TestCase):
    class FakeDesktop:
        def __init__(self, *, pid=456, controls=None):
            self.pid = pid
            self._controls = controls or []
            self.clicked = False
            self.typed = False

        def window(self, *, hwnd):
            return {
                "hwnd": hwnd,
                "pid": self.pid,
                "visible": True,
                "minimized": False,
            }

        def controls(self, hwnd, *, limit):
            return self._controls[:limit]

        def click(self, hwnd, *, name=None, automation_id=None):
            self.clicked = True
            return {"clicked": name or automation_id}

        def type_text(self, hwnd, text, *, name=None, automation_id=None):
            self.typed = True
            return {"verified": True}

    def test_observation_omits_sensitive_controls_even_when_password_state_is_unknown(self):
        controls = [
            {
                "name": "Password",
                "automation_id": "passwordBox",
                "role": "Edit",
                "visible": True,
                "enabled": True,
                "password": None,
            },
            {
                "name": "Projects",
                "automation_id": "projectsLink",
                "role": "Hyperlink",
                "visible": True,
                "enabled": True,
                "password": False,
            },
        ]
        desktop = self.FakeDesktop(controls=controls)
        with patch(
            "niang_ia.integrations.cline.cline_desktop.WindowsDesktopAgent",
            return_value=desktop,
        ):
            from niang_ia.integrations.cline.cline_desktop import observe_window
            result = json.loads(observe_window(123, 456))
        self.assertEqual([item["name"] for item in result["controls"]], ["Projects"])

    def test_control_action_rejects_replaced_window_and_sensitive_fields(self):
        from niang_ia.integrations.cline.cline_desktop import (
            click_control,
            type_into_control,
        )

        replaced = self.FakeDesktop(pid=999)
        with patch(
            "niang_ia.integrations.cline.cline_desktop.WindowsDesktopAgent",
            return_value=replaced,
        ):
            with self.assertRaisesRegex(WindowsDesktopError, "window changed"):
                click_control(123, 456, name="Projects", role="Hyperlink")
        self.assertFalse(replaced.clicked)

        sensitive = self.FakeDesktop(controls=[{
            "name": "API key",
            "automation_id": "api_key",
            "role": "Edit",
            "visible": True,
            "enabled": True,
            "password": None,
        }])
        with patch(
            "niang_ia.integrations.cline.cline_desktop.WindowsDesktopAgent",
            return_value=sensitive,
        ):
            with self.assertRaisesRegex(WindowsDesktopError, "password fields"):
                type_into_control(123, 456, name="API key", text="not-a-secret")
        self.assertFalse(sensitive.typed)


class ClineHealthTests(unittest.TestCase):
    def test_default_provider_uses_the_cline_free_fallback_order(self):
        self.assertEqual(DEFAULT_PROVIDER, "cline")
        self.assertEqual(DEFAULT_MODEL, CLINE_FREE_MODELS[0])
        self.assertEqual(len(CLINE_FREE_MODELS), 3)

    def test_cli_detection_finds_the_installed_package_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "cline"
            (package / "bin").mkdir(parents=True)
            (package / "package.json").write_text('{"name":"cline"}', encoding="utf-8")
            with patch(
                "niang_ia.integrations.cline.cline_health._cline_package_roots",
                return_value=[package],
            ), patch(
                "niang_ia.integrations.cline.cline_health.shutil.which",
                return_value=None,
            ):
                from niang_ia.integrations.cline.cline_health import find_cline_binary
                self.assertEqual(find_cline_binary(), package / "bin" / "cline")

    def test_health_reports_local_auth_without_secrets(self):
        with patch(
            "niang_ia.integrations.cline.cline_health.find_cline_binary",
            return_value=Path("cline.cmd"),
        ), patch(
            "niang_ia.integrations.cline.cline_health.find_agent_sdk_entrypoint",
            return_value=Path("sdk.mjs"),
        ), patch(
            "niang_ia.integrations.cline.cline_health.get_cline_version",
            return_value="3.0.74",
        ), patch(
            "niang_ia.integrations.cline.cline_health._probe_ollama",
            return_value={"available": True, "models": [DEFAULT_OLLAMA_MODEL], "error": None},
        ):
            result = check_cline_health(provider_id="ollama")
        self.assertTrue(result["ready"])
        self.assertEqual(result["authentication"], "not_required_for_local_ollama")
        self.assertNotIn("api_key", json.dumps(result).lower())

    def test_version_check_uses_cli_version_output_only(self):
        package_root = Path(tempfile.mkdtemp())
        try:
            with patch(
                "niang_ia.integrations.cline.cline_health._cline_package_roots",
                return_value=[package_root],
            ), patch(
                "niang_ia.integrations.cline.cline_health.shutil.which",
                return_value="node.exe",
            ), patch(
                "niang_ia.integrations.cline.cline_health.subprocess.run",
                return_value=type("Completed", (), {"returncode": 0, "stdout": "3.0.74\n", "stderr": ""})(),
            ) as run:
                self.assertEqual(get_cline_version(), "3.0.74")
                self.assertIn("--version", run.call_args.args[0])
        finally:
            import shutil
            shutil.rmtree(package_root)

    def test_legacy_manager_cannot_launch_uncontrolled_cli_tasks(self):
        with self.assertRaises(ClineExecutionError):
            ClineManager().start_task("task", ".", auto_approve=True)


if __name__ == "__main__":
    unittest.main()

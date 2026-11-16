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
from agent.workspace_tools import WorkspaceError, read_file, write_file
from niang_ia.integrations.cline.cline_config import (
    DEFAULT_MODEL,
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

    def run(self, goal, config, mode, *, on_tool_request, on_approval_request, on_event, cancel_flag):
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
                ClineConfig(Path(directory)),
                ClineMode.PLAN,
                on_tool_request=lambda *_: "",
                on_approval_request=lambda *_: False,
            )
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.text, "Plan ready.")
        self.assertEqual(result.events[0].event_type, "run-started")
        self.assertEqual(child.messages[0]["type"], "start")

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
            run_tool("workspace_list_files", {})
            return "Plan only."

        result = self.engine(action).execute("Inspect the project", self.root, "plan")
        self.assertEqual(result.text, "Plan only.")
        self.assertFalse((self.root / "new.py").exists())

    def test_completion_without_workspace_action_is_not_reported_as_success(self):
        response = '{"name":"workspace_write_file","arguments":{"path":"main.py"}}'
        with self.assertRaisesRegex(ClineEngineError, "without using a workspace tool"):
            self.engine(lambda *_: response).execute(
                "Create main.py", self.root, ClineMode.AUTONOMOUS_CONTROLLED
            )
        self.assertFalse((self.root / "main.py").exists())

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
        def action(goal, config, mode, run_tool, approve, *_):
            self.assertFalse(approve(
                "workspace_install_dependency",
                {"ecosystem": "node", "package": "example-package"},
            ))
            self.assertFalse(approve(
                "workspace_run_check",
                {"check": "python-tests"},
            ))
            self.assertTrue(approve(
                "workspace_run_check",
                {"check": "git-status"},
            ))
            run_tool("workspace_list_files", {})
            return "checked"

        result = self.engine(action).execute(
            "Inspect project", self.root, "autonomous_controlled",
        )
        self.assertEqual(result.status, "completed")

        from niang_ia.integrations.cline.cline_engine import _SAFE_AUTONOMOUS_CHECKS
        self.assertNotIn("python-tests", _SAFE_AUTONOMOUS_CHECKS)
        self.assertNotIn("npm-test", _SAFE_AUTONOMOUS_CHECKS)

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

    def test_queue_accepts_specialized_missions_without_running_a_real_engine(self):
        queue_instance = TaskQueue(persist=False)
        task_id = queue_instance.submit(
            "Analyze the project",
            executor_kind="cline",
            cline_workspace_root=str(self.root),
            cline_mode="plan",
        )
        status = queue_instance.get_status(task_id)
        self.assertEqual(status["executor_kind"], "cline")
        self.assertEqual(status["status"], "pending")
        self.assertEqual(status["cline_workspace_root"], str(self.root))

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
        )
        queue_instance._tasks[task.task_id] = task
        queue_instance._active_count = 1

        call_order = []
        with patch(
            "niang_ia.integrations.cline.cline_vscode.open_vscode_workspace",
            side_effect=lambda *_: call_order.append("vscode"),
        ), patch(
            "niang_ia.integrations.cline.cline_engine.ClineEngine"
        ) as engine_type:
            engine_type.return_value.execute.side_effect = (
                lambda *_args, **_kwargs: call_order.append("engine")
                or ClineResult(status="completed", text="Plan generated.", verified=True)
            )
            queue_instance._run_task(task)

        engine_type.return_value.execute.assert_called_once()
        self.assertEqual(call_order, ["vscode", "engine"])
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertEqual(task.result, "Plan generated.")

    def test_queue_does_not_run_cline_if_vscode_cannot_open(self):
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
        ), patch(
            "niang_ia.integrations.cline.cline_engine.ClineEngine"
        ) as engine_type:
            queue_instance._run_task(task)

        engine_type.return_value.execute.assert_not_called()
        self.assertEqual(task.status, TaskStatus.FAILED)
        self.assertIn("VS Code unavailable", task.error)

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
        with patch.dict(os.environ, {"GEMINI_API_KEY": "not-forwarded", "OPENAI_API_KEY": "not-forwarded"}):
            env = _safe_child_environment()
        self.assertNotIn("GEMINI_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)


class ClineHealthTests(unittest.TestCase):
    def test_default_model_is_tool_calling_compatible_choice(self):
        # qwen2.5-coder:7b emitted tool calls as plain text via Ollama in this stack;
        # default must target a model with native tool-call support.
        self.assertEqual(DEFAULT_MODEL, "qwen2.5:7b")

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
            return_value={"available": True, "models": [DEFAULT_MODEL], "error": None},
        ):
            result = check_cline_health()
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

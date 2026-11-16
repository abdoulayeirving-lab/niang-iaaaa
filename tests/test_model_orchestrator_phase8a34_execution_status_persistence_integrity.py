import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.executor import MissionExecutionResult, _coerce_result_status
from agent.mission_store import MissionStore
from agent.task_queue import Task, TaskQueue, TaskStatus
from agent.tool_registry import ToolDefinition, ToolExecutionContext, ToolExecutionResult, ToolRegistry
from niang_ia.model_orchestrator.workspace_verification import TrustedWorkspaceVerifier


def _proof_for(mission_id: str, workspace_root: str):
    return TrustedWorkspaceVerifier(use_persisted_key=False).inspect(workspace_root, mission_id=mission_id)


class Phase8A34ExecutionStatusPersistenceIntegrityTests(unittest.TestCase):
    def test_none_result_is_unknown(self):
        self.assertEqual(_coerce_result_status(None), "unknown")

    def test_empty_result_is_unknown(self):
        self.assertEqual(_coerce_result_status(""), "unknown")

    def test_dict_with_unknown_status_is_unknown(self):
        self.assertEqual(_coerce_result_status({"status": "mystery"}), "unknown")

    def test_invalid_object_status_is_unknown(self):
        class Result:
            status = "weird"

        self.assertEqual(_coerce_result_status(Result()), "unknown")

    def test_partial_status_is_partial(self):
        self.assertEqual(_coerce_result_status({"status": "partial"}), "partial")

    def test_blocked_status_is_blocked(self):
        self.assertEqual(_coerce_result_status({"status": "blocked"}), "blocked")

    def test_structured_result_metadata_is_preserved(self):
        task = Task(
            priority=2,
            created_at=0.0,
            task_id="meta",
            goal="persist result",
            status=TaskStatus.RUNNING,
            result=ToolExecutionResult(
                "workspace_write_file",
                "Wrote 10 bytes to workspace/ok.txt.",
                ok=True,
                status="returned",
                verified=True,
                error_kind="",
            ),
        )
        payload = TaskQueue._task_payload(task)
        self.assertEqual(payload["result"]["status"], "returned")
        self.assertTrue(payload["result"]["verified"])
        self.assertEqual(payload["result"]["tool_name"], "workspace_write_file")

    def test_structured_metadata_survives_reload(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "missions.db"
            q = TaskQueue(persist=True)
            q._mission_store = MissionStore(db_path)
            task = Task(
                priority=2,
                created_at=0.0,
                task_id="reload-meta",
                goal="persist result",
                status=TaskStatus.RUNNING,
                result=ToolExecutionResult(
                    "workspace_write_file",
                    "Wrote 3 bytes.",
                    ok=True,
                    status="returned",
                    verified=True,
                    error_kind="",
                ),
            )
            q._persist_task(task)
            q2 = TaskQueue(persist=True)
            q2._mission_store = MissionStore(db_path)
            q2._restore_missions()
            restored = q2._tasks["reload-meta"]
            self.assertEqual(restored.result["status"], "returned")
            self.assertTrue(restored.result["verified"])

    def test_mission_store_save_failure_marks_task_blocked(self):
        q = TaskQueue(persist=True)
        q._mission_store = mock.Mock()
        q._mission_store.save.side_effect = RuntimeError("disk full")
        task = Task(
            priority=2,
            created_at=0.0,
            task_id="persist-fail",
            goal="persist failure",
            status=TaskStatus.RUNNING,
            workspace_verification_required=True,
            continuity_mission_id="persist-fail",
            continuity_workspace_proof={"mission_id": "persist-fail"},
        )
        q._persist_task(task)
        self.assertEqual(task.status, TaskStatus.BLOCKED)
        self.assertIn("Mission persistence failed", task.error)

    def test_dpapi_unavailable_raises_runtime_error(self):
        with mock.patch("agent.mission_store._protect", side_effect=RuntimeError("DPAPI unavailable")):
            with self.assertRaises(RuntimeError):
                MissionStore(Path("/tmp/test.db")).save("a", "blocked", {"status": "blocked"})

    def test_fs_write_succeeds_then_persistence_failure_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "written.txt"
            target.write_text("before", encoding="utf-8")
            q = TaskQueue(persist=True)
            q._mission_store = mock.Mock()
            q._mission_store.save.side_effect = RuntimeError("save failed")
            task = Task(
                priority=2,
                created_at=0.0,
                task_id="write-then-save-fail",
                goal="write file",
                status=TaskStatus.RUNNING,
            )
            target.write_text("after", encoding="utf-8")
            q._persist_task(task)
            self.assertEqual(task.status, TaskStatus.BLOCKED)
            self.assertEqual(target.read_text(encoding="utf-8"), "after")

    def test_protected_mission_without_context_is_blocked(self):
        q = TaskQueue(persist=False)
        task = Task(
            priority=2,
            created_at=0.0,
            task_id="no-context",
            goal="write",
            status=TaskStatus.PENDING,
            workspace_verification_required=True,
            continuity_mission_id="no-context",
        )
        q._tasks[task.task_id] = task
        q._queue = []
        with mock.patch.object(q, "_get_executor") as get_executor:
            q._run_task(task)
        get_executor.assert_not_called()
        self.assertEqual(task.status, TaskStatus.BLOCKED)

    def test_protected_cline_without_proof_is_blocked(self):
        q = TaskQueue(persist=False)
        task = Task(
            priority=2,
            created_at=0.0,
            task_id="cline-no-proof",
            goal="write",
            status=TaskStatus.PENDING,
            executor_kind="cline",
            cline_workspace_root="/tmp",
            workspace_verification_required=True,
            continuity_mission_id="cline-no-proof",
        )
        q._tasks[task.task_id] = task
        q._queue = []
        with mock.patch("niang_ia.integrations.cline.cline_engine.ClineEngine.execute") as mock_execute:
            q._run_task(task)
        mock_execute.assert_not_called()
        self.assertEqual(task.status, TaskStatus.BLOCKED)

    def test_protected_cline_with_valid_proof_executes(self):
        with tempfile.TemporaryDirectory() as td:
            workspace_root = Path(td)
            proof = _proof_for("cline-proof", str(workspace_root))
            q = TaskQueue(persist=False)
            task = Task(
                priority=2,
                created_at=0.0,
                task_id="cline-proof",
                goal="write file",
                status=TaskStatus.PENDING,
                executor_kind="cline",
                cline_workspace_root=str(workspace_root),
                workspace_verification_required=True,
                continuity_mission_id="cline-proof",
                continuity_workspace_proof=proof,
                continuity_workspace_root=str(workspace_root),
            )
            q._tasks[task.task_id] = task
            q._queue = []
            with mock.patch("niang_ia.model_orchestrator.workspace_verification.validate_proof", return_value=(True, [])), \
                 mock.patch("niang_ia.integrations.cline.cline_vscode.open_vscode_workspace"), \
                 mock.patch("niang_ia.integrations.cline.cline_engine.ClineEngine.execute", return_value=MissionExecutionResult("done", status="completed")) as mock_execute:
                q._run_task(task)
            mock_execute.assert_called_once()
            self.assertEqual(task.status, TaskStatus.COMPLETED)

    def test_direct_tool_registry_invoke_rejects_protected_sensitive_call(self):
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="workspace_write_file",
                description="write a file",
                parameters={"properties": {"path": {"type": "STRING"}, "content": {"type": "STRING"}}, "required": ["path", "content"]},
                handler=lambda params, ctx: "ok",
                timeout_seconds=10,
                agent_enabled=True,
            )
        )
        with self.assertRaises(Exception):
            registry.invoke(
                "workspace_write_file",
                {"path": "a.txt", "content": "x"},
                ToolExecutionContext(mission_id="m-1", protected=True, agent_mode=True),
            )

    def test_historical_unprotected_mission_keeps_compat(self):
        q = TaskQueue(persist=False)
        task = Task(
            priority=2,
            created_at=0.0,
            task_id="legacy",
            goal="write",
            status=TaskStatus.INTERRUPTED,
            workspace_verification_required=False,
            continuity_workspace_proof=None,
        )
        q._tasks[task.task_id] = task
        q._queue = []
        with mock.patch.object(q, "_get_executor") as get_executor:
            executor = mock.Mock()
            executor.execute.return_value = MissionExecutionResult("ok", status="completed")
            get_executor.return_value = executor
            q._run_task(task)
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        executor.execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.executor import MissionExecutionResult, _call_tool
from agent.mission_store import MissionStore
from agent.task_queue import Task, TaskQueue, TaskStatus
from niang_ia.model_orchestrator.continuity import build_handoff_context
from niang_ia.model_orchestrator.continuity_guard import ContinuityExecutionContext
from niang_ia.model_orchestrator.workspace_verification import TrustedWorkspaceVerifier


def _verifier():
    return TrustedWorkspaceVerifier(use_persisted_key=False)


def _checkpoint(mission_id: str):
    return build_handoff_context(
        mission_id=mission_id,
        objective="resume mission",
        actions_completed=[{"id": "1", "status": "completed", "side_effects_possible": False}],
    ).to_dict()


class Phase8A33ContinuityFailClosedTests(unittest.TestCase):
    def test_blocked_continuity_safety_not_recorded_as_completed(self):
        ctx = ContinuityExecutionContext(
            mission_id="blocked-mission",
            workspace_root="/tmp",
            workspace_verification_required=True,
            continuity_state="recovery_pending",
            action_history=[{"status": "unknown"}],
            last_operation_uncertain=True,
        )
        with mock.patch("safety.needs_confirmation", return_value=False):
            out = _call_tool(
                "workspace_write_file",
                {"path": "blocked.txt", "content": "x"},
                speak=None,
                continuity_context=ctx,
            )
        self.assertIn("Blocked for continuity safety", out)
        self.assertNotIn("completed", out.lower())
        self.assertNotIn("successfully", out.lower())

    def test_blocked_continuity_safety_without_fs_write(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = ContinuityExecutionContext(
                mission_id="blocked-write",
                workspace_root=td,
                workspace_verification_required=True,
                continuity_state="recovery_pending",
                action_history=[{"status": "unknown"}],
                last_operation_uncertain=True,
            )
            with mock.patch("safety.needs_confirmation", return_value=False):
                out = _call_tool(
                    "workspace_write_file",
                    {"path": "blocked.txt", "content": "x"},
                    speak=None,
                    continuity_context=ctx,
                )
            self.assertIn("Blocked for continuity safety", out)
            self.assertFalse(Path(td, "blocked.txt").exists())

    def test_protected_context_construction_exception_blocks(self):
        q = TaskQueue(persist=False)
        q._tasks = {}
        q._queue = []
        task = Task(
            priority=2,
            created_at=0.0,
            task_id="ctx-error",
            goal="write",
            status=TaskStatus.PENDING,
            workspace_verification_required=True,
            continuity_mission_id="ctx-error",
        )
        q._tasks[task.task_id] = task
        with mock.patch("niang_ia.model_orchestrator.continuity_guard.ContinuityExecutionContext", side_effect=RuntimeError("boom")):
            q._run_task(task)
        self.assertEqual(task.status, TaskStatus.BLOCKED)
        self.assertEqual(task.outcome, "blocked")

    def test_protected_context_absent_blocks(self):
        q = TaskQueue(persist=False)
        task = Task(
            priority=2,
            created_at=0.0,
            task_id="missing-context",
            goal="write",
            status=TaskStatus.PENDING,
            workspace_verification_required=True,
            continuity_mission_id="missing-context",
        )
        q._tasks[task.task_id] = task
        q._queue = []
        with mock.patch.object(q, "_get_executor") as get_executor:
            q._run_task(task)
        get_executor.assert_not_called()
        self.assertEqual(task.status, TaskStatus.BLOCKED)

    def test_protected_context_invalid_blocks(self):
        q = TaskQueue(persist=False)
        with tempfile.TemporaryDirectory() as td:
            proof = _verifier().inspect(td, mission_id="other")
            task = Task(
                priority=2,
                created_at=0.0,
                task_id="bad-context",
                goal="write",
                status=TaskStatus.PENDING,
                workspace_verification_required=True,
                continuity_mission_id="expected-mission",
                continuity_workspace_proof=proof,
                continuity_workspace_root=td,
                handoff_summary=_checkpoint("expected-mission"),
            )
            q._tasks[task.task_id] = task
            q._queue = []
            with mock.patch.object(q, "_get_executor") as get_executor:
                q._run_task(task)
            get_executor.assert_not_called()
            self.assertEqual(task.status, TaskStatus.BLOCKED)

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

    def test_malformed_checkpoint_resume_refused(self):
        q = TaskQueue(persist=False)
        task = Task(
            priority=2,
            created_at=0.0,
            task_id="bad-checkpoint",
            goal="resume",
            status=TaskStatus.INTERRUPTED,
            workspace_verification_required=True,
            continuity_mission_id="bad-checkpoint",
            handoff_summary={"weird": 1},
            action_history=[{"status": "completed"}],
        )
        q._tasks[task.task_id] = task
        with self.assertRaises(ValueError):
            q.resume_interrupted(task.task_id, user_confirmed=True, workspace_root="/tmp")

    def test_inconsistent_checkpoint_identity_resume_refused(self):
        q = TaskQueue(persist=False)
        task = Task(
            priority=2,
            created_at=0.0,
            task_id="bad-id",
            goal="resume",
            status=TaskStatus.INTERRUPTED,
            workspace_verification_required=True,
            continuity_mission_id="bad-id",
            handoff_summary=_checkpoint("other-id"),
            action_history=[{"status": "completed"}],
        )
        q._tasks[task.task_id] = task
        with self.assertRaises(ValueError):
            q.resume_interrupted(task.task_id, user_confirmed=True, workspace_root="/tmp")

    def test_deserialization_error_blocks_resume_or_persist(self):
        q = TaskQueue(persist=False)
        task = Task(
            priority=2,
            created_at=0.0,
            task_id="bad-proof",
            goal="resume",
            status=TaskStatus.INTERRUPTED,
            workspace_verification_required=True,
            continuity_mission_id="bad-proof",
            continuity_workspace_proof=object(),
            action_history=[{"status": "completed"}],
        )
        with self.assertRaises(ValueError):
            q._task_payload(task)

    def test_serialization_failure_is_reported_as_blocked(self):
        q = TaskQueue(persist=False)
        task = Task(
            priority=2,
            created_at=0.0,
            task_id="persist-failure",
            goal="resume",
            status=TaskStatus.RUNNING,
            workspace_verification_required=True,
            continuity_mission_id="persist-failure",
            continuity_workspace_proof=object(),
        )
        q._persist_task(task)
        self.assertEqual(task.status, TaskStatus.BLOCKED)
        self.assertIn("Mission persistence failed", task.error)

    def test_absent_proof_after_reload_blocks_resume(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "missions.db"
            q = TaskQueue(persist=True)
            q._mission_store = MissionStore(db_path)
            task = Task(
                priority=2,
                created_at=0.0,
                task_id="reload-missing-proof",
                goal="resume",
                status=TaskStatus.INTERRUPTED,
                workspace_verification_required=True,
                continuity_mission_id="reload-missing-proof",
                continuity_workspace_root=td,
                handoff_summary=_checkpoint("reload-missing-proof"),
                action_history=[{"status": "completed"}],
            )
            q._tasks[task.task_id] = task
            q._persist_task(task)
            self.assertEqual(task.status, TaskStatus.BLOCKED)
            q2 = TaskQueue(persist=True)
            q2._mission_store = MissionStore(db_path)
            q2._restore_missions()
            self.assertEqual(q2._tasks, {})
            with self.assertRaises(ValueError):
                q2.resume_interrupted("reload-missing-proof", user_confirmed=True, workspace_root=td)

    def test_invalid_proof_after_reload_blocks_resume(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "missions.db"
            q = TaskQueue(persist=True)
            q._mission_store = MissionStore(db_path)
            task = Task(
                priority=2,
                created_at=0.0,
                task_id="reload-invalid-proof",
                goal="resume",
                status=TaskStatus.INTERRUPTED,
                workspace_verification_required=True,
                continuity_mission_id="reload-invalid-proof",
                continuity_workspace_root=td,
                continuity_workspace_proof={"signature": "bad", "mission_id": "reload-invalid-proof"},
                handoff_summary=_checkpoint("reload-invalid-proof"),
                action_history=[{"status": "completed"}],
            )
            q._tasks[task.task_id] = task
            q._persist_task(task)
            q2 = TaskQueue(persist=True)
            q2._mission_store = MissionStore(db_path)
            q2._restore_missions()
            with self.assertRaises(ValueError):
                q2.resume_interrupted("reload-invalid-proof", user_confirmed=True, workspace_root=td)

    def test_no_refusal_writes_to_fs(self):
        with tempfile.TemporaryDirectory() as td:
            ctx = ContinuityExecutionContext(
                mission_id="refusal-no-write",
                workspace_root=td,
                workspace_verification_required=True,
                continuity_state="recovery_pending",
                action_history=[{"status": "unknown"}],
                last_operation_uncertain=True,
            )
            before = list(Path(td).iterdir())
            with mock.patch("safety.needs_confirmation", return_value=False):
                out = _call_tool(
                    "workspace_write_file",
                    {"path": "should_not_exist.txt", "content": "x"},
                    speak=None,
                    continuity_context=ctx,
                )
            self.assertIn("Blocked for continuity safety", out)
            self.assertEqual(list(Path(td).iterdir()), before)

    def test_nominal_protected_resume_still_writes_after_validation(self):
        with tempfile.TemporaryDirectory() as td:
            workspace_root = Path(td) / "workspace"
            workspace_root.mkdir()
            storage_root = Path(td) / "storage"
            storage_root.mkdir()
            verifier = _verifier()
            proof = verifier.inspect(str(workspace_root), mission_id="nominal")
            import niang_ia.model_orchestrator.workspace_verification as ws_verification
            real_validate = ws_verification.validate_proof
            real_authorize = ws_verification.authorize_risky_resume_or_write
            q = TaskQueue(persist=True)
            q._mission_store = MissionStore(storage_root / "missions.db")
            task = Task(
                priority=2,
                created_at=0.0,
                task_id="nominal",
                goal="write persisted file",
                status=TaskStatus.INTERRUPTED,
                workspace_verification_required=True,
                continuity_mission_id="nominal",
                continuity_workspace_root=str(workspace_root),
                continuity_workspace_proof=proof,
                handoff_summary=_checkpoint("nominal"),
                action_history=[{"status": "completed"}],
            )
            q._tasks[task.task_id] = task
            q._persist_task(task)
            with mock.patch.dict(os.environ, {"NIANG_IA_WORKSPACE_ROOT": str(workspace_root)}, clear=False), mock.patch("safety.needs_confirmation", return_value=False), mock.patch("agent.executor.create_plan", return_value={
                "steps": [{
                    "step": 1,
                    "tool": "workspace_write_file",
                    "description": "write a file",
                    "parameters": {"path": "validated.txt", "content": "ok"},
                }]
            }), mock.patch(
                "niang_ia.model_orchestrator.workspace_verification.validate_proof",
                side_effect=lambda proof_arg, **kwargs: real_validate(
                    proof_arg,
                    **{k: v for k, v in kwargs.items() if k != "verifier"},
                    verifier=verifier,
                ),
            ), mock.patch(
                "niang_ia.model_orchestrator.workspace_verification.authorize_risky_resume_or_write",
                side_effect=lambda **kwargs: real_authorize(
                    **{k: v for k, v in kwargs.items() if k != "verifier"},
                    verifier=verifier,
                ),
            ):
                task_id = q.resume_interrupted("nominal", user_confirmed=True, workspace_proof=proof, workspace_root=str(workspace_root))
                resumed = q._tasks[task_id]
                q._run_task(resumed)
            self.assertTrue((workspace_root / "validated.txt").exists())
            self.assertIn(resumed.status, {TaskStatus.COMPLETED, TaskStatus.PARTIAL})


if __name__ == "__main__":
    unittest.main()

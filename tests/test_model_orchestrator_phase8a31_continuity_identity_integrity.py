from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent.executor import _call_tool
from agent.task_queue import Task, TaskQueue, TaskStatus
from niang_ia.model_orchestrator.continuity import build_handoff_context
from niang_ia.model_orchestrator.continuity_guard import ContinuityExecutionContext, evaluate_continuity_guard
from niang_ia.model_orchestrator.workspace_verification import TrustedWorkspaceVerifier, authorize_risky_resume_or_write


def _verifier():
    return TrustedWorkspaceVerifier(use_persisted_key=False)


def _stable_handoff(mission_id: str):
    return build_handoff_context(
        mission_id=mission_id,
        objective="resume mission",
        actions_completed=[{"id": "1", "status": "completed", "side_effects_possible": False}],
    )


class Phase8A31SimulatedIdentityIntegrityTests(unittest.TestCase):
    """SIMULATED: mission identity coherence, checkpoint normalization/integrity, context integrity, safety independence."""

    def _make_queue(self):
        q = TaskQueue.__new__(TaskQueue)
        q._tasks = {}
        q._queue = []
        q._lock = __import__("threading").RLock()
        q._persist = lambda: None
        q._load = lambda: None
        q._task_payload = TaskQueue._task_payload
        # methods used
        return q

    def test_resume_preserves_same_mission_id_and_proof_binding(self):
        # SIMULATED (queue logic) + REAL proof object/signature context: resume must keep canonical mission identity.
        q = TaskQueue()
        q._persist = lambda: None
        v = _verifier()
        with tempfile.TemporaryDirectory() as td:
            prev_id = "mid12345"
            proof = v.inspect(td, mission_id=prev_id)
            hc = _stable_handoff(prev_id)
            import time
            prev = Task(priority=2, created_at=time.time(), task_id=prev_id, goal="g",
                        status=TaskStatus.INTERRUPTED,
                        workspace_verification_required=True,
                        continuity_workspace_root=td,
                        continuity_workspace_proof=proof,
                        handoff_summary=hc.to_dict(),
                        action_history=[{"status": "completed"}],
                        continuity_mission_id=prev_id)
            q._tasks[prev_id] = prev
            import niang_ia.model_orchestrator.workspace_verification as wv
            real_auth = wv.authorize_risky_resume_or_write
            try:
                wv.authorize_risky_resume_or_write = lambda **kw: real_auth(**{**kw, "verifier": v})
                new_id = q.resume_interrupted(prev_id, user_confirmed=True, workspace_proof=proof, workspace_root=td)
            finally:
                wv.authorize_risky_resume_or_write = real_auth
            self.assertEqual(new_id, prev_id)
            resumed = q._tasks[prev_id]
            self.assertEqual(resumed.continuity_mission_id, prev_id)
            pmid = getattr(resumed.continuity_workspace_proof, "mission_id", None)
            self.assertEqual(pmid, prev_id)
            # Previous task preserved in history archive
            archived = [k for k in q._tasks.keys() if k.startswith(prev_id + "__hist__")]
            self.assertTrue(archived, "previous mission history should be preserved")

    def test_resume_with_different_or_mismatched_mission_proof_refused(self):
        q = TaskQueue()
        q._persist = lambda: None
        v = _verifier()
        with tempfile.TemporaryDirectory() as td:
            prev_id = "midAAA"
            proof_other = v.inspect(td, mission_id="other-mission")
            import time
            prev = Task(priority=2, created_at=time.time(), task_id=prev_id, goal="g",
                        status=TaskStatus.INTERRUPTED,
                        workspace_verification_required=True,
                        continuity_workspace_root=td,
                        handoff_summary=_stable_handoff(prev_id).to_dict(),
                        action_history=[{"status": "completed"}],
                        continuity_mission_id=prev_id)
            q._tasks[prev_id] = prev
            import niang_ia.model_orchestrator.workspace_verification as wv
            real_auth = wv.authorize_risky_resume_or_write
            try:
                wv.authorize_risky_resume_or_write = lambda **kw: real_auth(**{**kw, "verifier": v})
                with self.assertRaises(ValueError):
                    q.resume_interrupted(prev_id, user_confirmed=True, workspace_proof=proof_other, workspace_root=td)
            finally:
                wv.authorize_risky_resume_or_write = real_auth

    def test_resume_refused_without_proof_when_required(self):
        q = TaskQueue()
        q._persist = lambda: None
        import time
        prev_id = "midNOP"
        prev = Task(priority=2, created_at=time.time(), task_id=prev_id, goal="g",
                    status=TaskStatus.INTERRUPTED,
                    workspace_verification_required=True,
                    handoff_summary=_stable_handoff(prev_id).to_dict(),
                    action_history=[{"status": "completed"}],
                    continuity_mission_id=prev_id)
        q._tasks[prev_id] = prev
        with self.assertRaises(ValueError):
            q.resume_interrupted(prev_id, user_confirmed=True, workspace_proof=None, workspace_root=None)

    def test_historical_unprotected_mission_resume_behavior_preserved(self):
        # Historical mission not marked protected, no uncertain actions -> verification not forced.
        q = TaskQueue()
        q._persist = lambda: None
        import time
        prev_id = "hist1"
        prev = Task(priority=2, created_at=time.time(), task_id=prev_id, goal="g",
                    status=TaskStatus.INTERRUPTED,
                    workspace_verification_required=False,
                    handoff_summary={},
                    last_checkpoint={},
                    action_history=[{"status": "completed"}])
        q._tasks[prev_id] = prev
        new_id = q.resume_interrupted(prev_id, user_confirmed=True)
        self.assertEqual(new_id, prev_id)
        resumed = q._tasks[prev_id]
        self.assertFalse(resumed.workspace_verification_required)

    def test_checkpoint_malformed_invalid_or_mismatched_rejected_for_protected(self):
        from niang_ia.model_orchestrator import continuity_guard as cg
        from niang_ia.model_orchestrator.workspace_verification import validate_proof
        v = _verifier()
        with tempfile.TemporaryDirectory() as td:
            proof = v.inspect(td, mission_id="m1")
            real_auth = cg.authorize_risky_resume_or_write
            cg.authorize_risky_resume_or_write = lambda **kw: __import__("niang_ia.model_orchestrator.workspace_verification", fromlist=["authorize_risky_resume_or_write"]).authorize_risky_resume_or_write(**{**kw, "verifier": v})
            try:
                # malformed / missing identity
                ctx = ContinuityExecutionContext(mission_id="m1", workspace_root=td, workspace_proof=proof,
                    workspace_verification_required=True, continuity_state="recovery_verified",
                    checkpoint={"weird": 1}, action_history=({"status": "completed"},), last_operation_uncertain=False)
                allowed, issues = evaluate_continuity_guard(ctx, tool="workspace_write_file", parameters={"path":"a.txt","content":"x"})
                self.assertFalse(allowed)
                self.assertTrue(any("checkpoint_invalid" in i or "checkpoint" in i for i in issues))
                # checkpoint from another mission
                ctx2 = ContinuityExecutionContext(mission_id="m1", workspace_root=td, workspace_proof=proof,
                    workspace_verification_required=True, continuity_state="recovery_verified",
                    checkpoint=_stable_handoff("other").to_dict(), action_history=({"status": "completed"},), last_operation_uncertain=False)
                allowed2, issues2 = evaluate_continuity_guard(ctx2, tool="workspace_write_file", parameters={"path":"a.txt","content":"x"})
                self.assertFalse(allowed2)
                self.assertIn("checkpoint_mission_mismatch", issues2)
            finally:
                cg.authorize_risky_resume_or_write = real_auth

    def test_checkpoint_with_unknown_action_rejected(self):
        from niang_ia.model_orchestrator import continuity_guard as cg
        v = _verifier()
        with tempfile.TemporaryDirectory() as td:
            proof = v.inspect(td, mission_id="m1")
            hc = build_handoff_context(mission_id="m1", objective="o", actions_completed=[{"id":"1","status":"unknown","side_effects_possible":True}])
            ctx = ContinuityExecutionContext(mission_id="m1", workspace_root=td, workspace_proof=proof,
                workspace_verification_required=True, continuity_state="recovery_verified",
                checkpoint=hc.to_dict(), action_history=({"status": "completed"},), last_operation_uncertain=False)
            real_auth = cg.authorize_risky_resume_or_write
            cg.authorize_risky_resume_or_write = lambda **kw: __import__("niang_ia.model_orchestrator.workspace_verification", fromlist=["authorize_risky_resume_or_write"]).authorize_risky_resume_or_write(**{**kw, "verifier": v})
            try:
                allowed, issues = evaluate_continuity_guard(ctx, tool="workspace_write_file", parameters={"path":"a.txt","content":"x"})
            finally:
                cg.authorize_risky_resume_or_write = real_auth
            self.assertFalse(allowed)

    def test_context_is_immutable_against_internal_modification(self):
        # SIMULATED: frozen context prevents in-place field mutation by incorrect caller.
        ctx = ContinuityExecutionContext(mission_id="m1", workspace_verification_required=True)
        with self.assertRaises(Exception):
            ctx.mission_id = "other"  # type: ignore[misc]
        with self.assertRaises(Exception):
            ctx.workspace_verification_required = False  # type: ignore[misc]
        with self.assertRaises(Exception):
            ctx.last_operation_uncertain = False  # type: ignore[misc]

    def test_safety_approval_refused_independent(self):
        with mock.patch("safety.needs_confirmation", return_value=True), \
             mock.patch("safety.describe", return_value="danger"), \
             mock.patch("safety.issue_confirmation_token", return_value="tok"):
            out = _call_tool("workspace_write_file", {"path": "a.txt", "content": "x"}, speak=None,
                             approval_callback=lambda t,p,d: False, continuity_context=None)
        self.assertIn("Blocked for safety", out)


class Phase8A31RealWorkspaceTests(unittest.TestCase):
    """REAL: temp workspace filesystem effects for resume identity, write after verified resume context, and drift refusal."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        self.v = _verifier()

    def tearDown(self):
        self.td.cleanup()

    def _auth_patch(self):
        import niang_ia.model_orchestrator.workspace_verification as wv
        return lambda **kw: wv.authorize_risky_resume_or_write(**{**kw, "verifier": self.v})

    def test_real_resume_same_mission_id_and_controlled_write_after_resume(self):
        # REAL: valid signed proof bound to mission id, resume preserves identity, then controlled write succeeds.
        q = TaskQueue()
        q._persist = lambda: None
        import time
        prev_id = "mreal1"
        proof = self.v.inspect(self.root, mission_id=prev_id)
        hc = _stable_handoff(prev_id)
        prev = Task(priority=2, created_at=time.time(), task_id=prev_id, goal="g",
                    status=TaskStatus.INTERRUPTED,
                    workspace_verification_required=True,
                    continuity_workspace_root=str(self.root),
                    continuity_workspace_proof=proof,
                    handoff_summary=hc.to_dict(),
                    action_history=[{"status": "completed"}],
                    continuity_mission_id=prev_id)
        q._tasks[prev_id] = prev
        import niang_ia.model_orchestrator.workspace_verification as wv
        from niang_ia.model_orchestrator import continuity_guard as cg
        real_wv_auth = wv.authorize_risky_resume_or_write
        real_cg_auth = cg.authorize_risky_resume_or_write
        real_cg_val = cg.validate_proof
        try:
            wv.authorize_risky_resume_or_write = lambda **kw: real_wv_auth(**{**kw, "verifier": self.v})
            new_id = q.resume_interrupted(prev_id, user_confirmed=True, workspace_proof=proof, workspace_root=str(self.root))
            self.assertEqual(new_id, prev_id)
            t = q._tasks[prev_id]
            # re-inspect for fresh proof state valid at write time (no blind reuse of stale proof semantics)
            fresh = self.v.inspect(self.root, mission_id=prev_id)
            ctx = ContinuityExecutionContext(
                mission_id=(t.continuity_mission_id or t.task_id),
                workspace_root=str(self.root),
                workspace_proof=fresh,
                checkpoint=t.handoff_summary or {},
                workspace_verification_required=True,
                continuity_state="recovery_verified",
                execution_attempt_id=t.execution_attempt_id or "a1",
                last_operation_uncertain=False,
                action_history=tuple(dict(x) for x in (t.action_history or [])),
            )
            cg.authorize_risky_resume_or_write = lambda **kw: real_cg_auth(**{**kw, "verifier": self.v})
            cg.validate_proof = lambda p, **kw: real_cg_val(p, **{**kw, "verifier": self.v})
            with mock.patch("safety.needs_confirmation", return_value=False), \
                 mock.patch.dict(os.environ, {"NIANG_IA_WORKSPACE_ROOT": str(self.root)}):
                out = _call_tool("workspace_write_file", {"path": "resumed.txt", "content": "ok"}, speak=None, continuity_context=ctx)
            self.assertNotIn("Blocked for continuity safety", out)
            self.assertTrue((self.root / "resumed.txt").exists())
            self.assertEqual((self.root / "resumed.txt").read_text(encoding="utf-8"), "ok")
        finally:
            wv.authorize_risky_resume_or_write = real_wv_auth
            cg.authorize_risky_resume_or_write = real_cg_auth
            cg.validate_proof = real_cg_val

    def test_real_workspace_modified_after_interruption_blocks_write(self):
        import time
        prev_id = "mdrift"
        proof = self.v.inspect(self.root, mission_id=prev_id)
        (self.root / "drift.txt").write_text("changed", encoding="utf-8")
        # proof now stale vs modified workspace
        from niang_ia.model_orchestrator import continuity_guard as cg
        real_cg_auth = cg.authorize_risky_resume_or_write
        real_cg_val = cg.validate_proof
        try:
            cg.authorize_risky_resume_or_write = lambda **kw: real_cg_auth(**{**kw, "verifier": self.v})
            cg.validate_proof = lambda p, **kw: real_cg_val(p, **{**kw, "verifier": self.v})
            ctx = ContinuityExecutionContext(
                mission_id=prev_id, workspace_root=str(self.root), workspace_proof=proof,
                workspace_verification_required=True, continuity_state="recovery_verified",
                checkpoint=_stable_handoff(prev_id).to_dict(),
                action_history=({"status": "completed"},), last_operation_uncertain=False,
            )
            with mock.patch("safety.needs_confirmation", return_value=False), \
                 mock.patch.dict(os.environ, {"NIANG_IA_WORKSPACE_ROOT": str(self.root)}):
                out = _call_tool("workspace_write_file", {"path": "blocked.txt", "content": "x"}, speak=None, continuity_context=ctx)
            self.assertIn("Blocked for continuity safety", out)
            self.assertFalse((self.root / "blocked.txt").exists())
        finally:
            cg.authorize_risky_resume_or_write = real_cg_auth
            cg.validate_proof = real_cg_val

    def test_real_invalid_checkpoint_blocks_controlled_write(self):
        fresh = self.v.inspect(self.root, mission_id="mcp")
        from niang_ia.model_orchestrator import continuity_guard as cg
        real_cg_auth = cg.authorize_risky_resume_or_write
        try:
            cg.authorize_risky_resume_or_write = lambda **kw: __import__("niang_ia.model_orchestrator.workspace_verification", fromlist=["authorize_risky_resume_or_write"]).authorize_risky_resume_or_write(**{**kw, "verifier": self.v})
            ctx = ContinuityExecutionContext(
                mission_id="mcp", workspace_root=str(self.root), workspace_proof=fresh,
                workspace_verification_required=True, continuity_state="recovery_verified",
                checkpoint={"actions_completed": "bad"},  # malformed
                action_history=({"status": "completed"},), last_operation_uncertain=False,
            )
            with mock.patch("safety.needs_confirmation", return_value=False), \
                 mock.patch.dict(os.environ, {"NIANG_IA_WORKSPACE_ROOT": str(self.root)}):
                out = _call_tool("workspace_write_file", {"path": "nope.txt", "content": "x"}, speak=None, continuity_context=ctx)
            self.assertIn("Blocked for continuity safety", out)
            self.assertFalse((self.root / "nope.txt").exists())
        finally:
            cg.authorize_risky_resume_or_write = real_cg_auth


if __name__ == "__main__":
    unittest.main()

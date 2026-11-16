from __future__ import annotations

import unittest

from niang_ia.model_orchestrator.continuity import (
    assess_resume_safety,
    build_handoff_context,
    has_uncertain_or_unverified_actions,
    validate_handoff_for_resume,
)
from niang_ia.model_orchestrator.models import HandoffContext, IncidentKind, ResumeCheckpoint
from niang_ia.model_orchestrator.taxonomy import classify_incident


class ContinuityResumeSafetyPhase7Tests(unittest.TestCase):
    def test_handoff_requires_explicit_workspace_verification(self):
        handoff = build_handoff_context(
            mission_id="m1",
            objective="do thing",
            actions_completed=[{"id": "a1", "status": "completed", "side_effects_possible": True}],
            approvals_state={"approved": True},
            next_step="continue",
        )
        ok, issues = assess_resume_safety(handoff, workspace_verified=False)
        self.assertFalse(ok)
        self.assertIn("workspace_verification_required_but_not_confirmed", issues)

    def test_resume_denied_without_evidence_even_if_verified_flag_true(self):
        handoff = build_handoff_context(mission_id="m1", objective="obj")
        ok, issues = assess_resume_safety(handoff, workspace_verified=True, verification_evidence="")
        self.assertFalse(ok)
        self.assertIn("workspace_verification_evidence_missing", issues)

    def test_uncertain_or_in_progress_actions_never_replayable(self):
        handoff = build_handoff_context(
            mission_id="m2",
            objective="obj",
            actions_completed=[
                {"id": "s1", "status": "in_progress", "side_effects_possible": True},
                {"id": "s2", "status": "unknown", "side_effects_possible": False},
            ],
        )
        self.assertTrue(has_uncertain_or_unverified_actions(handoff))
        for cp in handoff.checkpoints:
            self.assertFalse(cp.replay_allowed)
            self.assertTrue(cp.workspace_verification_required)
        ok, issues = validate_handoff_for_resume(handoff)
        self.assertTrue(ok, issues)

    def test_resume_allowed_only_with_explicit_verification_and_evidence(self):
        handoff = build_handoff_context(
            mission_id="m3",
            objective="obj",
            actions_completed=[{"id": "s1", "status": "completed", "side_effects_possible": True}],
        )
        # completed but side-effectful => treated as requiring verified state, replay remains forbidden
        self.assertTrue(has_uncertain_or_unverified_actions(handoff))
        for cp in handoff.checkpoints:
            self.assertFalse(cp.replay_allowed)
        ok, issues = assess_resume_safety(
            handoff,
            workspace_verified=True,
            verification_evidence="workspace listing and outputs checked",
        )
        self.assertTrue(ok, issues)

    def test_handoff_preserves_mission_identity_history_and_approvals(self):
        handoff = build_handoff_context(
            mission_id="mission-123",
            objective="continue mission",
            mission_history_summary="planned and partially executed",
            approvals_state={"sensitive": "granted_once"},
            source_model="gemini:gemini-2.5-flash",
            target_model="ollama:qwen2.5:7b",
            next_step="verify_workspace_state_before_any_write",
        )
        self.assertEqual(handoff.mission_id, "mission-123")
        self.assertEqual(handoff.approvals_state.get("sensitive"), "granted_once")
        self.assertEqual(handoff.source_model, "gemini:gemini-2.5-flash")
        self.assertTrue(handoff.workspace_verification_required)

    def test_no_failover_on_code_mission_error_classification(self):
        c = classify_incident(mission_or_code_error=True)
        self.assertEqual(c.kind, IncidentKind.ERREUR_CODE_MISSION)
        self.assertFalse(c.failover_candidate)


class TaskQueueContinuityHelpersPhase7Tests(unittest.TestCase):
    def test_mark_and_record_handoff_helpers(self):
        from agent.task_queue import Task, TaskQueue

        q = TaskQueue(persist=False)
        t = Task(priority=1, created_at=1.0, task_id="t7", goal="g")
        q._tasks["t7"] = t
        q.mark_workspace_verification_required("t7", True, checkpoint={"step": "s1"})
        self.assertTrue(q._tasks["t7"].workspace_verification_required)
        self.assertEqual(q._tasks["t7"].last_checkpoint.get("step"), "s1")
        q.record_failover_handoff("t7", handoff={"mission_id": "t7"}, failover_event={"incident": "timeout"})
        self.assertTrue(q._tasks["t7"].workspace_verification_required)
        self.assertEqual(q._tasks["t7"].handoff_summary.get("mission_id"), "t7")
        self.assertEqual(q._tasks["t7"].failover_history[-1]["incident"], "timeout")


if __name__ == "__main__":
    unittest.main()

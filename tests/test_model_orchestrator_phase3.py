from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from niang_ia.model_orchestrator.config import OrchestratorConfig
from niang_ia.model_orchestrator.continuity import build_handoff_context, validate_handoff_for_resume
from niang_ia.model_orchestrator.failover import plan_failover
from niang_ia.model_orchestrator.metrics_store import MetricsEventStore
from niang_ia.model_orchestrator.models import (
    AttemptRecord,
    CapabilitySet,
    CooldownState,
    FailoverAction,
    IncidentKind,
    MeasurementOrigin,
    MissionProfile,
    ModelCapabilities,
    ModelRecord,
    ProviderKind,
)
from niang_ia.model_orchestrator.scoring import select_best_candidate
from niang_ia.model_orchestrator.taxonomy import classify_incident


def mk_record(provider, model, *, available=True, quota="ok", kind=ProviderKind.LOCAL, supports_cline=False, cline_verified=False,
              reasoning=False, coding=False, tool_calling=False, ctx=8192, latency="medium", until=None):
    return ModelRecord(
        capabilities=ModelCapabilities(
            provider_id=provider,
            model_id=model,
            display_name=model,
            kind=kind,
            capabilities=CapabilitySet(
                reasoning=reasoning, coding=coding, tool_calling=tool_calling,
                max_context_tokens=ctx, latency_tier=latency,
            ),
            supports_general=True,
            supports_cline=supports_cline,
            cline_tool_calling_verified=cline_verified,
            verified=True,
        ),
        available=available,
        quota_state=quota,
        temporarily_unavailable_until=until,
    )


class ScoringPhase3Tests(unittest.TestCase):
    def test_selects_best_compatible_not_first(self):
        candidates = [
            mk_record("p", "weak", coding=False, tool_calling=False),
            mk_record("p", "strong", coding=True, tool_calling=True, reasoning=True),
        ]
        profile = MissionProfile(needs_coding=True, needs_tool_calling=True, needs_reasoning=True)
        best, score, reasons = select_best_candidate(candidates, profile)
        self.assertIsNotNone(best)
        assert best is not None
        self.assertEqual(best.capabilities.model_id, "strong")
        self.assertGreater(score, 0)

    def test_excludes_paid_without_explicit_authorization(self):
        candidates = [mk_record("paidp", "paid-model", kind=ProviderKind.PAID, coding=True, tool_calling=True)]
        profile = MissionProfile(needs_coding=True)
        best, _, reasons = select_best_candidate(candidates, profile, allow_paid=False, config_paid_ok={"paidp": True})
        self.assertIsNone(best)
        self.assertIn("no_eligible_candidate", reasons)

    def test_cline_engine_requires_verified_cline_compatible_model(self):
        candidates = [
            mk_record("p", "general", coding=True, tool_calling=True, supports_cline=False),
            mk_record("p", "cline-ok", coding=True, tool_calling=True, supports_cline=True, cline_verified=True),
        ]
        profile = MissionProfile(engine="cline", needs_coding=True, needs_tool_calling=True)
        best, _, _ = select_best_candidate(candidates, profile)
        self.assertIsNotNone(best)
        assert best is not None
        self.assertEqual(best.capabilities.model_id, "cline-ok")


class FailoverPhase3Tests(unittest.TestCase):
    def _plan(self, incident_kind, *, current=("a", "m1"), candidates=None, attempts=None, profile=None, cooldowns=None, step_state="unknown", handoff_base=None, cfg=None):
        classification = classify_incident(
            quota_exhausted=(incident_kind == IncidentKind.QUOTA_EPUISE),
            rate_limited=(incident_kind == IncidentKind.RATE_LIMIT_TEMPORAIRE),
            provider_unavailable=(incident_kind == IncidentKind.PANNE_FOURNISSEUR),
            timeout=(incident_kind == IncidentKind.TIMEOUT),
            tool_calling_error=(incident_kind == IncidentKind.ERREUR_TOOL_CALLING),
            mission_or_code_error=(incident_kind == IncidentKind.ERREUR_CODE_MISSION),
        )
        if incident_kind == IncidentKind.RATE_LIMIT_TEMPORAIRE:
            classification = classify_incident(status_code=429, error_text="too many requests")
        return plan_failover(
            classification=classification,
            profile=profile or MissionProfile(mission_id="M1", needs_coding=True),
            current_provider=current[0], current_model=current[1],
            candidates=candidates or [],
            attempts=attempts or [],
            cooldowns=cooldowns or {},
            config=cfg or OrchestratorConfig.defaults(),
            now=1000.0,
            handoff_base=handoff_base or {"mission_id": "M1", "objective": "obj", "approvals_state": {"a": "ok"}},
            current_step_state=step_state,
        )

    def test_code_or_mission_error_never_switches(self):
        plan = self._plan(IncidentKind.ERREUR_CODE_MISSION, candidates=[mk_record("b", "m2", coding=True)])
        self.assertEqual(plan.action, FailoverAction.NO_SWITCH)
        self.assertFalse(plan.requires_handoff)

    def test_quota_exhausted_switches_to_best_fallback_with_handoff(self):
        candidates = [mk_record("b", "weak", coding=False), mk_record("c", "best", coding=True, tool_calling=True)]
        plan = self._plan(IncidentKind.QUOTA_EPUISE, candidates=candidates)
        self.assertIn(plan.action, {FailoverAction.COOLDOWN_AND_SWITCH, FailoverAction.SWITCH})
        self.assertEqual(plan.to_model, "best")
        self.assertTrue(plan.requires_handoff)
        self.assertIsNotNone(plan.handoff)
        assert plan.handoff is not None
        self.assertEqual(plan.handoff.mission_id, "M1")
        self.assertEqual(plan.handoff.approvals_state.get("a"), "ok")
        self.assertTrue(plan.handoff.uncertain_actions_must_not_be_replayed)
        self.assertTrue(plan.handoff.workspace_verification_required)

    def test_rate_limit_can_backoff_then_switch(self):
        candidates = [mk_record("b", "m2", coding=True)]
        # safe completed step allows one bounded retry same model
        plan_retry = self._plan(IncidentKind.RATE_LIMIT_TEMPORAIRE, candidates=candidates, step_state="completed")
        self.assertEqual(plan_retry.action, FailoverAction.RETRY_WITH_BACKOFF)
        self.assertGreater(plan_retry.delay_seconds, 0)
        # after same-model attempt, should switch
        attempts = [AttemptRecord("M1", "a", "m1", IncidentKind.RATE_LIMIT_TEMPORAIRE, "retry_with_backoff", 999.0)]
        plan_switch = self._plan(IncidentKind.RATE_LIMIT_TEMPORAIRE, candidates=candidates, attempts=attempts, step_state="completed")
        self.assertIn(plan_switch.action, {FailoverAction.COOLDOWN_AND_SWITCH, FailoverAction.SWITCH})

    def test_timeout_and_5xx_produce_safe_plan(self):
        candidates = [mk_record("b", "m2", coding=True)]
        plan_to = self._plan(IncidentKind.TIMEOUT, candidates=candidates, step_state="unknown")
        self.assertIn(plan_to.action, {FailoverAction.COOLDOWN_AND_SWITCH, FailoverAction.SWITCH, FailoverAction.RETRY_WITH_BACKOFF})
        plan_5 = self._plan(IncidentKind.PANNE_FOURNISSEUR, candidates=candidates, step_state="unknown")
        self.assertIn(plan_5.action, {FailoverAction.COOLDOWN_AND_SWITCH, FailoverAction.SWITCH, FailoverAction.RETRY_WITH_BACKOFF})

    def test_tool_calling_error_switches_to_compatible_fallback(self):
        candidates = [mk_record("b", "m2", coding=True, tool_calling=True)]
        plan = self._plan(IncidentKind.ERREUR_TOOL_CALLING, candidates=candidates)
        self.assertIn(plan.action, {FailoverAction.COOLDOWN_AND_SWITCH, FailoverAction.SWITCH})
        self.assertEqual(plan.to_model, "m2")

    def test_secondary_unavailable_and_all_unavailable(self):
        # secondary on cooldown/unavailable
        candidates = [mk_record("b", "m2", available=False, coding=True), mk_record("c", "m3", coding=True, until=2000.0)]
        plan = self._plan(IncidentKind.QUOTA_EPUISE, candidates=candidates)
        self.assertEqual(plan.action, FailoverAction.ABORT)
        self.assertTrue(plan.exhausted)
        # none at all
        plan2 = self._plan(IncidentKind.PANNE_FOURNISSEUR, candidates=[])
        self.assertEqual(plan2.action, FailoverAction.ABORT)
        self.assertTrue(plan2.exhausted)

    def test_anti_loop_budget(self):
        cfg = OrchestratorConfig.from_dict({"failover_max_attempts": 1})
        attempts = [AttemptRecord("M1", "a", "m1", IncidentKind.TIMEOUT, "retry_with_backoff", 900.0)]
        plan = self._plan(IncidentKind.TIMEOUT, candidates=[mk_record("b", "m2", coding=True)], attempts=attempts, cfg=cfg)
        self.assertEqual(plan.action, FailoverAction.ABORT)
        self.assertEqual(plan.reason, "failover_budget_exhausted")

    def test_handoff_preserves_critical_context_and_forbids_uncertain_replay(self):
        actions = [
            {"id": "1", "description": "read", "status": "completed"},
            {"id": "2", "description": "write", "status": "in_progress", "side_effects_possible": True},
            {"id": "3", "description": "patch", "status": "unknown"},
        ]
        plan = self._plan(
            IncidentKind.PANNE_FOURNISSEUR,
            candidates=[mk_record("b", "m2", coding=True)],
            handoff_base={
                "mission_id": "M1", "objective": "goal",
                "actions_completed": actions,
                "files_created_or_modified": ["x.py"],
                "tool_results": [{"tool": "t", "ok": True}],
                "errors_encountered": [{"e": "boom"}],
                "approvals_state": {"write": "approved"},
                "next_step": "verify then continue",
            },
        )
        self.assertIsNotNone(plan.handoff)
        assert plan.handoff is not None
        ok, issues = validate_handoff_for_resume(plan.handoff)
        self.assertTrue(ok, issues)
        self.assertEqual(plan.handoff.files_created_or_modified, ["x.py"])
        self.assertEqual(plan.handoff.approvals_state["write"], "approved")
        self.assertEqual(len(plan.handoff.checkpoints), 3)
        for cp in plan.handoff.checkpoints:
            self.assertFalse(cp.replay_allowed)
            self.assertTrue(cp.workspace_verification_required)

    def test_metrics_origin_separation_for_measured_scoring(self):
        candidates = [mk_record("p", "a", coding=True), mk_record("p", "b", coding=True)]
        profile = MissionProfile(needs_coding=True)
        history = [
            {"provider_id": "p", "model_id": "b", "origin": "reel", "success": True},
            {"provider_id": "p", "model_id": "b", "origin": "reel", "success": True},
            {"provider_id": "p", "model_id": "a", "origin": "simule", "success": True},
        ]
        best_real, _, _ = select_best_candidate(candidates, profile, measured_history=history, measured_origin=MeasurementOrigin.REEL)
        self.assertIsNotNone(best_real)
        assert best_real is not None
        self.assertEqual(best_real.capabilities.model_id, "b")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from niang_ia.model_orchestrator.config import OrchestratorConfig, load_orchestrator_config
from niang_ia.model_orchestrator.metrics_store import MetricsEventStore
from niang_ia.model_orchestrator.models import HandoffContext, IncidentKind, MeasurementOrigin, ResumeCheckpoint
from niang_ia.model_orchestrator.registry import ModelRegistry
from niang_ia.model_orchestrator.taxonomy import classify_incident, should_failover


class OrchestratorPhase1ConfigTests(unittest.TestCase):
    def test_defaults_are_safe_and_auto(self):
        cfg = OrchestratorConfig.defaults()
        self.assertEqual(cfg.mode, "auto")
        self.assertFalse(cfg.paid_usage_allowed)
        self.assertFalse(cfg.provider_can_spend("anything"))

    def test_load_missing_file_returns_safe_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = load_orchestrator_config(Path(td) / "missing.json")
        self.assertEqual(cfg.mode, "auto")
        self.assertFalse(cfg.paid_usage_allowed)

    def test_load_invalid_json_returns_safe_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text("{not-json", encoding="utf-8")
            cfg = load_orchestrator_config(path)
        self.assertEqual(cfg.mode, "auto")
        self.assertFalse(cfg.paid_usage_allowed)

    def test_paid_provider_requires_explicit_global_and_provider_authorization(self):
        cfg = OrchestratorConfig.from_dict({
            "paid_usage_allowed": False,
            "providers": {"deepseek": {"enabled": True, "kind": "paid", "paid_allowed": True, "models": []}},
        })
        self.assertFalse(cfg.provider_can_spend("deepseek"))
        cfg2 = OrchestratorConfig.from_dict({
            "paid_usage_allowed": True,
            "providers": {"deepseek": {"enabled": True, "kind": "paid", "paid_allowed": True, "models": []}},
        })
        self.assertTrue(cfg2.provider_can_spend("deepseek"))
        cfg3 = OrchestratorConfig.from_dict({
            "paid_usage_allowed": True,
            "providers": {"deepseek": {"enabled": True, "kind": "paid", "paid_allowed": False, "models": []}},
        })
        self.assertFalse(cfg3.provider_can_spend("deepseek"))


class OrchestratorPhase1TaxonomyTests(unittest.TestCase):
    def test_distinguishes_required_incident_kinds(self):
        self.assertEqual(classify_incident(quota_exhausted=True).kind, IncidentKind.QUOTA_EPUISE)
        self.assertEqual(classify_incident(status_code=429).kind, IncidentKind.RATE_LIMIT_TEMPORAIRE)
        self.assertEqual(classify_incident(status_code=503).kind, IncidentKind.PANNE_FOURNISSEUR)
        self.assertEqual(classify_incident(timeout=True).kind, IncidentKind.TIMEOUT)
        self.assertEqual(classify_incident(tool_calling_error=True).kind, IncidentKind.ERREUR_TOOL_CALLING)
        self.assertEqual(classify_incident(mission_or_code_error=True).kind, IncidentKind.ERREUR_CODE_MISSION)

    def test_code_or_mission_error_never_triggers_failover(self):
        c = classify_incident(mission_or_code_error=True)
        self.assertEqual(c.kind, IncidentKind.ERREUR_CODE_MISSION)
        self.assertFalse(c.failover_candidate)
        self.assertFalse(should_failover(c.kind))
        self.assertFalse(should_failover(IncidentKind.ERREUR_CODE_MISSION))

    def test_failover_candidates_for_infra_and_model_compatibility_issues(self):
        for kind in [
            IncidentKind.QUOTA_EPUISE,
            IncidentKind.RATE_LIMIT_TEMPORAIRE,
            IncidentKind.PANNE_FOURNISSEUR,
            IncidentKind.TIMEOUT,
            IncidentKind.ERREUR_TOOL_CALLING,
        ]:
            self.assertTrue(should_failover(kind))

    def test_unclassified_defaults_to_no_failover(self):
        c = classify_incident(error_text="something unexpected happened")
        self.assertEqual(c.kind, IncidentKind.ERREUR_CODE_MISSION)
        self.assertFalse(c.failover_candidate)


class OrchestratorPhase1StoreTests(unittest.TestCase):
    def test_metrics_and_events_store_separates_simulated_and_real(self):
        with tempfile.TemporaryDirectory() as td:
            store = MetricsEventStore(Path(td) / "metrics.db")
            store.record_metric("ollama", "qwen2.5:7b", "simule", {"success": True, "latency_ms": 120})
            store.record_metric("ollama", "qwen2.5:7b", "reel", {"success": True, "latency_ms": 900})
            store.record_event("failover", "simule", {"from": "a", "to": "b"})
            sim = store.list_metrics(origin="simule")
            real = store.list_metrics(origin="reel")
            self.assertEqual(len(sim), 1)
            self.assertEqual(len(real), 1)
            self.assertEqual(sim[0]["payload"]["latency_ms"], 120)
            self.assertEqual(real[0]["payload"]["latency_ms"], 900)
            ev = store.list_events(origin="simule")
            self.assertEqual(len(ev), 1)
            self.assertEqual(ev[0]["event_type"], "failover")

    def test_origin_validation(self):
        with tempfile.TemporaryDirectory() as td:
            store = MetricsEventStore(Path(td) / "metrics.db")
            with self.assertRaises(ValueError):
                store.record_metric("p", "m", "unknown", {})


class OrchestratorPhase1ModelTests(unittest.TestCase):
    def test_handoff_context_marks_uncertain_actions_and_verification(self):
        cp = ResumeCheckpoint(step_id="s1", description="write file", status="unknown", replay_allowed=False)
        handoff = HandoffContext(
            mission_id="m1",
            objective="do thing",
            next_step="verify workspace state",
            checkpoints=[cp],
            approvals_state={"step_1": "approved"},
            files_created_or_modified=["a.py"],
        )
        data = handoff.to_dict()
        self.assertTrue(data["uncertain_actions_must_not_be_replayed"])
        self.assertTrue(data["workspace_verification_required"])
        self.assertEqual(data["checkpoints"][0]["status"], "unknown")
        self.assertFalse(data["checkpoints"][0]["replay_allowed"])

    def test_registry_from_config_filters_cline_support(self):
        # Phase 6+ safety: Cline-eligible models must be explicitly verified for tool-calling.
        cfg = OrchestratorConfig.from_dict({
            "providers": {
                "ollama": {"enabled": True, "kind": "local", "models": [
                    {"model_id": "qwen2.5:7b", "supports_cline": True, "cline_tool_calling_verified": True, "tool_calling": True},
                    {"model_id": "llama3", "supports_cline": False},
                    {"model_id": "unverified", "supports_cline": True, "cline_tool_calling_verified": False, "tool_calling": True},
                ]}
            }
        })
        reg = ModelRegistry.from_config(cfg)
        cline_models = reg.list_available(engine="cline")
        self.assertEqual([r.capabilities.model_id for r in cline_models], ["qwen2.5:7b"])


if __name__ == "__main__":
    unittest.main()

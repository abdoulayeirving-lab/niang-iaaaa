from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from niang_ia.model_orchestrator.config import OrchestratorConfig
from niang_ia.model_orchestrator.instrumentation import record_classified_error, record_routing_decision
from niang_ia.model_orchestrator.metrics_store import MetricsEventStore
from niang_ia.model_orchestrator.models import IncidentKind, MeasurementOrigin, MissionProfile
from niang_ia.model_orchestrator.orchestrator import ModelOrchestrator
from niang_ia.model_orchestrator.providers.gemini import GeminiAdapter


class GeminiAdapterPhase2Tests(unittest.TestCase):
    def test_selects_best_match_not_first_for_coding_mission(self):
        cfg = OrchestratorConfig.defaults()
        with mock.patch("api_keys.get_all_keys", return_value=["k1"]):
            adapter = GeminiAdapter(cfg)
            # Provide candidates where a later model is better for coding
            adapter._configured_models = lambda: [  # type: ignore[assignment]
                {"model_id": "lite", "display_name": "Lite", "reasoning": False, "coding": False, "tool_calling": False, "latency_tier": "low"},
                {"model_id": "code", "display_name": "Code", "reasoning": True, "coding": True, "tool_calling": True, "latency_tier": "medium"},
            ]
            profile = MissionProfile(needs_coding=True, needs_reasoning=True, needs_tool_calling=True)
            decision = adapter.select_model(profile)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.selected_model, "code")
        self.assertIn("best_match_single_provider_gemini", decision.reason)

    def test_selects_fast_model_when_latency_preferred(self):
        cfg = OrchestratorConfig.defaults()
        with mock.patch("api_keys.get_all_keys", return_value=["k1"]):
            adapter = GeminiAdapter(cfg)
            adapter._configured_models = lambda: [  # type: ignore[assignment]
                {"model_id": "quality", "reasoning": True, "coding": True, "tool_calling": True, "latency_tier": "high"},
                {"model_id": "fast", "reasoning": False, "coding": True, "tool_calling": True, "latency_tier": "low"},
            ]
            decision = adapter.select_model(MissionProfile(needs_coding=True, preferred_latency="fast"))
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.selected_model, "fast")

    def test_no_decision_without_credentials(self):
        cfg = OrchestratorConfig.defaults()
        with mock.patch("api_keys.get_all_keys", return_value=[]):
            adapter = GeminiAdapter(cfg)
            decision = adapter.select_model(MissionProfile())
        self.assertIsNone(decision)

    def test_classifies_errors_into_required_categories(self):
        adapter = GeminiAdapter(OrchestratorConfig.defaults())
        self.assertEqual(adapter.classify_error(Exception("RESOURCE_EXHAUSTED 429"), status_code=429).kind, IncidentKind.QUOTA_EPUISE)
        self.assertEqual(adapter.classify_error(Exception("Too Many Requests"), status_code=429).kind, IncidentKind.RATE_LIMIT_TEMPORAIRE)
        self.assertEqual(adapter.classify_error(Exception("server error"), status_code=503).kind, IncidentKind.PANNE_FOURNISSEUR)
        self.assertEqual(adapter.classify_error(TimeoutError("timed out")).kind, IncidentKind.TIMEOUT)
        self.assertEqual(adapter.classify_error(Exception("tool call schema invalid"), tool_calling_error=True).kind, IncidentKind.ERREUR_TOOL_CALLING)
        c = adapter.classify_error(Exception("SyntaxError in user code"), mission_or_code_error=True)
        self.assertEqual(c.kind, IncidentKind.ERREUR_CODE_MISSION)
        self.assertFalse(c.failover_candidate)

    def test_generate_facade_delegates_to_existing_api_keys(self):
        adapter = GeminiAdapter(OrchestratorConfig.defaults())
        with mock.patch("api_keys.generate_with_retry", return_value="ok") as m:
            out = adapter.generate("gemini-test", "hello", config=None, api_version="v1", timeout_ms=1234)
        self.assertEqual(out, "ok")
        m.assert_called_once_with("gemini-test", "hello", config=None, api_version="v1", timeout_ms=1234)


class OrchestratorPhase2Tests(unittest.TestCase):
    def test_single_provider_selection_no_failover_chain_execution(self):
        cfg = OrchestratorConfig.defaults()
        with mock.patch("api_keys.get_all_keys", return_value=["k1"]):
            orch = ModelOrchestrator(cfg)
            decision = orch.select_model(MissionProfile(needs_coding=True))
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.selected_provider, "gemini")
        self.assertIsNotNone(decision.selected_model)
        # fallback_chain is informational only in Phase 2; no failover mechanism exists/executed
        self.assertIsInstance(decision.fallback_chain, list)

    def test_blocks_paid_provider_without_explicit_authorization(self):
        cfg = OrchestratorConfig.from_dict({
            "paid_usage_allowed": False,
            "providers": {
                "gemini": {"enabled": True, "kind": "paid", "paid_allowed": False, "models": [{"model_id": "gemini-2.5-flash"}]}
            }
        })
        with mock.patch("api_keys.get_all_keys", return_value=["k1"]):
            orch = ModelOrchestrator(cfg)
            # Caller intent alone is insufficient; config-level authorization is also required.
            decision = orch.select_model(MissionProfile(), allow_paid=True)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertIsNone(decision.selected_model)
        self.assertIn("paid_provider_blocked", decision.reason)

    def test_code_or_mission_error_not_failover_candidate(self):
        orch = ModelOrchestrator(OrchestratorConfig.defaults())
        classification = orch.classify_error(ValueError("bad mission logic"), mission_or_code_error=True)
        self.assertTrue(orch.is_code_or_mission_error(classification))
        self.assertFalse(orch.can_failover(classification))


class InstrumentationPhase2Tests(unittest.TestCase):
    def test_records_decision_and_error_with_simule_reel_separation(self):
        with tempfile.TemporaryDirectory() as td:
            store = MetricsEventStore(Path(td) / "m.db")
            with mock.patch("api_keys.get_all_keys", return_value=["k1"]):
                orch = ModelOrchestrator(OrchestratorConfig.defaults())
                decision = orch.select_model(MissionProfile(needs_coding=True))
            assert decision is not None
            record_routing_decision(store, decision, {"needs_coding": True}, origin=MeasurementOrigin.SIMULE)
            record_routing_decision(store, decision, {"needs_coding": True}, origin=MeasurementOrigin.REEL)
            cls = orch.classify_error(Exception("timeout"), timeout=True)
            record_classified_error(store, cls, "gemini", decision.selected_model or "", origin=MeasurementOrigin.SIMULE)
            self.assertEqual(len(store.list_events(event_type="routing_decision", origin="simule")), 1)
            self.assertEqual(len(store.list_events(event_type="routing_decision", origin="reel")), 1)
            self.assertEqual(len(store.list_events(event_type="classified_error", origin="simule")), 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from unittest import mock

from niang_ia.model_orchestrator.cline_routing import evaluate_cline_model, filter_cline_candidates
from niang_ia.model_orchestrator.config import OrchestratorConfig
from niang_ia.model_orchestrator.models import (
    CapabilitySet,
    IncidentKind,
    MissionProfile,
    ModelCapabilities,
    ModelRecord,
    ProviderKind,
)
from niang_ia.model_orchestrator.orchestrator import ModelOrchestrator
from niang_ia.model_orchestrator.providers.ollama import OllamaAdapter
from niang_ia.model_orchestrator.registry import ModelRegistry
from niang_ia.model_orchestrator.taxonomy import classify_incident


class OllamaAdapterPhase6Tests(unittest.TestCase):
    def test_discover_and_select_best_local_model(self):
        cfg = OrchestratorConfig.from_dict({
            "providers": {
                "ollama": {"enabled": True, "kind": "local", "models": [
                    {"model_id": "qwen2.5:7b", "coding": True, "reasoning": True, "tool_calling": True, "supports_general": True},
                    {"model_id": "small:latest", "coding": False, "reasoning": False, "tool_calling": False, "supports_general": True},
                ]}
            }
        })
        adapter = OllamaAdapter(cfg)
        with mock.patch("niang_ia.model_orchestrator.providers.ollama.probe_ollama_models", return_value={"available": True, "models": ["qwen2.5:7b", "small:latest"], "error": None}):
            discovered = adapter.discover_models()
            decision = adapter.select_model(MissionProfile(needs_coding=True, needs_reasoning=True), discovered=discovered)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.selected_provider, "ollama")
        self.assertEqual(decision.selected_model, "qwen2.5:7b")
        self.assertIn("best_match_ollama_local", decision.reason)

    def test_cline_selection_requires_verified_tool_calling(self):
        cfg = OrchestratorConfig.from_dict({
            "providers": {
                "ollama": {"enabled": True, "kind": "local", "models": [
                    {"model_id": "qwen2.5:7b", "coding": True, "tool_calling": True, "supports_cline": True, "cline_tool_calling_verified": True},
                    {"model_id": "other:7b", "coding": True, "tool_calling": True, "supports_cline": True, "cline_tool_calling_verified": False},
                ]}
            }
        })
        adapter = OllamaAdapter(cfg)
        decision = adapter.select_model(MissionProfile(engine="cline", needs_coding=True, needs_tool_calling=True))
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.selected_model, "qwen2.5:7b")
        self.assertEqual(decision.ranking_kind, "cline")


class ClineRoutingPhase6Tests(unittest.TestCase):
    def test_unverified_cline_model_not_eligible(self):
        unverified = ModelCapabilities(
            provider_id="ollama", model_id="m", kind=ProviderKind.LOCAL,
            capabilities=CapabilitySet(coding=True, tool_calling=True),
            supports_cline=True, cline_tool_calling_verified=False,
        )
        elig = evaluate_cline_model(unverified)
        self.assertFalse(elig.eligible)
        self.assertIn("not_verified", elig.reason)

    def test_filter_cline_candidates(self):
        good = ModelRecord(ModelCapabilities(
            provider_id="ollama", model_id="good", kind=ProviderKind.LOCAL,
            capabilities=CapabilitySet(coding=True, tool_calling=True),
            supports_cline=True, cline_tool_calling_verified=True,
        ))
        bad = ModelRecord(ModelCapabilities(
            provider_id="ollama", model_id="bad", kind=ProviderKind.LOCAL,
            capabilities=CapabilitySet(coding=True, tool_calling=True),
            supports_cline=True, cline_tool_calling_verified=False,
        ))
        out = filter_cline_candidates([bad, good], MissionProfile(engine="cline"))
        self.assertEqual([r.capabilities.model_id for r in out], ["good"])


class OrchestratorPhase6Tests(unittest.TestCase):
    def test_selects_best_across_gemini_and_ollama_when_enabled(self):
        cfg = OrchestratorConfig.from_dict({
            "providers": {
                "gemini": {"enabled": True, "kind": "free_quota", "models": [
                    {"model_id": "gemini-2.5-flash", "coding": True, "tool_calling": True, "latency_tier": "low"}
                ]},
                "ollama": {"enabled": True, "kind": "local", "models": [
                    {"model_id": "qwen2.5:7b", "coding": True, "reasoning": True, "tool_calling": True, "latency_tier": "medium"}
                ]},
            }
        })
        with mock.patch("api_keys.get_all_keys", return_value=["k1"]):
            orch = ModelOrchestrator(cfg)
            decision = orch.select_model(MissionProfile(needs_coding=True, needs_reasoning=True, needs_tool_calling=True))
        self.assertIsNotNone(decision)
        assert decision is not None
        # best for reasoning+coding+tool_calling should be ollama qwen in this configured setup
        self.assertEqual(decision.selected_model, "qwen2.5:7b")
        self.assertEqual(decision.selected_provider, "ollama")

    def test_cline_engine_never_selects_unverified_model(self):
        cfg = OrchestratorConfig.from_dict({
            "providers": {
                "ollama": {"enabled": True, "kind": "local", "models": [
                    {"model_id": "qwen2.5:7b", "coding": True, "tool_calling": True, "supports_cline": True, "cline_tool_calling_verified": False},
                ]}
            }
        })
        orch = ModelOrchestrator(cfg)
        decision = orch.select_model(MissionProfile(engine="cline", needs_coding=True, needs_tool_calling=True))
        self.assertIsNone(decision)

    def test_paid_provider_blocked(self):
        cfg = OrchestratorConfig.from_dict({
            "paid_usage_allowed": False,
            "providers": {"deepseek": {"enabled": True, "kind": "paid", "paid_allowed": False, "models": [{"model_id": "ds", "coding": True, "tool_calling": True}]}}
        })
        with mock.patch("api_keys.get_all_keys", return_value=[]):
            orch = ModelOrchestrator(cfg)
            decision = orch.select_model(MissionProfile(needs_coding=True), allow_paid=False)
        # either blocked decision or None (no eligible non-paid fallback)
        self.assertTrue(decision is None or decision.selected_model is None)

    def test_code_mission_error_classification_no_failover(self):
        c = classify_incident(mission_or_code_error=True)
        self.assertEqual(c.kind, IncidentKind.ERREUR_CODE_MISSION)
        self.assertFalse(c.failover_candidate)


class TaskQueueContinuityPhase6Tests(unittest.TestCase):
    def test_task_payload_includes_continuity_fields(self):
        from agent.task_queue import Task, TaskQueue
        q = TaskQueue(persist=False)
        task = Task(priority=2, created_at=1.0, task_id="t1", goal="g", workspace_verification_required=True,
                    failover_history=[{"incident": "timeout"}], handoff_summary={"mission_id": "t1"})
        payload = q._task_payload(task)
        self.assertTrue(payload["workspace_verification_required"])
        self.assertEqual(payload["failover_history"][0]["incident"], "timeout")
        self.assertEqual(payload["handoff_summary"]["mission_id"], "t1")


if __name__ == "__main__":
    unittest.main()

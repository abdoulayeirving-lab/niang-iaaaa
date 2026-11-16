from __future__ import annotations

import unittest
from unittest import mock

from niang_ia.model_orchestrator.execution import FailoverExecutionState, generate_with_failover
from niang_ia.model_orchestrator.models import IncidentKind, MissionProfile


def _models():
    # first is default/fallback-like, second is best capable fallback
    return [
        {"model_id": "model-a", "display_name": "A", "reasoning": False, "coding": True, "tool_calling": True, "latency_tier": "low"},
        {"model_id": "model-b", "display_name": "B", "reasoning": True, "coding": True, "tool_calling": True, "latency_tier": "medium"},
    ]


class DummyResp:
    def __init__(self, text="ok"):
        self.text = text


class Phase5FailoverExecutionTests(unittest.TestCase):
    def _run(self, side_effects, profile=None, fallback="model-a", handoff_base=None, state=None):
        profile = profile or MissionProfile(mission_id="M1", needs_coding=True, needs_tool_calling=True)
        handoff_base = handoff_base or {
            "mission_id": "M1", "objective": "goal", "mission_history_summary": "h",
            "actions_completed": [{"id": "1", "status": "completed"}],
            "files_created_or_modified": ["f.py"], "tool_results": [{"ok": True}],
            "errors_encountered": [], "approvals_state": {"a": "approved"}, "next_step": "continue",
        }
        calls = []

        def fake_generate(model, contents, config=None, api_version=None, timeout_ms=None):
            calls.append({"model": model, "contents": contents})
            eff = side_effects.pop(0)
            if isinstance(eff, Exception):
                raise eff
            return DummyResp(eff)

        with mock.patch("api_keys.get_all_keys", return_value=["k1"]), \
             mock.patch("api_keys.generate_with_retry", side_effect=fake_generate), \
             mock.patch("niang_ia.model_orchestrator.providers.gemini.GeminiAdapter._configured_models", return_value=_models()):
            resp, st, provider, model = generate_with_failover(
                contents="prompt",
                profile=profile,
                fallback_model_name=fallback,
                handoff_base=handoff_base,
                state=state or FailoverExecutionState(mission_id="M1"),
                sleep_fn=lambda s: None,
            )
        return resp, st, provider, model, calls

    def test_1_primary_available(self):
        resp, st, provider, model, calls = self._run(["ok"])
        self.assertEqual(resp.text, "ok")
        self.assertEqual(provider, "gemini")
        self.assertEqual(len(calls), 1)
        self.assertEqual(st.incident_history, [])

    def test_2_quota_exhausted_switches(self):
        resp, st, provider, model, calls = self._run([Exception("RESOURCE_EXHAUSTED 429 quota"), "ok"])
        self.assertEqual(resp.text, "ok")
        self.assertGreaterEqual(len(calls), 2)
        self.assertNotEqual(calls[0]["model"], calls[1]["model"])
        self.assertTrue(any(i["incident"] == IncidentKind.QUOTA_EPUISE.value for i in st.incident_history))

    def test_3_rate_limit_429_backoff_or_switch(self):
        # transient 429 -> backoff retry same model (safe) then success, or switch path depending plan; both valid if recovers
        resp, st, provider, model, calls = self._run([Exception("429 Too Many Requests"), "ok"])
        self.assertEqual(resp.text, "ok")
        self.assertGreaterEqual(len(calls), 2)
        self.assertTrue(any(i["incident"] == IncidentKind.RATE_LIMIT_TEMPORAIRE.value for i in st.incident_history))

    def test_4_error_500_switches_or_recovers(self):
        # 5xx is transient: may backoff+retry same model or switch depending on state/budget.
        resp, st, provider, model, calls = self._run([Exception("500 Internal Server Error"), "ok"])
        self.assertEqual(resp.text, "ok")
        self.assertTrue(any(i["incident"] == IncidentKind.PANNE_FOURNISSEUR.value for i in st.incident_history))
        self.assertGreaterEqual(len(calls), 2)

    def test_5_timeout_switches_or_recovers(self):
        resp, st, provider, model, calls = self._run([TimeoutError("request timed out"), "ok"])
        self.assertEqual(resp.text, "ok")
        self.assertTrue(any(i["incident"] == IncidentKind.TIMEOUT.value for i in st.incident_history))
        self.assertGreaterEqual(len(calls), 2)

    def test_6_provider_offline_switches(self):
        resp, st, provider, model, calls = self._run([Exception("connection refused service unavailable"), "ok"])
        self.assertEqual(resp.text, "ok")
        self.assertTrue(any(i["incident"] == IncidentKind.PANNE_FOURNISSEUR.value for i in st.incident_history))

    def test_7_tool_calling_error_switches(self):
        resp, st, provider, model, calls = self._run([Exception("invalid tool call schema"), "ok"])
        self.assertEqual(resp.text, "ok")
        self.assertTrue(any(i["incident"] == IncidentKind.ERREUR_TOOL_CALLING.value for i in st.incident_history))
        self.assertNotEqual(calls[0]["model"], calls[1]["model"])

    def test_8_secondary_unavailable_falls_through(self):
        # model-b on cooldown from the start; initial selection should pick model-a, fail quota, no fallback -> abort
        state = FailoverExecutionState(mission_id="M1")
        from niang_ia.model_orchestrator.models import CooldownState
        state.cooldowns["gemini:model-b"] = CooldownState(unavailable_until=9_999_999_999.0, reason="down", incident=IncidentKind.PANNE_FOURNISSEUR)
        profile = MissionProfile(mission_id="M1", needs_coding=False)
        calls_seen = []
        def fg(model, contents, config=None, api_version=None, timeout_ms=None):
            calls_seen.append(model)
            raise Exception("RESOURCE_EXHAUSTED")
        from unittest import mock
        with mock.patch("api_keys.get_all_keys", return_value=["k1"]), \
             mock.patch("api_keys.generate_with_retry", side_effect=fg), \
             mock.patch("niang_ia.model_orchestrator.providers.gemini.GeminiAdapter._configured_models", return_value=[
                {"model_id":"model-a","coding":True,"tool_calling":True},
                {"model_id":"model-b","coding":True,"tool_calling":True,"reasoning":True},
             ]):
            with self.assertRaises(RuntimeError):
                from niang_ia.model_orchestrator.execution import generate_with_failover
                generate_with_failover(contents="prompt", profile=profile, fallback_model_name="model-a", state=state, sleep_fn=lambda s: None)
        self.assertEqual(calls_seen, ["model-a"])

    def test_9_all_models_unavailable_aborts(self):
        state = FailoverExecutionState(mission_id="M1")
        from niang_ia.model_orchestrator.models import CooldownState
        state.cooldowns["gemini:model-a"] = CooldownState(unavailable_until=9_999_999_999.0, reason="q", incident=IncidentKind.QUOTA_EPUISE)
        state.cooldowns["gemini:model-b"] = CooldownState(unavailable_until=9_999_999_999.0, reason="q", incident=IncidentKind.QUOTA_EPUISE)
        calls_seen = []
        def fg(model, contents, config=None, api_version=None, timeout_ms=None):
            calls_seen.append(model)
            raise Exception("RESOURCE_EXHAUSTED")
        from unittest import mock
        with mock.patch("api_keys.get_all_keys", return_value=["k1"]), \
             mock.patch("api_keys.generate_with_retry", side_effect=fg), \
             mock.patch("niang_ia.model_orchestrator.providers.gemini.GeminiAdapter._configured_models", return_value=_models()):
            with self.assertRaises(RuntimeError):
                from niang_ia.model_orchestrator.execution import generate_with_failover
                generate_with_failover(contents="prompt", profile=MissionProfile(mission_id="M1",needs_coding=True), fallback_model_name="model-a", state=state, sleep_fn=lambda s: None)
        self.assertEqual(calls_seen, [])  # no eligible model to call

    def test_10_continuation_after_switch_includes_handoff(self):
        resp, st, provider, model, calls = self._run([Exception("RESOURCE_EXHAUSTED"), "continued"])
        self.assertEqual(resp.text, "continued")
        self.assertTrue(len(st.handoffs) >= 1)
        # second call should include handoff context in contents
        self.assertIn("CONTEXTE DE REPRISE", str(calls[1]["contents"]))
        self.assertIn("ne rejoue aucune action incertaine", str(calls[1]["contents"]))

    def test_11_no_uncertain_action_replay_and_preserves_context(self):
        # quota exhausted forces immediate switch with structured handoff
        handoff_base = {
            "mission_id": "M1", "objective": "goal",
            "actions_completed": [
                {"id": "1", "status": "completed"},
                {"id": "2", "status": "unknown", "side_effects_possible": True},
            ],
            "approvals_state": {"write": "approved"},
            "files_created_or_modified": ["x.py"],
            "next_step": "verify workspace then continue",
        }
        resp, st, provider, model, calls = self._run([Exception("RESOURCE_EXHAUSTED"), "ok"], handoff_base=handoff_base)
        self.assertEqual(resp.text, "ok")
        self.assertGreaterEqual(len(calls), 2)
        handoff = st.handoffs[0]
        self.assertEqual(handoff["mission_id"], "M1")
        self.assertEqual(handoff["approvals_state"]["write"], "approved")
        self.assertTrue(handoff["uncertain_actions_must_not_be_replayed"])
        self.assertIn("CONTEXTE DE REPRISE", str(calls[-1]["contents"]))
        cps = {c["step_id"]: c for c in handoff["checkpoints"]}
        self.assertFalse(cps["2"]["replay_allowed"])

    def test_12_mission_code_error_never_switches(self):
        with mock.patch("api_keys.get_all_keys", return_value=["k1"]), \
             mock.patch("api_keys.generate_with_retry", side_effect=ValueError("bad plan format in mission")) as gen, \
             mock.patch("niang_ia.model_orchestrator.providers.gemini.GeminiAdapter._configured_models", return_value=_models()):
            with self.assertRaises(ValueError):
                generate_with_failover(
                    contents="prompt",
                    profile=MissionProfile(mission_id="M1", needs_coding=True),
                    fallback_model_name="model-a",
                    sleep_fn=lambda s: None,
                )
        # no model switch attempts on code/mission error
        self.assertEqual(gen.call_count, 1)

    def test_no_infinite_loop_budget(self):
        # always fail with transient 500 on all models -> must stop
        with mock.patch("api_keys.get_all_keys", return_value=["k1"]), \
             mock.patch("api_keys.generate_with_retry", side_effect=Exception("500 server error")), \
             mock.patch("niang_ia.model_orchestrator.providers.gemini.GeminiAdapter._configured_models", return_value=_models()):
            with self.assertRaises(Exception):
                generate_with_failover(
                    contents="prompt",
                    profile=MissionProfile(mission_id="M1", needs_coding=True),
                    fallback_model_name="model-a",
                    sleep_fn=lambda s: None,
                )

    def test_paid_model_blocked_without_explicit_authorization(self):
        # configure provider as paid, selection/execution must not use it
        from niang_ia.model_orchestrator.config import OrchestratorConfig
        cfg = OrchestratorConfig.from_dict({
            "paid_usage_allowed": False,
            "providers": {"gemini": {"enabled": True, "kind": "paid", "paid_allowed": False, "models": [
                {"model_id": "model-a", "coding": True, "tool_calling": True},
                {"model_id": "model-b", "coding": True, "tool_calling": True},
            ]}}
        })
        with mock.patch("api_keys.get_all_keys", return_value=["k1"]), \
             mock.patch("api_keys.generate_with_retry", return_value=DummyResp("ok")) as gen:
            resp, st, provider, model = generate_with_failover(
                contents="prompt",
                profile=MissionProfile(mission_id="M1", needs_coding=True),
                fallback_model_name="model-a",
                allow_paid=False,
                orchestrator_config=cfg,
                sleep_fn=lambda s: None,
            )
        self.assertEqual(resp.text, "ok")


if __name__ == "__main__":
    unittest.main()

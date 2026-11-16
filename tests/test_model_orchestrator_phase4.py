from __future__ import annotations

import unittest
from unittest import mock

from niang_ia.model_orchestrator.models import IncidentKind
from niang_ia.model_orchestrator.runtime import classify_runtime_error, resolve_gemini_model


class RuntimePhase4Tests(unittest.TestCase):
    def test_resolve_best_gemini_model_without_failover(self):
        with mock.patch("api_keys.get_all_keys", return_value=["k1"]):
            resolved = resolve_gemini_model(
                "gemini-2.5-flash",
                needs_coding=True,
                needs_reasoning=True,
                preferred_latency="balanced",
            )
        self.assertTrue(resolved.model_name)
        self.assertEqual(resolved.provider_id, "gemini")
        # Single-provider resolution only; no runtime failover/switch mechanism executed.
        self.assertNotEqual(resolved.reason, "")

    def test_resolve_falls_back_when_no_credentials(self):
        with mock.patch("api_keys.get_all_keys", return_value=[]):
            resolved = resolve_gemini_model("gemini-2.5-flash", needs_coding=True)
        self.assertEqual(resolved.model_name, "gemini-2.5-flash")

    def test_resolve_falls_back_on_orchestrator_error(self):
        with mock.patch("niang_ia.model_orchestrator.runtime._get_orchestrator", side_effect=RuntimeError("boom")):
            resolved = resolve_gemini_model("gemini-3.5-flash-lite")
        self.assertEqual(resolved.model_name, "gemini-3.5-flash-lite")
        self.assertIn("fallback", resolved.reason)

    def test_classify_runtime_error_taxonomy(self):
        with mock.patch("api_keys.get_all_keys", return_value=["k1"]):
            c1 = classify_runtime_error(Exception("RESOURCE_EXHAUSTED"), status_code=429)
            c2 = classify_runtime_error(Exception("too many requests"), status_code=429)
            c3 = classify_runtime_error(Exception("server error"), status_code=503)
            c4 = classify_runtime_error(TimeoutError("timed out"))
            c5 = classify_runtime_error(Exception("tool schema error"), tool_calling_error=True)
            c6 = classify_runtime_error(Exception("syntax error"), mission_or_code_error=True)
        self.assertIsNotNone(c1)
        assert c1 and c2 and c3 and c4 and c5 and c6
        self.assertEqual(c1.kind, IncidentKind.QUOTA_EPUISE)
        self.assertEqual(c2.kind, IncidentKind.RATE_LIMIT_TEMPORAIRE)
        self.assertEqual(c3.kind, IncidentKind.PANNE_FOURNISSEUR)
        self.assertEqual(c4.kind, IncidentKind.TIMEOUT)
        self.assertEqual(c5.kind, IncidentKind.ERREUR_TOOL_CALLING)
        self.assertEqual(c6.kind, IncidentKind.ERREUR_CODE_MISSION)
        self.assertFalse(c6.failover_candidate)


class TaskQueueRoutingFieldsPhase4Tests(unittest.TestCase):
    def test_task_payload_and_restore_keep_routing_fields_backward_compatible(self):
        from agent.task_queue import Task, TaskStatus, _queue
        # payload shape includes additive routing fields
        task = Task(priority=2, created_at=1.0, task_id="t1", goal="g")
        payload = _queue._task_payload(task)
        for k in ["routing_provider", "routing_model", "routing_reason", "routing_incident_history"]:
            self.assertIn(k, payload)
        # restore-like construction tolerance: old payload without fields should default via .get usage in code paths
        self.assertEqual(payload["routing_provider"], "")
        self.assertEqual(payload["routing_incident_history"], [])

    def test_get_status_includes_routing_fields(self):
        from agent.task_queue import TaskQueue, Task, TaskStatus
        q = TaskQueue(persist=False)
        task = Task(priority=2, created_at=1.0, task_id="t2", goal="g", routing_model="gemini-2.5-flash", routing_provider="gemini")
        with q._lock:
            q._tasks["t2"] = task
        status = q.get_status("t2")
        self.assertIsNotNone(status)
        assert status is not None
        self.assertEqual(status["routing_model"], "gemini-2.5-flash")
        self.assertEqual(status["routing_provider"], "gemini")


if __name__ == "__main__":
    unittest.main()

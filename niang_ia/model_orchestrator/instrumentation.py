from __future__ import annotations

import time
from typing import Any

from .metrics_store import MetricsEventStore
from .models import MeasurementOrigin, RoutingDecision
from .taxonomy import IncidentClassification


def record_routing_decision(
    store: MetricsEventStore,
    decision: RoutingDecision,
    profile_summary: dict[str, Any] | None = None,
    origin: MeasurementOrigin = MeasurementOrigin.SIMULE,
) -> int:
    payload = {
        "timestamp": time.time(),
        "event": "routing_decision",
        "selected_provider": decision.selected_provider,
        "selected_model": decision.selected_model,
        "score": decision.score,
        "reason": decision.reason,
        "fallback_chain": list(decision.fallback_chain),
        "engine": decision.engine,
        "ranking_kind": decision.ranking_kind,
        "profile": profile_summary or {},
    }
    return store.record_event("routing_decision", origin.value, payload)


def record_classified_error(
    store: MetricsEventStore,
    classification: IncidentClassification,
    provider_id: str = "",
    model_id: str = "",
    origin: MeasurementOrigin = MeasurementOrigin.SIMULE,
    details: dict[str, Any] | None = None,
) -> int:
    payload = {
        "timestamp": time.time(),
        "event": "classified_error",
        "provider_id": provider_id,
        "model_id": model_id,
        "incident": classification.kind.value,
        "retryable": classification.retryable,
        "failover_candidate": classification.failover_candidate,
        "reason": classification.reason,
        "details": details or {},
    }
    return store.record_event("classified_error", origin.value, payload)

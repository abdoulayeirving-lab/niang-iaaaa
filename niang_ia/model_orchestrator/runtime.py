from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import api_keys
from .config import OrchestratorConfig, load_orchestrator_config
from .execution import FailoverExecutionState, generate_with_failover
from .metrics_store import MetricsEventStore
from .models import MeasurementOrigin, MissionProfile, RoutingDecision
from .taxonomy import IncidentClassification

try:
    from .orchestrator import ModelOrchestrator
except Exception:  # pragma: no cover - defensive
    ModelOrchestrator = None  # type: ignore


@dataclass(frozen=True)
class ResolvedModel:
    model_name: str
    provider_id: str | None = None
    reason: str = "fallback"
    decision: RoutingDecision | None = None


_orchestrator: Any = None
_store: MetricsEventStore | None = None


def _get_orchestrator() -> Any:
    global _orchestrator
    if _orchestrator is not None:
        return _orchestrator
    if ModelOrchestrator is None:
        return None
    try:
        _orchestrator = ModelOrchestrator(load_orchestrator_config())
    except Exception:
        _orchestrator = None
    return _orchestrator


def _get_store() -> MetricsEventStore | None:
    global _store
    if _store is not None:
        return _store
    try:
        cfg = load_orchestrator_config()
        path = cfg.metrics_path or None
        _store = MetricsEventStore(path)
    except Exception:
        _store = None
    return _store


def resolve_gemini_model(
    fallback_model_name: str,
    *,
    mission_id: str = "",
    mission_type: str = "general",
    needs_reasoning: bool = False,
    needs_coding: bool = False,
    needs_vision: bool = False,
    needs_document_analysis: bool = False,
    needs_tool_calling: bool = False,
    required_context_tokens: int | None = None,
    preferred_latency: str = "balanced",
    engine: str = "niang",
    allow_paid: bool = False,
    origin: MeasurementOrigin = MeasurementOrigin.SIMULE,
) -> ResolvedModel:
    """Resolve best Gemini model via orchestrator with safe fallback.

    Never raises; always returns a usable model name (fallback on any issue).
    No model/provider failover is performed.
    """
    try:
        orch = _get_orchestrator()
        if orch is None:
            return ResolvedModel(model_name=fallback_model_name, reason="orchestrator_unavailable")
        profile = MissionProfile(
            mission_id=mission_id,
            mission_type=mission_type,
            needs_reasoning=needs_reasoning,
            needs_coding=needs_coding,
            needs_vision=needs_vision,
            needs_document_analysis=needs_document_analysis,
            needs_tool_calling=needs_tool_calling,
            required_context_tokens=required_context_tokens,
            preferred_latency=preferred_latency,
            engine=engine,
            allow_paid=allow_paid,
        )
        decision = orch.select_model(profile, engine=engine, allow_paid=allow_paid)
        if decision and decision.selected_model and decision.selected_provider == "gemini":
            _record_decision_safe(decision, profile, origin)
            return ResolvedModel(
                model_name=decision.selected_model,
                provider_id=decision.selected_provider,
                reason=decision.reason or "orchestrator_selected",
                decision=decision,
            )
        if decision and decision.reason == "paid_provider_blocked_missing_explicit_authorization":
            # Safety: do not route to paid path; fallback to historical model behavior.
            return ResolvedModel(model_name=fallback_model_name, reason=decision.reason, decision=decision)
    except Exception:
        pass
    return ResolvedModel(model_name=fallback_model_name, reason="fallback_historical")


def _record_decision_safe(decision: RoutingDecision, profile: MissionProfile, origin: MeasurementOrigin) -> None:
    try:
        store = _get_store()
        if store is None:
            return
        from .instrumentation import record_routing_decision
        record_routing_decision(
            store,
            decision,
            profile_summary={
                "mission_id": profile.mission_id,
                "mission_type": profile.mission_type,
                "needs_reasoning": profile.needs_reasoning,
                "needs_coding": profile.needs_coding,
                "needs_tool_calling": profile.needs_tool_calling,
                "engine": profile.engine,
            },
            origin=origin,
        )
    except Exception:
        pass


def classify_runtime_error(exc: Exception | str, **signals: Any) -> IncidentClassification | None:
    try:
        orch = _get_orchestrator()
        if orch is None:
            return None
        return orch.classify_error(exc, **signals)
    except Exception:
        return None


def record_error_safe(
    classification: IncidentClassification | None,
    provider_id: str = "",
    model_id: str = "",
    origin: MeasurementOrigin = MeasurementOrigin.SIMULE,
    details: dict[str, Any] | None = None,
) -> None:
    if classification is None:
        return
    try:
        store = _get_store()
        if store is None:
            return
        from .instrumentation import record_classified_error
        record_classified_error(store, classification, provider_id=provider_id, model_id=model_id, origin=origin, details=details)
    except Exception:
        pass


class RuntimeGeminiModel:
    """Gemini-compatible model wrapper with controlled failover (Phase 5)."""

    def __init__(
        self,
        model_name: str,
        *,
        system_instruction: str | None = None,
        generation_config: dict | None = None,
        timeout_s: int | None = None,
        profile: MissionProfile | None = None,
        mission_handoff_base: dict[str, Any] | None = None,
        execution_state: FailoverExecutionState | None = None,
        allow_paid: bool = False,
        fallback_on_error: bool = True,
    ):
        self.fallback_model_name = model_name
        self.system_instruction = system_instruction
        self.generation_config = generation_config or {}
        self.profile = profile or MissionProfile()
        self.mission_handoff_base = mission_handoff_base or {}
        self.execution_state = execution_state
        self.allow_paid = allow_paid
        self.fallback_on_error = fallback_on_error
        if timeout_s is None:
            try:
                from agent.settings import gemini_timeout_seconds
                timeout_s = gemini_timeout_seconds()
            except Exception:
                timeout_s = 180
        if not 1 <= timeout_s <= 1800:
            raise ValueError("Gemini timeout must be between 1 and 1800 seconds.")
        self.timeout_ms = timeout_s * 1000

    def generate_content(self, contents, **kwargs):
        from google.genai import types

        config_values = dict(self.generation_config)
        config_values.update(kwargs)
        if self.system_instruction is not None:
            config_values["system_instruction"] = self.system_instruction
        config = types.GenerateContentConfig(**config_values) if config_values else None

        try:
            response, state, provider, model = generate_with_failover(
                contents=contents,
                config=config,
                timeout_ms=self.timeout_ms,
                profile=self.profile,
                fallback_model_name=self.fallback_model_name,
                allow_paid=self.allow_paid,
                handoff_base=self.mission_handoff_base,
                state=self.execution_state,
            )
            self.execution_state = state
            return response
        except Exception:
            if not self.fallback_on_error:
                raise
            # Final safety fallback to legacy direct behavior (preserves existing semantics)
            return api_keys.generate_with_retry(
                self.fallback_model_name,
                contents,
                config=config,
                timeout_ms=self.timeout_ms,
            )


def get_gemini_model(
    fallback_model_name: str,
    *,
    system_instruction: str | None = None,
    generation_config: dict | None = None,
    timeout_s: int | None = None,
    mission_id: str = "",
    mission_type: str = "general",
    needs_reasoning: bool = False,
    needs_coding: bool = False,
    needs_vision: bool = False,
    needs_document_analysis: bool = False,
    needs_tool_calling: bool = False,
    required_context_tokens: int | None = None,
    preferred_latency: str = "balanced",
    allow_paid: bool = False,
    handoff_base: dict[str, Any] | None = None,
    execution_state: FailoverExecutionState | None = None,
):
    profile = MissionProfile(
        mission_id=mission_id,
        mission_type=mission_type,
        needs_reasoning=needs_reasoning,
        needs_coding=needs_coding,
        needs_vision=needs_vision,
        needs_document_analysis=needs_document_analysis,
        needs_tool_calling=needs_tool_calling,
        required_context_tokens=required_context_tokens,
        preferred_latency=preferred_latency,
        engine="niang",
        allow_paid=allow_paid,
    )
    return RuntimeGeminiModel(
        fallback_model_name,
        system_instruction=system_instruction,
        generation_config=generation_config,
        timeout_s=timeout_s,
        profile=profile,
        mission_handoff_base=handoff_base,
        execution_state=execution_state,
        allow_paid=allow_paid,
        fallback_on_error=True,
    )

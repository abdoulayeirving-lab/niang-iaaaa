from __future__ import annotations

from typing import Any

from .cline_routing import filter_cline_candidates
from .config import OrchestratorConfig, load_orchestrator_config
from .continuity import build_handoff_context, validate_handoff_for_resume
from .failover import plan_failover
from .models import (
    AttemptRecord,
    CooldownState,
    FailoverPlan,
    HandoffContext,
    IncidentKind,
    MeasurementOrigin,
    MissionProfile,
    ModelRecord,
    ProviderKind,
    RoutingDecision,
)
from .providers.gemini import GeminiAdapter
from .providers.ollama import OllamaAdapter
from .registry import ModelRegistry
from .scoring import select_best_candidate
from .taxonomy import IncidentClassification, classify_incident, should_failover


class ModelOrchestrator:
    """Orchestrator entry point (Phase 3 foundations, not runtime-integrated).

    - Selects the best available Gemini candidate for a mission profile (Phase 2 behavior).
    - Provides failover planning and handoff-building helpers (Phase 3) without executing
      failover, without network side effects, and without integration into existing runtimes.
    - Never authorizes paid spending without explicit allow_paid + config authorization.
    """

    def __init__(self, config: OrchestratorConfig | None = None, *, ollama_discovered: list[str] | None = None):
        self.config = config or load_orchestrator_config()
        self.gemini = GeminiAdapter(self.config)
        self.ollama = OllamaAdapter(self.config)
        self._ollama_discovered = ollama_discovered

    def _paid_allowed(self, provider_id: str, allow_paid: bool) -> bool:
        # Explicit per-call authorization is required in addition to config-level authorization.
        return bool(allow_paid) and self.config.provider_can_spend(provider_id)

    def select_model(
        self,
        profile: MissionProfile,
        engine: str | None = None,
        allow_paid: bool = False,
        user_override: str | None = None,
    ) -> RoutingDecision | None:
        effective_engine = engine if engine is not None else (profile.engine or "niang")
        if user_override and not profile.user_override_model:
            profile = MissionProfile(
                mission_id=profile.mission_id,
                mission_type=profile.mission_type,
                difficulty=profile.difficulty,
                needs_reasoning=profile.needs_reasoning,
                needs_coding=profile.needs_coding,
                needs_vision=profile.needs_vision,
                needs_document_analysis=profile.needs_document_analysis,
                needs_tool_calling=profile.needs_tool_calling,
                required_context_tokens=profile.required_context_tokens,
                preferred_latency=profile.preferred_latency,
                engine=effective_engine,
                user_override_model=user_override,
                allow_paid=allow_paid,
            )
        else:
            profile = MissionProfile(
                mission_id=profile.mission_id,
                mission_type=profile.mission_type,
                difficulty=profile.difficulty,
                needs_reasoning=profile.needs_reasoning,
                needs_coding=profile.needs_coding,
                needs_vision=profile.needs_vision,
                needs_document_analysis=profile.needs_document_analysis,
                needs_tool_calling=profile.needs_tool_calling,
                required_context_tokens=profile.required_context_tokens,
                preferred_latency=profile.preferred_latency,
                engine=effective_engine,
                user_override_model=profile.user_override_model or user_override,
                allow_paid=allow_paid,
            )

        # Build candidate pool from enabled/configured providers (Gemini + local Ollama if available/configured).
        registry = ModelRegistry.from_config(self.config, ollama_discovered=self._ollama_discovered)
        candidates = [r for r in registry.records.values() if r.available]
        # Filter by engine/ranking
        if (engine or profile.engine) == "cline":
            candidates = filter_cline_candidates(candidates, profile)
            ranking_kind = "cline"
        else:
            candidates = [r for r in candidates if r.capabilities.supports_general]
            ranking_kind = "general"

        # User override if present and eligible
        if profile.user_override_model:
            for r in candidates:
                key = f"{r.capabilities.provider_id}:{r.capabilities.model_id}"
                if profile.user_override_model in {r.capabilities.model_id, key}:
                    if r.capabilities.kind == ProviderKind.PAID and not self._paid_allowed(r.capabilities.provider_id, allow_paid):
                        return RoutingDecision(None, None, 0.0, "paid_provider_blocked_missing_explicit_authorization", [], profile.engine, ranking_kind)
                    return RoutingDecision(r.capabilities.provider_id, r.capabilities.model_id, 100.0, "explicit_user_override", [], profile.engine, ranking_kind)

        config_paid_ok = {pid: self.config.provider_can_spend(pid) for pid in self.config.providers.keys()}
        # Gemini credentials check: exclude Gemini candidates if no credentials configured
        try:
            import api_keys
            gemini_has_creds = len(api_keys.get_all_keys()) > 0
        except Exception:
            gemini_has_creds = False
        filtered = []
        for r in candidates:
            if r.capabilities.provider_id == "gemini" and not gemini_has_creds:
                continue
            # Ollama candidates only considered if provider enabled or explicitly discovered/declared
            if r.capabilities.provider_id == "ollama":
                p = self.config.providers.get("ollama")
                if not (p and p.enabled) and self._ollama_discovered is None and not (p and p.models):
                    continue
            filtered.append(r)

        best, score, reasons = select_best_candidate(filtered, profile, allow_paid=allow_paid, config_paid_ok=config_paid_ok)
        if best is None:
            # Explicit block reason when candidates exist but are excluded only by missing paid authorization.
            paid_blocked_candidates = [
                r for r in filtered
                if r.capabilities.kind == ProviderKind.PAID and not self._paid_allowed(r.capabilities.provider_id, allow_paid)
            ]
            if paid_blocked_candidates:
                return RoutingDecision(None, None, 0.0, "paid_provider_blocked_missing_explicit_authorization", [], profile.engine, ranking_kind)
            # Safe fallback: try Gemini adapter only for non-cline general missions when Gemini is eligible
            if effective_engine != "cline" and gemini_has_creds:
                gem_cfg = self.config.providers.get("gemini")
                gemini_paid_blocked = bool(gem_cfg and gem_cfg.kind == "paid" and not self._paid_allowed("gemini", allow_paid))
                if not gemini_paid_blocked:
                    fallback = self.gemini.select_model(profile)
                    if fallback and fallback.selected_model:
                        return fallback
            return None
        if best.capabilities.kind == ProviderKind.PAID and not self._paid_allowed(best.capabilities.provider_id, allow_paid):
            return RoutingDecision(None, None, 0.0, "paid_provider_blocked_missing_explicit_authorization", [], profile.engine, ranking_kind)
        chain = [f"{r.capabilities.provider_id}:{r.capabilities.model_id}" for r in filtered if r is not best]
        return RoutingDecision(
            selected_provider=best.capabilities.provider_id,
            selected_model=best.capabilities.model_id,
            score=score,
            reason=f"best_match_{ranking_kind}; score={score:.2f}; factors={','.join(reasons[:6])}",
            fallback_chain=chain[:10],
            engine=profile.engine,
            ranking_kind=ranking_kind,
        )

    def classify_error(self, exc: Exception | str, **signals: Any) -> IncidentClassification:
        provider = str(signals.get("provider", "gemini"))
        if provider == "gemini":
            return self.gemini.classify_error(exc, **signals)
        if provider == "ollama":
            return self.ollama.classify_error(exc, **signals)
        return classify_incident(error_text=str(exc), **{k: v for k, v in signals.items() if k in {
            "status_code", "timeout", "provider_unavailable", "quota_exhausted", "rate_limited",
            "tool_calling_error", "context_limit_exceeded", "mission_or_code_error"
        }})

    @staticmethod
    def can_failover(classification: IncidentClassification) -> bool:
        # Exposed for future phases/instrumentation; no failover is executed in Phase 2.
        return should_failover(classification.kind)

    @staticmethod
    def is_code_or_mission_error(classification: IncidentClassification) -> bool:
        return classification.kind == IncidentKind.ERREUR_CODE_MISSION

    def plan_failover(
        self,
        *,
        classification: IncidentClassification,
        profile: MissionProfile,
        current_provider: str | None,
        current_model: str | None,
        candidates: list[ModelRecord],
        attempts: list[AttemptRecord] | None = None,
        cooldowns: dict[str, CooldownState] | None = None,
        now: float | None = None,
        allow_paid: bool = False,
        handoff_base: dict[str, Any] | None = None,
        current_step_state: str = "unknown",
        measured_history: list[dict[str, Any]] | None = None,
        measured_origin: MeasurementOrigin | None = None,
    ) -> FailoverPlan:
        """Plan (do not execute) a safe failover/retry decision."""
        return plan_failover(
            classification=classification,
            profile=profile,
            current_provider=current_provider,
            current_model=current_model,
            candidates=candidates,
            attempts=attempts,
            cooldowns=cooldowns,
            config=self.config,
            now=now,
            allow_paid=allow_paid,
            handoff_base=handoff_base,
            current_step_state=current_step_state,
            measured_history=measured_history,
            measured_origin=measured_origin,
        )

    @staticmethod
    def build_handoff(**kwargs: Any) -> HandoffContext:
        """Build a structured, safety-validated handoff context (no execution)."""
        return build_handoff_context(**kwargs)

    @staticmethod
    def validate_handoff(handoff: HandoffContext):
        return validate_handoff_for_resume(handoff)

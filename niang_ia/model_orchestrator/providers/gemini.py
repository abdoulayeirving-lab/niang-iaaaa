from __future__ import annotations

from typing import Any

import api_keys
from ..config import OrchestratorConfig
from ..models import CapabilitySet, IncidentKind, MeasurementOrigin, MissionProfile, ModelCapabilities, RoutingDecision
from ..taxonomy import IncidentClassification, classify_incident
from .base import ProviderAdapter


_DEFAULT_GEMINI_MODELS: list[dict[str, Any]] = [
    {
        "model_id": "gemini-2.5-flash",
        "display_name": "Gemini 2.5 Flash",
        "reasoning": True,
        "coding": True,
        "tool_calling": True,
        "max_context_tokens": 1_000_000,
        "latency_tier": "low",
    },
    {
        "model_id": "gemini-2.0-flash",
        "display_name": "Gemini 2.0 Flash",
        "reasoning": False,
        "coding": True,
        "tool_calling": True,
        "max_context_tokens": 1_000_000,
        "latency_tier": "low",
    },
    {
        "model_id": "gemini-3.5-flash-lite",
        "display_name": "Gemini 3.5 Flash Lite",
        "reasoning": False,
        "coding": False,
        "tool_calling": False,
        "max_context_tokens": 1_000_000,
        "latency_tier": "low",
    },
]


class GeminiAdapter(ProviderAdapter):
    provider_id = "gemini"

    def __init__(self, config: OrchestratorConfig | None = None):
        self.config = config or OrchestratorConfig.defaults()

    def _configured_models(self) -> list[dict[str, Any]]:
        provider = self.config.providers.get(self.provider_id)
        if provider and provider.models:
            return [m for m in provider.models if isinstance(m, dict) and str(m.get("model_id", "")).strip()]
        return list(_DEFAULT_GEMINI_MODELS)

    def has_credentials(self) -> bool:
        try:
            return len(api_keys.get_all_keys()) > 0
        except Exception:
            return False

    def list_candidate_models(self) -> list[ModelCapabilities]:
        # Kind comes from config when provided; default is non-paid-spend-authorized usage context.
        provider = self.config.providers.get(self.provider_id)
        kind_value = (provider.kind if provider else "free_quota")
        from ..models import ProviderKind
        kind = ProviderKind(kind_value) if kind_value in ProviderKind._value2member_map_ else ProviderKind.FREE_QUOTA
        caps_list: list[ModelCapabilities] = []
        for m in self._configured_models():
            model_id = str(m.get("model_id") or m.get("id"))
            cap = CapabilitySet(
                reasoning=bool(m.get("reasoning", False)),
                coding=bool(m.get("coding", False)),
                vision=bool(m.get("vision", False)),
                document_analysis=bool(m.get("document_analysis", False)),
                tool_calling=bool(m.get("tool_calling", False)),
                streaming=bool(m.get("streaming", True)),
                max_context_tokens=m.get("max_context_tokens"),
                latency_tier=str(m.get("latency_tier", "unknown")),
            )
            caps_list.append(
                ModelCapabilities(
                    provider_id=self.provider_id,
                    model_id=model_id,
                    display_name=str(m.get("display_name") or model_id),
                    kind=kind,
                    capabilities=cap,
                    supports_general=bool(m.get("supports_general", True)),
                    supports_cline=bool(m.get("supports_cline", False)),
                    cline_tool_calling_verified=bool(m.get("cline_tool_calling_verified", False)),
                    verified=bool(m.get("verified", False)),
                    notes="Gemini adapter facade over existing api_keys; real billing tier must be respected.",
                )
            )
        return caps_list

    def _score_model(self, model: ModelCapabilities, profile: MissionProfile) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        c = model.capabilities
        if profile.needs_reasoning:
            score += 3.0 if c.reasoning else -2.0
            reasons.append("reasoning_match" if c.reasoning else "reasoning_missing")
        if profile.needs_coding:
            score += 3.0 if c.coding else -1.5
            reasons.append("coding_match" if c.coding else "coding_limited")
        if profile.needs_vision or profile.needs_document_analysis:
            score += 2.0 if (c.vision or c.document_analysis) else -1.0
            reasons.append("vision_doc_match" if (c.vision or c.document_analysis) else "vision_doc_unknown")
        if profile.needs_tool_calling:
            score += 2.5 if c.tool_calling else -2.5
            reasons.append("tool_calling_match" if c.tool_calling else "tool_calling_missing")
        if profile.required_context_tokens and c.max_context_tokens:
            if c.max_context_tokens >= profile.required_context_tokens:
                score += 1.0
                reasons.append("context_ok")
            else:
                score -= 3.0
                reasons.append("context_insufficient")
        if profile.preferred_latency == "fast":
            score += 1.0 if c.latency_tier == "low" else 0.0
            reasons.append("latency_fast" if c.latency_tier == "low" else "latency_not_fast")
        elif profile.preferred_latency == "quality":
            score += 0.5 if c.reasoning else 0.0
            reasons.append("quality_bias")
        else:
            reasons.append("balanced")
        # Small deterministic preference for more capable general models among equals.
        score += 0.1 * sum([c.reasoning, c.coding, c.tool_calling])
        return score, reasons

    def select_model(self, profile: MissionProfile) -> RoutingDecision | None:
        if not self.has_credentials():
            return None
        candidates = [m for m in self.list_candidate_models() if m.supports_general]
        if profile.user_override_model:
            for m in candidates:
                if m.model_id == profile.user_override_model or f"{m.provider_id}:{m.model_id}" == profile.user_override_model:
                    return RoutingDecision(
                        selected_provider=m.provider_id,
                        selected_model=m.model_id,
                        score=100.0,
                        reason="explicit_user_override",
                        fallback_chain=[],
                        engine=profile.engine,
                        ranking_kind="general",
                    )
        if not candidates:
            return None
        scored = []
        for m in candidates:
            s, reasons = self._score_model(m, profile)
            scored.append((s, m, reasons))
        scored.sort(key=lambda x: (-x[0], x[1].model_id))
        best_score, best, reasons = scored[0]
        fallbacks = [f"{m.provider_id}:{m.model_id}" for _, m, _ in scored[1:]]
        reason = f"best_match_single_provider_gemini; score={best_score:.2f}; factors={','.join(reasons[:6])}"
        return RoutingDecision(
            selected_provider=best.provider_id,
            selected_model=best.model_id,
            score=best_score,
            reason=reason,
            fallback_chain=fallbacks,
            engine=profile.engine,
            ranking_kind="general",
        )

    def classify_error(self, exc: Exception | str, **signals: Any) -> IncidentClassification:
        text = str(exc) if exc is not None else ""
        status_code = signals.get("status_code")
        lower = text.lower()
        quota_exhausted = bool(signals.get("quota_exhausted")) or "resource_exhausted" in lower or "quota" in lower and "429" in lower
        rate_limited = bool(signals.get("rate_limited")) or (status_code == 429) or "rate limit" in lower or "too many requests" in lower
        # Distinguish: explicit quota/resource exhausted signals treated as quota exhausted; pure throttling as rate limit.
        if "resource_exhausted" in lower or "insufficient_quota" in lower or "daily quota" in lower:
            quota_exhausted = True
            rate_limited = False
        elif status_code == 429 and "quota" in lower:
            quota_exhausted = True
            rate_limited = False
        elif status_code == 429:
            rate_limited = True
            quota_exhausted = False
        timeout = bool(signals.get("timeout")) or isinstance(exc, TimeoutError) or "timeout" in lower or "timed out" in lower
        provider_unavailable = bool(signals.get("provider_unavailable")) or (isinstance(status_code, int) and 500 <= status_code <= 599) or "unavailable" in lower or "connection" in lower
        tool_calling_error = bool(signals.get("tool_calling_error")) or "tool call" in lower or "function call" in lower or "invalid argument" in lower and "tool" in lower
        mission_or_code_error = bool(signals.get("mission_or_code_error"))
        context_limit_exceeded = bool(signals.get("context_limit_exceeded")) or "context length" in lower or "token" in lower and "exceed" in lower
        return classify_incident(
            status_code=status_code if isinstance(status_code, int) else None,
            error_text=text,
            timeout=timeout,
            provider_unavailable=provider_unavailable,
            quota_exhausted=quota_exhausted,
            rate_limited=rate_limited,
            tool_calling_error=tool_calling_error,
            context_limit_exceeded=context_limit_exceeded,
            mission_or_code_error=mission_or_code_error,
        )

    # Facade methods (no behavior change vs existing api_keys helpers)
    def generate(self, model: str, contents: Any, config: Any = None, api_version: str | None = None, timeout_ms: int | None = None):
        return api_keys.generate_with_retry(model, contents, config=config, api_version=api_version, timeout_ms=timeout_ms)

    async def aio_generate(self, model: str, contents: Any, config: Any = None, api_version: str | None = None):
        return await api_keys.aio_generate(model, contents, config=config, api_version=api_version)

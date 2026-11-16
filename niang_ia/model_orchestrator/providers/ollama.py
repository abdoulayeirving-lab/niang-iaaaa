from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..config import OrchestratorConfig
from ..models import CapabilitySet, MissionProfile, ModelCapabilities, ProviderKind, RoutingDecision
from ..taxonomy import IncidentClassification, classify_incident
from .base import ProviderAdapter

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


def probe_ollama_models(base_url: str = DEFAULT_OLLAMA_BASE_URL, timeout: float = 3.0) -> dict[str, Any]:
    request = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError, TimeoutError) as exc:
        return {"available": False, "models": [], "error": str(exc) or "Local Ollama did not respond."}
    models = payload.get("models", []) if isinstance(payload, dict) else []
    names = [str(item.get("name", "")) for item in models if isinstance(item, dict) and item.get("name")]
    return {"available": True, "models": names, "error": None}


class OllamaAdapter(ProviderAdapter):
    provider_id = "ollama"

    def __init__(self, config: OrchestratorConfig | None = None):
        self.config = config or OrchestratorConfig.defaults()

    def _provider_cfg(self):
        return self.config.providers.get(self.provider_id)

    def base_url(self) -> str:
        cfg = self._provider_cfg()
        if cfg and isinstance(cfg.models, list):
            # allow provider-level base_url in config models container? not in schema; use default
            pass
        # support base_url stored in provider extra if added later; for now default/local
        return DEFAULT_OLLAMA_BASE_URL

    def _configured_models(self) -> list[dict[str, Any]]:
        cfg = self._provider_cfg()
        if cfg and cfg.models:
            return [m for m in cfg.models if isinstance(m, dict) and str(m.get("model_id", "")).strip()]
        return []

    def discover_models(self, timeout: float = 3.0) -> list[str]:
        probe = probe_ollama_models(self.base_url(), timeout=timeout)
        if not probe.get("available"):
            return []
        return list(probe.get("models") or [])

    def list_candidate_models(self, discovered: list[str] | None = None) -> list[ModelCapabilities]:
        cfg_models = {str(m.get("model_id")): m for m in self._configured_models()}
        discovered = discovered or []
        caps_list: list[ModelCapabilities] = []
        # Prefer configured metadata for known models; include discovered models with conservative defaults.
        seen = set()
        for model_id, m in cfg_models.items():
            seen.add(model_id)
            cap = CapabilitySet(
                reasoning=bool(m.get("reasoning", False)),
                coding=bool(m.get("coding", False)),
                vision=bool(m.get("vision", False)),
                document_analysis=bool(m.get("document_analysis", False)),
                tool_calling=bool(m.get("tool_calling", False)),
                streaming=bool(m.get("streaming", False)),
                max_context_tokens=m.get("max_context_tokens"),
                latency_tier=str(m.get("latency_tier", "unknown")),
            )
            caps_list.append(ModelCapabilities(
                provider_id=self.provider_id,
                model_id=model_id,
                display_name=str(m.get("display_name") or model_id),
                kind=ProviderKind.LOCAL,
                capabilities=cap,
                supports_general=bool(m.get("supports_general", True)),
                supports_cline=bool(m.get("supports_cline", False)),
                cline_tool_calling_verified=bool(m.get("cline_tool_calling_verified", False)),
                verified=bool(m.get("verified", False)),
                notes=str(m.get("notes", "local_ollama")),
            ))
        for name in discovered:
            if name in seen or f"{name}:latest" in seen or name.replace(":latest", "") in seen:
                continue
            base = CapabilitySet(coding=True, tool_calling=False, latency_tier="medium")
            caps_list.append(ModelCapabilities(
                provider_id=self.provider_id,
                model_id=name,
                display_name=name,
                kind=ProviderKind.LOCAL,
                capabilities=base,
                supports_general=True,
                supports_cline=False,
                cline_tool_calling_verified=False,
                verified=False,
                notes="discovered_unverified",
            ))
        return caps_list

    def _score(self, model: ModelCapabilities, profile: MissionProfile) -> tuple[float, list[str]]:
        c = model.capabilities
        score = 0.0
        reasons: list[str] = []
        if profile.needs_reasoning:
            score += 3.0 if c.reasoning else -1.5
            reasons.append("reasoning" if c.reasoning else "reasoning_unknown")
        if profile.needs_coding:
            score += 3.0 if c.coding else -1.5
            reasons.append("coding" if c.coding else "coding_unknown")
        if profile.needs_tool_calling:
            score += 2.5 if c.tool_calling else -2.5
            reasons.append("tool_calling" if c.tool_calling else "no_tool_calling")
        if profile.needs_vision or profile.needs_document_analysis:
            ok = c.vision or c.document_analysis
            score += 1.5 if ok else -1.0
            reasons.append("vision_doc" if ok else "no_vision_doc")
        if profile.required_context_tokens and c.max_context_tokens:
            score += 1.0 if c.max_context_tokens >= profile.required_context_tokens else -3.0
        score += 0.1 * sum([c.reasoning, c.coding, c.tool_calling])
        return score, reasons

    def select_model(self, profile: MissionProfile, discovered: list[str] | None = None) -> RoutingDecision | None:
        candidates = self.list_candidate_models(discovered=discovered)
        if profile.engine == "cline":
            candidates = [m for m in candidates if m.supports_cline and m.cline_tool_calling_verified]
            ranking_kind = "cline"
        else:
            candidates = [m for m in candidates if m.supports_general]
            ranking_kind = "general"
        if not candidates:
            return None
        if profile.user_override_model:
            for m in candidates:
                key = f"{m.provider_id}:{m.model_id}"
                if profile.user_override_model in {m.model_id, key}:
                    return RoutingDecision(m.provider_id, m.model_id, 100.0, "explicit_user_override", [], profile.engine, ranking_kind)
        scored = []
        for m in candidates:
            s, r = self._score(m, profile)
            scored.append((s, m, r))
        scored.sort(key=lambda x: (-x[0], x[1].model_id))
        best_s, best, reasons = scored[0]
        return RoutingDecision(
            selected_provider=best.provider_id,
            selected_model=best.model_id,
            score=best_s,
            reason=f"best_match_ollama_local; score={best_s:.2f}; factors={','.join(reasons[:6])}",
            fallback_chain=[f"{m.provider_id}:{m.model_id}" for _, m, _ in scored[1:]],
            engine=profile.engine,
            ranking_kind=ranking_kind,
        )

    def classify_error(self, exc: Exception | str, **signals: Any) -> IncidentClassification:
        text = str(exc) if exc is not None else ""
        lower = text.lower()
        timeout = bool(signals.get("timeout")) or isinstance(exc, TimeoutError) or "timeout" in lower or "timed out" in lower
        unavailable = bool(signals.get("provider_unavailable")) or "connection refused" in lower or "did not respond" in lower or "unavailable" in lower
        context_limit = bool(signals.get("context_limit_exceeded")) or "context length" in lower or "too many tokens" in lower
        tool_calling_error = bool(signals.get("tool_calling_error")) or "tool call" in lower or "function call" in lower
        mission_or_code_error = bool(signals.get("mission_or_code_error"))
        return classify_incident(
            error_text=text,
            timeout=timeout,
            provider_unavailable=unavailable,
            tool_calling_error=tool_calling_error or context_limit,
            context_limit_exceeded=context_limit,
            mission_or_code_error=mission_or_code_error,
        )

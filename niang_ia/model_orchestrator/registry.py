from __future__ import annotations

from dataclasses import dataclass, field

from .cline_routing import filter_cline_candidates
from .config import OrchestratorConfig
from .models import CapabilitySet, IncidentKind, ModelCapabilities, ModelRecord, ProviderKind


@dataclass
class ModelRegistry:
    """In-memory registry of models/providers (config + optional discovery input)."""

    records: dict[str, ModelRecord] = field(default_factory=dict)

    @staticmethod
    def model_key(provider_id: str, model_id: str) -> str:
        return f"{provider_id}:{model_id}"

    def register(self, capabilities: ModelCapabilities) -> ModelRecord:
        key = self.model_key(capabilities.provider_id, capabilities.model_id)
        record = ModelRecord(capabilities=capabilities)
        self.records[key] = record
        return record

    def get(self, provider_id: str, model_id: str) -> ModelRecord | None:
        return self.records.get(self.model_key(provider_id, model_id))

    def list_available(self, *, engine: str = "niang") -> list[ModelRecord]:
        items = [r for r in self.records.values() if r.available]
        if engine == "cline":
            items = filter_cline_candidates(items, type("P", (), {"engine": "cline"})())
        return items

    def mark_unavailable(self, provider_id: str, model_id: str, reason: str, until: float | None = None,
                         incident: IncidentKind | None = None) -> None:
        record = self.get(provider_id, model_id)
        if record is None:
            return
        record.available = False
        record.unavailable_reason = reason
        record.temporarily_unavailable_until = until
        record.last_error_kind = incident

    @classmethod
    def from_config(cls, config: OrchestratorConfig, *, ollama_discovered: list[str] | None = None) -> "ModelRegistry":
        registry = cls()
        for provider_id, provider in config.providers.items():
            for model in provider.models or []:
                if not isinstance(model, dict):
                    continue
                model_id = str(model.get("model_id") or model.get("id") or "").strip()
                if not model_id:
                    continue
                kind = ProviderKind(provider.kind) if provider.kind in ProviderKind._value2member_map_ else ProviderKind.FREE_QUOTA
                capset = CapabilitySet(
                    reasoning=bool(model.get("reasoning", False)),
                    coding=bool(model.get("coding", False)),
                    vision=bool(model.get("vision", False)),
                    document_analysis=bool(model.get("document_analysis", False)),
                    tool_calling=bool(model.get("tool_calling", False)),
                    streaming=bool(model.get("streaming", False)),
                    max_context_tokens=model.get("max_context_tokens"),
                    latency_tier=str(model.get("latency_tier", "unknown")),
                )
                caps = ModelCapabilities(
                    provider_id=provider_id,
                    model_id=model_id,
                    display_name=str(model.get("display_name") or model_id),
                    kind=kind,
                    capabilities=capset,
                    supports_general=bool(model.get("supports_general", True)),
                    supports_cline=bool(model.get("supports_cline", False)),
                    cline_tool_calling_verified=bool(model.get("cline_tool_calling_verified", False)),
                    verified=bool(model.get("verified", False)),
                    notes=str(model.get("notes", "")),
                )
                registry.register(caps)
        # Add discovered Ollama models conservatively (unverified, not Cline-eligible by default)
        if ollama_discovered:
            for name in ollama_discovered:
                if registry.get("ollama", name):
                    continue
                registry.register(ModelCapabilities(
                    provider_id="ollama",
                    model_id=name,
                    display_name=name,
                    kind=ProviderKind.LOCAL,
                    capabilities=CapabilitySet(coding=True),
                    supports_general=True,
                    supports_cline=False,
                    cline_tool_calling_verified=False,
                    verified=False,
                    notes="discovered_unverified",
                ))
        return registry

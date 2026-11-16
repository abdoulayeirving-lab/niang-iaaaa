from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProviderConfig:
    provider_id: str
    enabled: bool = False
    kind: str = "free_quota"  # local|free_quota|paid
    paid_allowed: bool = False
    base_url: str = ""
    models: list[dict[str, Any]] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrchestratorConfig:
    mode: str = "auto"  # auto by default
    expert_manual_override: bool = True
    paid_usage_allowed: bool = False  # explicit authorization required before any spend
    default_ranking_kind: str = "general"
    failover_max_attempts: int = 3
    failover_cooldown_seconds: int = 60
    metrics_path: str = ""
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

    @classmethod
    def defaults(cls) -> "OrchestratorConfig":
        return cls()

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "OrchestratorConfig":
        if not isinstance(data, dict):
            return cls.defaults()
        providers_raw = data.get("providers") or {}
        providers: dict[str, ProviderConfig] = {}
        if isinstance(providers_raw, dict):
            for pid, cfg in providers_raw.items():
                if not isinstance(pid, str) or not isinstance(cfg, dict):
                    continue
                kind = str(cfg.get("kind", "free_quota"))
                if kind not in {"local", "free_quota", "paid"}:
                    kind = "free_quota"
                providers[pid] = ProviderConfig(
                    provider_id=pid,
                    enabled=bool(cfg.get("enabled", False)),
                    kind=kind,
                    paid_allowed=bool(cfg.get("paid_allowed", False)),
                    base_url=str(cfg.get("base_url", "")),
                    models=list(cfg.get("models") or []),
                    options=dict(cfg.get("options") or {}),
                )
        mode = str(data.get("mode", "auto"))
        if mode not in {"auto", "expert"}:
            mode = "auto"
        ranking = str(data.get("default_ranking_kind", "general"))
        if ranking not in {"general", "cline"}:
            ranking = "general"
        return cls(
            mode=mode,
            expert_manual_override=bool(data.get("expert_manual_override", True)),
            paid_usage_allowed=bool(data.get("paid_usage_allowed", False)),
            default_ranking_kind=ranking,
            failover_max_attempts=max(1, int(data.get("failover_max_attempts", 3))),
            failover_cooldown_seconds=max(0, int(data.get("failover_cooldown_seconds", 60))),
            metrics_path=str(data.get("metrics_path", "")),
            providers=providers,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "expert_manual_override": self.expert_manual_override,
            "paid_usage_allowed": self.paid_usage_allowed,
            "default_ranking_kind": self.default_ranking_kind,
            "failover_max_attempts": self.failover_max_attempts,
            "failover_cooldown_seconds": self.failover_cooldown_seconds,
            "metrics_path": self.metrics_path,
            "providers": {pid: asdict(cfg) for pid, cfg in self.providers.items()},
        }

    def provider_can_spend(self, provider_id: str) -> bool:
        """True only with explicit global and provider-level paid authorization."""
        if not self.paid_usage_allowed:
            return False
        provider = self.providers.get(provider_id)
        if provider is None:
            return False
        return provider.kind == "paid" and provider.enabled and provider.paid_allowed


def load_orchestrator_config(path: str | Path | None = None) -> OrchestratorConfig:
    if path is None:
        path = Path(__file__).resolve().parents[2] / "config" / "model_routing.json"
    path = Path(path)
    if not path.exists():
        return OrchestratorConfig.defaults()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        # Fail safe: defaults keep auto mode and paid usage disabled.
        return OrchestratorConfig.defaults()
    return OrchestratorConfig.from_dict(data)

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class ProviderKind(str, Enum):
    LOCAL = "local"
    FREE_QUOTA = "free_quota"
    PAID = "paid"


class IncidentKind(str, Enum):
    QUOTA_EPUISE = "quota_epuise"
    RATE_LIMIT_TEMPORAIRE = "rate_limit_temporaire"
    PANNE_FOURNISSEUR = "panne_fournisseur"
    TIMEOUT = "timeout"
    ERREUR_TOOL_CALLING = "erreur_tool_calling"
    ERREUR_CODE_MISSION = "erreur_code_mission"


class MeasurementOrigin(str, Enum):
    SIMULE = "simule"
    REEL = "reel"


@dataclass(frozen=True)
class CapabilitySet:
    reasoning: bool = False
    coding: bool = False
    vision: bool = False
    document_analysis: bool = False
    tool_calling: bool = False
    streaming: bool = False
    max_context_tokens: int | None = None
    latency_tier: str = "unknown"  # low|medium|high|unknown


@dataclass(frozen=True)
class ModelCapabilities:
    provider_id: str
    model_id: str
    display_name: str = ""
    kind: ProviderKind = ProviderKind.FREE_QUOTA
    capabilities: CapabilitySet = field(default_factory=CapabilitySet)
    supports_general: bool = True
    supports_cline: bool = False
    cline_tool_calling_verified: bool = False
    verified: bool = False
    verification_origin: MeasurementOrigin | None = None
    notes: str = ""


@dataclass(frozen=True)
class MissionProfile:
    mission_id: str = ""
    mission_type: str = "general"  # general|cline|analysis|...
    difficulty: str = "unknown"
    needs_reasoning: bool = False
    needs_coding: bool = False
    needs_vision: bool = False
    needs_document_analysis: bool = False
    needs_tool_calling: bool = False
    required_context_tokens: int | None = None
    preferred_latency: str = "balanced"  # fast|balanced|quality
    engine: str = "niang"  # niang|cline
    user_override_model: str | None = None
    allow_paid: bool = False


@dataclass
class ModelRecord:
    capabilities: ModelCapabilities
    available: bool = True
    temporarily_unavailable_until: float | None = None
    unavailable_reason: str = ""
    quota_state: str = "unknown"  # ok|limited|exhausted|unknown
    last_error_kind: IncidentKind | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingDecision:
    selected_provider: str | None
    selected_model: str | None
    score: float = 0.0
    reason: str = ""
    fallback_chain: list[str] = field(default_factory=list)
    engine: str = "niang"
    ranking_kind: str = "general"  # general|cline
    simulated: bool = False


@dataclass(frozen=True)
class FailoverEvent:
    timestamp: float
    mission_id: str
    from_model: str | None
    to_model: str | None
    incident: IncidentKind
    detail: str = ""
    safe_to_retry_step: bool = False
    origin: MeasurementOrigin = MeasurementOrigin.SIMULE


@dataclass(frozen=True)
class ResumeCheckpoint:
    step_id: str
    description: str
    status: str = "unknown"  # completed|in_progress|unknown|failed
    side_effects_possible: bool = True
    workspace_verification_required: bool = True
    replay_allowed: bool = False


@dataclass(frozen=True)
class HandoffContext:
    mission_id: str
    objective: str
    mission_history_summary: str = ""
    actions_completed: list[dict[str, Any]] = field(default_factory=list)
    files_created_or_modified: list[str] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    errors_encountered: list[dict[str, Any]] = field(default_factory=list)
    approvals_state: dict[str, Any] = field(default_factory=dict)
    next_step: str = ""
    checkpoints: list[ResumeCheckpoint] = field(default_factory=list)
    workspace_verification_required: bool = True
    uncertain_actions_must_not_be_replayed: bool = True
    source_model: str | None = None
    target_model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["checkpoints"] = [asdict(cp) for cp in self.checkpoints]
        return payload


class FailoverAction(str, Enum):
    NO_SWITCH = "no_switch"
    RETRY = "retry"
    RETRY_WITH_BACKOFF = "retry_with_backoff"
    COOLDOWN_AND_SWITCH = "cooldown_and_switch"
    SWITCH = "switch"
    ABORT = "abort"


@dataclass(frozen=True)
class AttemptRecord:
    mission_id: str
    provider_id: str | None
    model_id: str | None
    incident: IncidentKind | None = None
    action: str = ""
    timestamp: float = 0.0


@dataclass
class CooldownState:
    unavailable_until: float = 0.0
    reason: str = ""
    incident: IncidentKind | None = None


@dataclass(frozen=True)
class FailoverPlan:
    action: FailoverAction
    incident: IncidentKind
    reason: str
    from_provider: str | None = None
    from_model: str | None = None
    to_provider: str | None = None
    to_model: str | None = None
    delay_seconds: float = 0.0
    set_cooldown_seconds: float = 0.0
    safe_to_retry_same_step: bool = False
    requires_workspace_verification: bool = True
    requires_handoff: bool = False
    handoff: HandoffContext | None = None
    exhausted: bool = False
    attempted_models: list[str] = field(default_factory=list)

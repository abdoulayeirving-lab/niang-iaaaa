"""Foundations and orchestration modules for NIANG IA (Phases 1-6, progressive integration).

Phase 1: data models, configuration, incident taxonomy, registry skeleton, metrics/event store.
Phase 2: Gemini adapter facade and single-provider orchestrator entry point.
Phase 3: failover planning, continuity/handoff builders, candidate scoring (isolated).
Phase 4-5: runtime selection/instrumentation and controlled LLM failover (Gemini, NIANG pipeline).
Phase 6: Ollama adapter, Cline-compatibility-aware routing/registry, additive mission continuity metadata.
"""

from .config import OrchestratorConfig, load_orchestrator_config
from .continuity import (
    assess_resume_safety,
    build_handoff_context,
    build_resume_checkpoints,
    has_uncertain_or_unverified_actions,
    validate_handoff_for_resume,
)
from .workspace_verification import (
    TrustedWorkspaceVerifier,
    WorkspaceProof,
    authorize_risky_resume_or_write,
    validate_proof,
)
from .failover import plan_failover
from .execution import FailoverExecutionState, generate_with_failover
from .instrumentation import record_classified_error, record_routing_decision
from .metrics_store import MetricsEventStore
from .models import (
    AttemptRecord,
    CapabilitySet,
    CooldownState,
    FailoverAction,
    FailoverEvent,
    FailoverPlan,
    HandoffContext,
    IncidentKind,
    MeasurementOrigin,
    MissionProfile,
    ModelCapabilities,
    ModelRecord,
    ProviderKind,
    ResumeCheckpoint,
    RoutingDecision,
)
from .orchestrator import ModelOrchestrator
from .providers.base import ProviderAdapter
from .providers.gemini import GeminiAdapter
from .providers.ollama import OllamaAdapter
from .cline_routing import evaluate_cline_model, filter_cline_candidates
from .registry import ModelRegistry
from .scoring import select_best_candidate
from .taxonomy import classify_incident, should_failover

__all__ = [
    "AttemptRecord",
    "CapabilitySet",
    "CooldownState",
    "FailoverAction",
    "FailoverEvent",
    "FailoverExecutionState",
    "FailoverPlan",
    "GeminiAdapter",
    "HandoffContext",
    "IncidentKind",
    "MeasurementOrigin",
    "MetricsEventStore",
    "MissionProfile",
    "ModelCapabilities",
    "ModelOrchestrator",
    "ModelRecord",
    "ModelRegistry",
    "OllamaAdapter",
    "OrchestratorConfig",
    "ProviderAdapter",
    "ProviderKind",
    "ResumeCheckpoint",
    "RoutingDecision",
    "build_handoff_context",
    "build_resume_checkpoints",
    "classify_incident",
    "evaluate_cline_model",
    "filter_cline_candidates",
    "generate_with_failover",
    "load_orchestrator_config",
    "plan_failover",
    "record_classified_error",
    "record_routing_decision",
    "select_best_candidate",
    "should_failover",
    "TrustedWorkspaceVerifier",
    "WorkspaceProof",
    "assess_resume_safety",
    "authorize_risky_resume_or_write",
    "has_uncertain_or_unverified_actions",
    "validate_handoff_for_resume",
    "validate_proof",
]

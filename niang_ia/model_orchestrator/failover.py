from __future__ import annotations

import time
from typing import Any

from .config import OrchestratorConfig
from .continuity import build_handoff_context
from .models import (
    AttemptRecord,
    CooldownState,
    FailoverAction,
    FailoverPlan,
    HandoffContext,
    IncidentKind,
    MeasurementOrigin,
    MissionProfile,
    ModelRecord,
)
from .scoring import model_key, select_best_candidate
from .taxonomy import IncidentClassification, should_failover


# Conservative defaults per incident kind (seconds)
_DEFAULT_BACKOFF = {
    IncidentKind.RATE_LIMIT_TEMPORAIRE: 5.0,
    IncidentKind.PANNE_FOURNISSEUR: 3.0,
    IncidentKind.TIMEOUT: 2.0,
}
_DEFAULT_COOLDOWN = {
    IncidentKind.QUOTA_EPUISE: 1800.0,
    IncidentKind.PANNE_FOURNISSEUR: 60.0,
    IncidentKind.ERREUR_TOOL_CALLING: 300.0,
    IncidentKind.TIMEOUT: 30.0,
    IncidentKind.RATE_LIMIT_TEMPORAIRE: 30.0,
}


def _is_retryable_without_switch(incident: IncidentKind) -> bool:
    return incident in {
        IncidentKind.RATE_LIMIT_TEMPORAIRE,
        IncidentKind.PANNE_FOURNISSEUR,
        IncidentKind.TIMEOUT,
    }


def plan_failover(
    *,
    classification: IncidentClassification,
    profile: MissionProfile,
    current_provider: str | None,
    current_model: str | None,
    candidates: list[ModelRecord],
    attempts: list[AttemptRecord] | None = None,
    cooldowns: dict[str, CooldownState] | None = None,
    config: OrchestratorConfig | None = None,
    now: float | None = None,
    allow_paid: bool = False,
    handoff_base: dict[str, Any] | None = None,
    current_step_state: str = "unknown",  # completed|in_progress|unknown|failed
    measured_history: list[dict[str, Any]] | None = None,
    measured_origin: MeasurementOrigin | None = None,
) -> FailoverPlan:
    """Compute a safe failover/retry plan. Does not execute anything.

    - Never switches model for mission/code errors.
    - Never marks uncertain/in-progress steps as replayable.
    - Selects the best compatible fallback candidate (not first available).
    - Enforces anti-loop budgets and excludes already-attempted models.
    """
    now = time.time() if now is None else now
    cfg = config or OrchestratorConfig.defaults()
    attempts = attempts or []
    cooldowns = cooldowns or {}
    incident = classification.kind
    from_key = model_key(current_provider or "", current_model or "") if current_provider and current_model else None

    # Budget/anti-loop: count prior failover/switch attempts for this mission.
    prior_switches = [a for a in attempts if a.action in {"switch", "cooldown_and_switch", "retry", "retry_with_backoff"}]
    if len(prior_switches) >= max(1, cfg.failover_max_attempts):
        return FailoverPlan(
            action=FailoverAction.ABORT,
            incident=incident,
            reason="failover_budget_exhausted",
            from_provider=current_provider,
            from_model=current_model,
            exhausted=True,
            requires_workspace_verification=True,
            requires_handoff=False,
        )

    if incident == IncidentKind.ERREUR_CODE_MISSION or not should_failover(incident):
        return FailoverPlan(
            action=FailoverAction.NO_SWITCH,
            incident=incident,
            reason="no_model_failover_for_mission_or_code_error" if incident == IncidentKind.ERREUR_CODE_MISSION else "incident_not_failover_candidate",
            from_provider=current_provider,
            from_model=current_model,
            safe_to_retry_same_step=False,
            requires_workspace_verification=True,
            requires_handoff=False,
        )

    # Determine if same-model retry is reasonable before switching (bounded by attempts).
    same_model_attempts = [
        a for a in attempts
        if model_key(a.provider_id or "", a.model_id or "") == from_key and a.incident == incident
    ]
    can_retry_same = _is_retryable_without_switch(incident) and len(same_model_attempts) == 0
    # Rate limit/timeout/5xx: one bounded backoff retry on same model, then switch if still failing.
    if can_retry_same and current_step_state in {"completed", "not_started"}:
        delay = _DEFAULT_BACKOFF.get(incident, 2.0)
        return FailoverPlan(
            action=FailoverAction.RETRY_WITH_BACKOFF,
            incident=incident,
            reason=f"transient_incident_backoff_before_switch:{incident.value}",
            from_provider=current_provider,
            from_model=current_model,
            to_provider=current_provider,
            to_model=current_model,
            delay_seconds=delay,
            safe_to_retry_same_step=True,
            requires_workspace_verification=False,
            requires_handoff=False,
        )

    # For uncertain/in-progress steps or non-retryable incidents: switch to best compatible fallback.
    excluded = set()
    for a in attempts:
        if a.provider_id and a.model_id:
            excluded.add(model_key(a.provider_id, a.model_id))
    # Also exclude current model on quota/tool-calling/provider fatal incompatibility contexts.
    if from_key and incident in {IncidentKind.QUOTA_EPUISE, IncidentKind.ERREUR_TOOL_CALLING, IncidentKind.PANNE_FOURNISSEUR}:
        excluded.add(from_key)
    # Apply cooldowns
    effective_candidates: list[ModelRecord] = []
    for c in candidates:
        key = model_key(c.capabilities.provider_id, c.capabilities.model_id)
        cd = cooldowns.get(key)
        if cd and cd.unavailable_until > now:
            continue
        effective_candidates.append(c)

    config_paid_ok = {pid: (cfg.provider_can_spend(pid)) for pid in {c.capabilities.provider_id for c in effective_candidates}}
    best, score, reasons = select_best_candidate(
        effective_candidates,
        profile,
        now=now,
        allow_paid=allow_paid,
        config_paid_ok=config_paid_ok,
        excluded_model_keys=excluded,
        measured_history=measured_history,
        measured_origin=measured_origin,
    )

    if best is None:
        return FailoverPlan(
            action=FailoverAction.ABORT,
            incident=incident,
            reason="no_eligible_fallback_model_available",
            from_provider=current_provider,
            from_model=current_model,
            exhausted=True,
            requires_workspace_verification=True,
            requires_handoff=False,
            attempted_models=sorted(excluded),
        )

    to_provider = best.capabilities.provider_id
    to_model = best.capabilities.model_id
    cooldown_s = _DEFAULT_COOLDOWN.get(incident, cfg.failover_cooldown_seconds)
    handoff: HandoffContext | None = None
    requires_handoff = True
    base = handoff_base or {}
    handoff = build_handoff_context(
        mission_id=str(base.get("mission_id") or profile.mission_id or ""),
        objective=str(base.get("objective") or ""),
        mission_history_summary=str(base.get("mission_history_summary") or ""),
        actions_completed=list(base.get("actions_completed") or []),
        files_created_or_modified=list(base.get("files_created_or_modified") or []),
        tool_results=list(base.get("tool_results") or []),
        errors_encountered=list(base.get("errors_encountered") or []),
        approvals_state=dict(base.get("approvals_state") or {}),
        next_step=str(base.get("next_step") or "verify_workspace_state_before_any_write"),
        source_model=from_key,
        target_model=model_key(to_provider, to_model),
    )

    return FailoverPlan(
        action=FailoverAction.COOLDOWN_AND_SWITCH if cooldown_s > 0 else FailoverAction.SWITCH,
        incident=incident,
        reason=f"switch_to_best_compatible_fallback;score={score:.2f};factors={','.join(reasons[:6])}",
        from_provider=current_provider,
        from_model=current_model,
        to_provider=to_provider,
        to_model=to_model,
        delay_seconds=0.0,
        set_cooldown_seconds=cooldown_s,
        safe_to_retry_same_step=False,
        requires_workspace_verification=True,
        requires_handoff=requires_handoff,
        handoff=handoff,
        exhausted=False,
        attempted_models=sorted(excluded),
    )

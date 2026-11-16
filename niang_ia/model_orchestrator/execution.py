from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import api_keys
from .config import OrchestratorConfig, load_orchestrator_config
from .failover import plan_failover
from .models import AttemptRecord, CooldownState, FailoverAction, IncidentKind, MeasurementOrigin, MissionProfile, ModelRecord, ProviderKind
from .providers.gemini import GeminiAdapter
from .scoring import model_key
from .taxonomy import classify_incident


@dataclass
class FailoverExecutionState:
    mission_id: str = ""
    attempts: list[AttemptRecord] = field(default_factory=list)
    cooldowns: dict[str, CooldownState] = field(default_factory=dict)
    incident_history: list[dict[str, Any]] = field(default_factory=list)
    active_provider: str | None = None
    active_model: str | None = None
    handoffs: list[dict[str, Any]] = field(default_factory=list)
    workspace_verification_required: bool = False
    last_checkpoint: dict[str, Any] = field(default_factory=dict)


def _handoff_prefix(handoff: Any) -> str:
    if handoff is None:
        return ""
    try:
        data = handoff.to_dict() if hasattr(handoff, "to_dict") else handoff
        summary = json.dumps(data, ensure_ascii=False)[:4000]
        return (
            "CONTEXTE DE REPRISE (handoff structuré, vérifié côté orchestration):\n"
            f"{summary}\n\n"
            "INSTRUCTIONS DE SÉCURITÉ: ne rejoue aucune action incertaine ou en cours; "
            "vérifie l'état du workspace avant toute écriture/reprise; "
            "aucune reprise d'écriture sans vérification explicite.\n\n"
            "TÂCHE À CONTINUER:\n"
        )
    except Exception:
        return ""


def _model_records_from_adapter(adapter: GeminiAdapter, now: float, state: FailoverExecutionState) -> list[ModelRecord]:
    records: list[ModelRecord] = []
    for caps in adapter.list_candidate_models():
        key = model_key(caps.provider_id, caps.model_id)
        cd = state.cooldowns.get(key)
        unavailable_until = cd.unavailable_until if cd and cd.unavailable_until > now else None
        quota_state = "exhausted" if cd and cd.incident == IncidentKind.QUOTA_EPUISE and unavailable_until else "ok"
        records.append(
            ModelRecord(
                capabilities=caps,
                available=unavailable_until is None,
                temporarily_unavailable_until=unavailable_until,
                unavailable_reason=cd.reason if cd and unavailable_until else "",
                quota_state=quota_state,
                last_error_kind=cd.incident if cd and unavailable_until else None,
            )
        )
    return records


def _status_code_from_exc(exc: Exception) -> int | None:
    for attr in ("status_code", "code"):
        val = getattr(exc, attr, None)
        if isinstance(val, int):
            return val
    resp = getattr(exc, "response", None)
    if resp is not None:
        val = getattr(resp, "status_code", None)
        if isinstance(val, int):
            return val
    return None


def generate_with_failover(
    *,
    contents: Any,
    config: Any = None,
    api_version: str | None = None,
    timeout_ms: int | None = None,
    profile: MissionProfile,
    fallback_model_name: str,
    allow_paid: bool = False,
    handoff_base: dict[str, Any] | None = None,
    state: FailoverExecutionState | None = None,
    origin: MeasurementOrigin = MeasurementOrigin.SIMULE,
    orchestrator_config: OrchestratorConfig | None = None,
    time_fn: Callable[[], float] = time.time,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[Any, FailoverExecutionState, str, str]:
    """Execute a Gemini generation with controlled failover planning/execution.

    Returns (response, state, provider_id, model_id).
    - No switch on mission/code errors.
    - Bounded attempts/bascules, no uncertain action replay.
    - No paid provider/model without explicit authorization.
    - Reuses api_keys.generate_with_retry for actual Gemini calls.
    """
    cfg = orchestrator_config or load_orchestrator_config()
    adapter = GeminiAdapter(cfg)
    state = state or FailoverExecutionState(mission_id=profile.mission_id)
    if not state.mission_id:
        state.mission_id = profile.mission_id

    # Initial model selection (best for mission) with safe fallback, respecting state cooldowns/quota.
    now = time_fn()
    candidates = _model_records_from_adapter(adapter, now, state)
    from .scoring import select_best_candidate
    config_paid_ok = {pid: cfg.provider_can_spend(pid) for pid in {c.capabilities.provider_id for c in candidates}}
    best, _, _ = select_best_candidate(candidates, profile, now=now, allow_paid=allow_paid, config_paid_ok=config_paid_ok)
    current_model = fallback_model_name
    current_provider = "gemini"
    if best is not None:
        current_model = best.capabilities.model_id
        current_provider = best.capabilities.provider_id
    elif candidates:
        # fallback to any non-cooled-down candidate or configured fallback
        for c in candidates:
            if c.available and c.quota_state != "exhausted":
                current_model = c.capabilities.model_id
                current_provider = c.capabilities.provider_id
                break
    state.active_provider = current_provider
    state.active_model = current_model

    max_loops = max(1, cfg.failover_max_attempts) + 3
    current_contents = contents
    # Preserve mission identity/history continuity hints for failover planning/handoff.
    safe_handoff_base = dict(handoff_base or {})
    if state.mission_id and "mission_id" not in safe_handoff_base:
        safe_handoff_base["mission_id"] = state.mission_id
    if profile.mission_id and "mission_id" not in safe_handoff_base:
        safe_handoff_base["mission_id"] = profile.mission_id
    safe_handoff_base.setdefault("workspace_verification_required", True)
    for _ in range(max_loops):
        now = time_fn()
        key = model_key(current_provider, current_model)
        cd = state.cooldowns.get(key)
        if cd and cd.unavailable_until > now:
            classification = classify_incident(provider_unavailable=True, error_text="model in cooldown")
            plan = plan_failover(
                classification=classification,
                profile=profile,
                current_provider=current_provider,
                current_model=current_model,
                candidates=_model_records_from_adapter(adapter, now, state),
                attempts=state.attempts,
                cooldowns=state.cooldowns,
                config=cfg,
                now=now,
                allow_paid=allow_paid,
                handoff_base=safe_handoff_base,
                current_step_state="unknown_unverified",
            )
            # Never retry the same cooled-down model; force switch/abort.
            if plan.action == FailoverAction.RETRY_WITH_BACKOFF:
                state.attempts.append(AttemptRecord(state.mission_id, current_provider, current_model, classification.kind, "cooldown_skip", now))
                plan = plan_failover(
                    classification=classification,
                    profile=profile,
                    current_provider=current_provider,
                    current_model=current_model,
                    candidates=_model_records_from_adapter(adapter, now, state),
                    attempts=state.attempts,
                    cooldowns=state.cooldowns,
                    config=cfg,
                    now=now,
                    allow_paid=allow_paid,
                    handoff_base=safe_handoff_base,
                    current_step_state="unknown_unverified",
                )
            if plan.action == FailoverAction.ABORT:
                state.incident_history.append({"incident": plan.incident.value, "action": plan.action.value, "reason": plan.reason, "from": key, "to": None, "ts": now})
                raise RuntimeError(f"No eligible fallback model available: {plan.reason}")
            if plan.to_model and plan.action in {FailoverAction.SWITCH, FailoverAction.COOLDOWN_AND_SWITCH}:
                if plan.set_cooldown_seconds > 0 and current_provider and current_model:
                    state.cooldowns[key] = CooldownState(now + plan.set_cooldown_seconds, plan.reason, plan.incident)
                state.attempts.append(AttemptRecord(state.mission_id, current_provider, current_model, plan.incident, plan.action.value, now))
                state.incident_history.append({"incident": plan.incident.value, "action": plan.action.value, "reason": plan.reason, "from": key, "to": model_key(plan.to_provider or "", plan.to_model or ""), "ts": now})
                if plan.handoff:
                    hdata = plan.handoff.to_dict() if hasattr(plan.handoff, "to_dict") else plan.handoff
                    state.handoffs.append(hdata)
                    state.workspace_verification_required = True
                    state.last_checkpoint = {"from": key, "to": model_key(plan.to_provider or "", plan.to_model or ""), "ts": now, "status": "handoff_pending_verification"}
                    current_contents = _handoff_prefix(plan.handoff) + (contents if isinstance(contents, str) else str(contents))
                current_provider = plan.to_provider or current_provider
                current_model = plan.to_model or current_model
                state.active_provider, state.active_model = current_provider, current_model
                continue
            # If no valid switch plan, abort safely
            state.incident_history.append({"incident": classification.kind.value, "action": "abort", "reason": "cooldown_no_switch_path", "from": key, "to": None, "ts": now})
            raise RuntimeError("No eligible fallback model available: cooldown_no_switch_path")

        try:
            response = api_keys.generate_with_retry(
                current_model,
                current_contents,
                config=config,
                api_version=api_version,
                timeout_ms=timeout_ms,
            )
            return response, state, current_provider, current_model
        except Exception as exc:
            now = time_fn()
            status_code = _status_code_from_exc(exc)
            text = str(exc)
            lower = text.lower()
            quota_exhausted = "resource_exhausted" in lower or "insufficient_quota" in lower or "daily quota" in lower or ("quota" in lower and "429" in lower)
            rate_limited = (status_code == 429 and not quota_exhausted) or ("too many requests" in lower and not quota_exhausted)
            timeout = isinstance(exc, TimeoutError) or "timeout" in lower or "timed out" in lower
            provider_unavailable = (
                (isinstance(status_code, int) and 500 <= status_code <= 599)
                or any(tok in lower for tok in (" 500", " 502", " 503", " 504", "internal server error", "bad gateway", "service unavailable", "gateway timeout"))
                or status_code is None and any(code in lower for code in ("500", "502", "503", "504")) and "429" not in lower
                or "unavailable" in lower or "connection refused" in lower or "connection reset" in lower
            )
            tool_calling_error = "tool call" in lower or "function call" in lower or "invalid argument" in lower
            context_limit = "context length" in lower or ("token" in lower and "exceed" in lower)
            # Mission/code errors must never trigger model failover.
            mission_or_code_error = isinstance(exc, (SyntaxError, NameError, TypeError, ValueError, KeyError, AttributeError, AssertionError)) and not (timeout or provider_unavailable or quota_exhausted or rate_limited)
            classification = classify_incident(
                status_code=status_code,
                error_text=text,
                timeout=timeout,
                provider_unavailable=provider_unavailable,
                quota_exhausted=quota_exhausted,
                rate_limited=rate_limited,
                tool_calling_error=tool_calling_error or context_limit,
                context_limit_exceeded=context_limit,
                mission_or_code_error=mission_or_code_error,
            )
            plan = plan_failover(
                classification=classification,
                profile=profile,
                current_provider=current_provider,
                current_model=current_model,
                candidates=_model_records_from_adapter(adapter, now, state),
                attempts=state.attempts,
                cooldowns=state.cooldowns,
                config=cfg,
                now=now,
                allow_paid=allow_paid,
                handoff_base=safe_handoff_base,
                current_step_state="unknown_unverified",
            )
            state.attempts.append(AttemptRecord(state.mission_id, current_provider, current_model, classification.kind, plan.action.value, now))
            if plan.set_cooldown_seconds > 0 and current_provider and current_model and plan.action in {FailoverAction.COOLDOWN_AND_SWITCH, FailoverAction.SWITCH, FailoverAction.ABORT}:
                state.cooldowns[model_key(current_provider, current_model)] = CooldownState(now + plan.set_cooldown_seconds, plan.reason, classification.kind)
            state.incident_history.append({
                "incident": classification.kind.value,
                "action": plan.action.value,
                "reason": plan.reason,
                "from": model_key(current_provider, current_model),
                "to": model_key(plan.to_provider or "", plan.to_model or "") if plan.to_model else None,
                "error": text[:300],
                "ts": now,
            })

            if plan.action == FailoverAction.NO_SWITCH:
                raise
            if plan.action == FailoverAction.ABORT:
                raise RuntimeError(f"No eligible fallback model available: {plan.reason}") from exc
            if plan.action == FailoverAction.RETRY_WITH_BACKOFF:
                if plan.delay_seconds > 0:
                    sleep_fn(plan.delay_seconds)
                continue
            if plan.action in {FailoverAction.SWITCH, FailoverAction.COOLDOWN_AND_SWITCH} and plan.to_model:
                if plan.handoff:
                    hdata = plan.handoff.to_dict() if hasattr(plan.handoff, "to_dict") else plan.handoff
                    state.handoffs.append(hdata)
                    state.workspace_verification_required = True
                    state.last_checkpoint = {"from": model_key(current_provider, current_model), "to": model_key(plan.to_provider or current_provider, plan.to_model), "ts": now, "status": "handoff_pending_verification"}
                    current_contents = _handoff_prefix(plan.handoff) + (contents if isinstance(contents, str) else str(contents))
                current_provider = plan.to_provider or current_provider
                current_model = plan.to_model
                state.active_provider, state.active_model = current_provider, current_model
                continue
            raise

    raise RuntimeError("Failover execution budget exhausted.")

from __future__ import annotations

import time
from typing import Any

from .models import MeasurementOrigin, MissionProfile, ModelRecord, ProviderKind


def model_key(provider_id: str, model_id: str) -> str:
    return f"{provider_id}:{model_id}"


def _is_paid_blocked(record: ModelRecord, allow_paid: bool, config_paid_ok: bool) -> bool:
    if record.capabilities.kind != ProviderKind.PAID:
        return False
    # Paid candidates require explicit per-call authorization and config authorization.
    return not (allow_paid and config_paid_ok)


def _compatible_for_engine(record: ModelRecord, engine: str) -> bool:
    if engine == "cline":
        caps = record.capabilities
        return bool(caps.supports_cline and caps.cline_tool_calling_verified)
    return bool(record.capabilities.supports_general)


def _on_cooldown(record: ModelRecord, now: float) -> bool:
    until = record.temporarily_unavailable_until
    return bool(until and until > now)


def _measured_bonus(
    history: list[dict[str, Any]] | None,
    provider_id: str,
    model_id: str,
    origin: MeasurementOrigin | None,
) -> float:
    """Deterministic bonus from measured history; respects simule/reel separation.

    If origin is provided, only matching-origin records contribute. Callers must
    not mix simulated evidence into real ranking decisions.
    """
    if not history:
        return 0.0
    key = model_key(provider_id, model_id)
    relevant = []
    for item in history:
        if not isinstance(item, dict):
            continue
        item_key = item.get("model_key")
        if item_key is not None:
            if item_key != key:
                continue
        else:
            if (item.get("provider_id"), item.get("model_id")) != (provider_id, model_id):
                continue
        if origin is not None and item.get("origin") != origin.value:
            continue
        relevant.append(item)
    if not relevant:
        return 0.0
    successes = sum(1 for r in relevant if r.get("success") is True)
    rate = successes / max(1, len(relevant))
    # Small bounded influence; ranking remains primarily capability/health driven.
    return min(1.0, max(-1.0, (rate - 0.5) * 2.0))


def score_candidate(
    record: ModelRecord,
    profile: MissionProfile,
    *,
    now: float | None = None,
    allow_paid: bool = False,
    config_paid_ok_for_provider: bool = False,
    excluded_model_keys: set[str] | None = None,
    measured_history: list[dict[str, Any]] | None = None,
    measured_origin: MeasurementOrigin | None = None,
) -> tuple[float, list[str], bool]:
    """Return (score, reasons, eligible). Higher score is better."""
    now = time.time() if now is None else now
    excluded_model_keys = excluded_model_keys or set()
    key = model_key(record.capabilities.provider_id, record.capabilities.model_id)
    reasons: list[str] = []
    if key in excluded_model_keys:
        return -10_000.0, ["excluded_already_attempted"], False
    if not record.available or _on_cooldown(record, now):
        return -10_000.0, ["temporarily_unavailable"], False
    if record.quota_state == "exhausted":
        return -10_000.0, ["quota_exhausted"], False
    if _is_paid_blocked(record, allow_paid, config_paid_ok_for_provider):
        return -10_000.0, ["paid_not_authorized"], False
    if not _compatible_for_engine(record, profile.engine):
        return -10_000.0, [f"incompatible_engine_{profile.engine}"], False

    c = record.capabilities.capabilities
    score = 0.0
    if profile.needs_reasoning:
        score += 3.0 if c.reasoning else -2.0
        reasons.append("reasoning" if c.reasoning else "no_reasoning")
    if profile.needs_coding:
        score += 3.0 if c.coding else -1.5
        reasons.append("coding" if c.coding else "weak_coding")
    if profile.needs_vision or profile.needs_document_analysis:
        ok = c.vision or c.document_analysis
        score += 2.0 if ok else -1.0
        reasons.append("vision_doc" if ok else "no_vision_doc")
    if profile.needs_tool_calling:
        score += 2.5 if c.tool_calling else -2.5
        reasons.append("tool_calling" if c.tool_calling else "no_tool_calling")
    if profile.required_context_tokens and c.max_context_tokens:
        if c.max_context_tokens >= profile.required_context_tokens:
            score += 1.0
            reasons.append("context_ok")
        else:
            score -= 4.0
            reasons.append("context_too_small")
    if profile.preferred_latency == "fast":
        score += 1.0 if c.latency_tier == "low" else 0.0
    elif profile.preferred_latency == "quality":
        score += 0.5 if c.reasoning else 0.0
    score += 0.1 * sum([c.reasoning, c.coding, c.tool_calling, c.vision, c.document_analysis])

    # Measured evidence (separated by origin when specified).
    score += _measured_bonus(measured_history, record.capabilities.provider_id, record.capabilities.model_id, measured_origin)
    if record.quota_state == "limited":
        score -= 0.5
        reasons.append("quota_limited")
    return score, reasons, True


def select_best_candidate(
    candidates: list[ModelRecord],
    profile: MissionProfile,
    *,
    now: float | None = None,
    allow_paid: bool = False,
    config_paid_ok: dict[str, bool] | None = None,
    excluded_model_keys: set[str] | None = None,
    measured_history: list[dict[str, Any]] | None = None,
    measured_origin: MeasurementOrigin | None = None,
) -> tuple[ModelRecord | None, float, list[str]]:
    config_paid_ok = config_paid_ok or {}
    best: ModelRecord | None = None
    best_score = -10_000.0
    best_reasons: list[str] = []
    for record in candidates:
        provider_id = record.capabilities.provider_id
        score, reasons, eligible = score_candidate(
            record,
            profile,
            now=now,
            allow_paid=allow_paid,
            config_paid_ok_for_provider=config_paid_ok.get(provider_id, False),
            excluded_model_keys=excluded_model_keys,
            measured_history=measured_history,
            measured_origin=measured_origin,
        )
        if not eligible:
            continue
        # Deterministic tie-breaker: higher score, then provider/model id.
        if best is None or score > best_score or (score == best_score and model_key(provider_id, record.capabilities.model_id) < model_key(best.capabilities.provider_id, best.capabilities.model_id)):
            best = record
            best_score = score
            best_reasons = reasons
    if best is None:
        return None, -10_000.0, ["no_eligible_candidate"]
    return best, best_score, best_reasons

from __future__ import annotations

from dataclasses import dataclass

from .models import IncidentKind


@dataclass(frozen=True)
class IncidentClassification:
    kind: IncidentKind
    retryable: bool
    failover_candidate: bool
    reason: str


_NON_FAILOVER = {
    # A code/mission error must not trigger an automatic model switch.
    IncidentKind.ERREUR_CODE_MISSION,
}

_FAILOVER_CANDIDATES = {
    IncidentKind.QUOTA_EPUISE,
    IncidentKind.RATE_LIMIT_TEMPORAIRE,
    IncidentKind.PANNE_FOURNISSEUR,
    IncidentKind.TIMEOUT,
    IncidentKind.ERREUR_TOOL_CALLING,
}


def should_failover(kind: IncidentKind) -> bool:
    return kind in _FAILOVER_CANDIDATES and kind not in _NON_FAILOVER


def classify_incident(
    *,
    status_code: int | None = None,
    error_text: str = "",
    timeout: bool = False,
    provider_unavailable: bool = False,
    quota_exhausted: bool = False,
    rate_limited: bool = False,
    tool_calling_error: bool = False,
    context_limit_exceeded: bool = False,
    mission_or_code_error: bool = False,
) -> IncidentClassification:
    """Normalize an incident into one of the required categories.

    Classification is deterministic and side-effect free. Callers must provide
    accurate flags derived from verified runtime signals; this function does not
    inspect external systems.
    """
    text = (error_text or "").lower()

    if mission_or_code_error:
        return IncidentClassification(
            IncidentKind.ERREUR_CODE_MISSION,
            retryable=False,
            failover_candidate=False,
            reason="mission_or_code_error",
        )

    if quota_exhausted or status_code == 402 or "insufficient_quota" in text:
        return IncidentClassification(
            IncidentKind.QUOTA_EPUISE,
            retryable=False,
            failover_candidate=True,
            reason="quota_exhausted",
        )

    if rate_limited or status_code == 429 or "rate limit" in text or "too many requests" in text:
        return IncidentClassification(
            IncidentKind.RATE_LIMIT_TEMPORAIRE,
            retryable=True,
            failover_candidate=True,
            reason="rate_limited",
        )

    if provider_unavailable or (status_code is not None and 500 <= status_code <= 599):
        return IncidentClassification(
            IncidentKind.PANNE_FOURNISSEUR,
            retryable=True,
            failover_candidate=True,
            reason="provider_unavailable",
        )

    if timeout or "timeout" in text or "timed out" in text:
        return IncidentClassification(
            IncidentKind.TIMEOUT,
            retryable=True,
            failover_candidate=True,
            reason="timeout",
        )

    if tool_calling_error or "tool call" in text or "function call" in text or "schema" in text:
        return IncidentClassification(
            IncidentKind.ERREUR_TOOL_CALLING,
            retryable=False,
            failover_candidate=True,
            reason="tool_calling_error",
        )

    if context_limit_exceeded or "context length" in text or "too many tokens" in text:
        # Context overflow is treated as a model-capacity incompatibility for failover routing.
        return IncidentClassification(
            IncidentKind.ERREUR_TOOL_CALLING,
            retryable=False,
            failover_candidate=True,
            reason="context_limit_exceeded",
        )

    # Default to mission/code error to avoid accidental model failover.
    return IncidentClassification(
        IncidentKind.ERREUR_CODE_MISSION,
        retryable=False,
        failover_candidate=False,
        reason="unclassified_default_no_failover",
    )

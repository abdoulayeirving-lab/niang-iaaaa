from __future__ import annotations

from typing import Any

from .models import HandoffContext, ResumeCheckpoint

# Resume is only allowed when caller explicitly confirms workspace/state verification.
# This module never inspects the filesystem or infers verification.


_SAFE_COPY_LIMIT = 100


def _safe_list(values: list[Any] | None, limit: int = _SAFE_COPY_LIMIT) -> list[Any]:
    if not values:
        return []
    return list(values[:limit])


def build_resume_checkpoints(actions: list[dict[str, Any]] | None) -> list[ResumeCheckpoint]:
    checkpoints: list[ResumeCheckpoint] = []
    for idx, action in enumerate(_safe_list(actions or []), start=1):
        if not isinstance(action, dict):
            continue
        status = str(action.get("status", "unknown"))
        if status in {"completed", "done", "success", "ok"}:
            normalized = "completed"
            replay_allowed = False
        elif status in {"failed", "error"}:
            normalized = "failed"
            replay_allowed = False
        elif status in {"in_progress", "running"}:
            normalized = "in_progress"
            replay_allowed = False
        else:
            normalized = "unknown"
            replay_allowed = False
        uncertain = normalized in {"unknown", "in_progress"}
        checkpoints.append(
            ResumeCheckpoint(
                step_id=str(action.get("id") or action.get("step_id") or idx),
                description=str(action.get("description") or action.get("tool") or action.get("name") or "action"),
                status=normalized,
                side_effects_possible=bool(action.get("side_effects_possible", True)),
                workspace_verification_required=True,
                replay_allowed=False if uncertain or bool(action.get("side_effects_possible", True)) else replay_allowed,
            )
        )
    return checkpoints


def build_handoff_context(
    *,
    mission_id: str,
    objective: str,
    mission_history_summary: str = "",
    actions_completed: list[dict[str, Any]] | None = None,
    files_created_or_modified: list[str] | None = None,
    tool_results: list[dict[str, Any]] | None = None,
    errors_encountered: list[dict[str, Any]] | None = None,
    approvals_state: dict[str, Any] | None = None,
    next_step: str = "",
    source_model: str | None = None,
    target_model: str | None = None,
    checkpoints: list[ResumeCheckpoint] | None = None,
) -> HandoffContext:
    """Build a structured, safety-oriented handoff for a fallback model.

    The handoff explicitly requires workspace verification and forbids replay of
    uncertain/in-progress actions. Callers must provide verified state; this
    function does not inspect the workspace.
    """
    cps = checkpoints if checkpoints is not None else build_resume_checkpoints(actions_completed)
    # Enforce safety invariants regardless of caller input.
    safe_cps: list[ResumeCheckpoint] = []
    for cp in cps:
        uncertain = cp.status in {"unknown", "in_progress"}
        safe_cps.append(
            ResumeCheckpoint(
                step_id=cp.step_id,
                description=cp.description,
                status=cp.status,
                side_effects_possible=cp.side_effects_possible,
                workspace_verification_required=True,
                replay_allowed=False if (uncertain or cp.side_effects_possible) else False,
            )
        )
    return HandoffContext(
        mission_id=mission_id,
        objective=objective,
        mission_history_summary=mission_history_summary,
        actions_completed=_safe_list(actions_completed or []),
        files_created_or_modified=[str(x) for x in _safe_list(files_created_or_modified or [])],
        tool_results=_safe_list(tool_results or []),
        errors_encountered=_safe_list(errors_encountered or []),
        approvals_state=dict(approvals_state or {}),
        next_step=next_step or "verify_workspace_state_before_any_write",
        checkpoints=safe_cps,
        workspace_verification_required=True,
        uncertain_actions_must_not_be_replayed=True,
        source_model=source_model,
        target_model=target_model,
    )


def validate_handoff_for_resume(handoff: HandoffContext) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if not handoff.mission_id or not handoff.objective:
        issues.append("missing_mission_identity_or_objective")
    if not handoff.workspace_verification_required:
        issues.append("workspace_verification_must_be_required")
    if not handoff.uncertain_actions_must_not_be_replayed:
        issues.append("uncertain_actions_must_not_be_replayed")
    for cp in handoff.checkpoints:
        if cp.status in {"unknown", "in_progress"} and cp.replay_allowed:
            issues.append(f"uncertain_checkpoint_replay_allowed:{cp.step_id}")
        if cp.side_effects_possible and cp.replay_allowed:
            issues.append(f"side_effect_checkpoint_replay_allowed:{cp.step_id}")
        if not cp.workspace_verification_required:
            issues.append(f"checkpoint_missing_workspace_verification:{cp.step_id}")
    return (len(issues) == 0), issues


def has_uncertain_or_unverified_actions(handoff: HandoffContext) -> bool:
    """Return True when any checkpoint is uncertain/in-progress or requires verification before replay."""
    for cp in handoff.checkpoints:
        if cp.status in {"unknown", "in_progress"}:
            return True
        if cp.side_effects_possible or cp.workspace_verification_required:
            # Side effects require explicit verified state before any replay/write decision.
            return True
    return False


def assess_resume_safety(
    handoff: HandoffContext,
    *,
    workspace_verified: bool = False,
    verification_evidence: str = "",
    proof: Any | None = None,
    mission_id: str | None = None,
    workspace_root: str | None = None,
    require_trusted_proof: bool = False,
) -> tuple[bool, list[str]]:
    """Assess whether resume is allowed.

    Legacy mode (default): accepts explicit caller confirmation + evidence string (Phase 7 behavior).
    Trusted mode (Phase 8A): when `require_trusted_proof=True` or `proof` is provided,
    a verifier-issued WorkspaceProof from real inspection is mandatory; bool/string alone is refused.
    """
    valid, issues = validate_handoff_for_resume(handoff)
    if not valid:
        return False, issues

    if require_trusted_proof or proof is not None:
        try:
            from .workspace_verification import validate_proof
            ok, proof_issues = validate_proof(
                proof,
                mission_id=str(mission_id or handoff.mission_id or ""),
                workspace_root=workspace_root,
            )
        except Exception:
            ok, proof_issues = False, ["workspace_proof_validation_unavailable"]
        if not ok:
            issues.extend(proof_issues)
            if proof is None:
                issues.append("trusted_workspace_proof_required")
            return False, issues
    else:
        if not workspace_verified:
            issues.append("workspace_verification_required_but_not_confirmed")
            return False, issues
        if not str(verification_evidence or "").strip():
            issues.append("workspace_verification_evidence_missing")
            return False, issues

    # Even with verification, uncertain actions must not be replayed; caller must advance safely.
    for cp in handoff.checkpoints:
        if cp.status in {"unknown", "in_progress"} and cp.replay_allowed:
            issues.append(f"uncertain_checkpoint_replay_allowed:{cp.step_id}")
        if cp.side_effects_possible and cp.replay_allowed:
            issues.append(f"side_effect_checkpoint_replay_allowed:{cp.step_id}")
    return (len(issues) == 0), issues

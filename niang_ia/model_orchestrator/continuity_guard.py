from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Mapping

from .continuity import has_uncertain_or_unverified_actions
from .models import HandoffContext
from .workspace_verification import WorkspaceProof, authorize_risky_resume_or_write, validate_proof


# Tools/operations treated as sensitive side effects for continuity-guarded missions.
# Conservative classification: workspace mutations and other state-changing operations.
WORKSPACE_MUTATING_TOOLS = frozenset({
    "workspace_write_file",
    "workspace_edit_file",
    "workspace_apply_patch",
})

WORKSPACE_SIDE_EFFECT_TOOLS = frozenset({
    "workspace_run_check",  # may produce/modify build/test artifacts in workspace
})

FILE_CONTROLLER_MUTATING_ACTIONS = frozenset({
    "write", "create", "create_file", "delete", "remove", "move", "rename",
    "copy", "organize", "undo_organize", "undo", "unzip", "extract", "zip",
    "mkdir", "create_folder",
})

# Broad set of tools that can cause side effects outside workspace or mutate system state.
# For missions explicitly marked workspace_verification_required, these are blocked unless
# continuity proof/state is valid and the operation is allowed by policy.
GENERIC_SIDE_EFFECT_TOOLS = frozenset({
    "file_controller", "cmd_control", "windows_repair", "computer_control",
    "computer_settings", "desktop_control", "install_dependency", "terminal_control",
    "project_execution", "dev_agent", "code_helper", "send_message", "gmail",
    "calendar", "drive", "smart_home_control", "create_presentation",
    "create_document", "create_spreadsheet", "browser_control", "open_app",
    "reminder", "autostart", "task_manager", "clipboard", "media_control",
    "monitor_alerts", "email_watch", "notify", "schedule",
})


@dataclass(frozen=True)
class ContinuityExecutionContext:
    """Trusted continuity context attached by mission runtime (not by model/tool output).

    Frozen to reduce accidental/internal mutation. Immutability is not authentication:
    proof signature/mission/workspace validation remains mandatory when required.
    """

    mission_id: str
    workspace_root: str = ""
    workspace_proof: Any = None  # WorkspaceProof or serialized mapping
    checkpoint: Any = None  # HandoffContext/dict/summary
    workspace_verification_required: bool = False
    continuity_state: str = "normal"  # normal|recovery|handoff_pending|unknown
    execution_attempt_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    last_operation_uncertain: bool = False
    action_history: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        # Normalize/coerce runtime inputs defensively; callers must not rely on mutation.
        object.__setattr__(self, "mission_id", str(self.mission_id or ""))
        object.__setattr__(self, "workspace_root", str(self.workspace_root or ""))
        object.__setattr__(self, "continuity_state", str(self.continuity_state or "normal"))
        object.__setattr__(self, "workspace_verification_required", bool(self.workspace_verification_required))
        object.__setattr__(self, "last_operation_uncertain", bool(self.last_operation_uncertain))
        ah = self.action_history or ()
        if isinstance(ah, list):
            ah = tuple(dict(x) if isinstance(x, dict) else {"value": x} for x in ah[-50:])
        elif isinstance(ah, tuple):
            ah = tuple(dict(x) if isinstance(x, dict) else {"value": x} for x in ah[-50:])
        else:
            ah = ()
        object.__setattr__(self, "action_history", ah)

    @property
    def requires_verification(self) -> bool:
        return bool(self.workspace_verification_required)


def _normalize_checkpoint(checkpoint: Any) -> tuple[HandoffContext | None, bool]:
    """Return (normalized_handoff_or_None, invalid_or_untrusted_shape).

    For protected missions, malformed/unparseable/missing-identity checkpoints must be treated
    as unsafe by callers (fail-closed). This function never infers safety.
    """
    if checkpoint is None:
        return None, False
    if isinstance(checkpoint, HandoffContext):
        return checkpoint, False
    if isinstance(checkpoint, Mapping):
        # Reject clearly malformed shapes early.
        try:
            actions = checkpoint.get("actions_completed") or checkpoint.get("action_history") or []
            if actions is not None and not isinstance(actions, list):
                return None, True
            approvals = checkpoint.get("approvals_state")
            if approvals is not None and not isinstance(approvals, dict):
                approvals = {}
            from .continuity import build_handoff_context, build_resume_checkpoints
            cps = build_resume_checkpoints(actions if isinstance(actions, list) else [])
            mission_id = str(checkpoint.get("mission_id") or "")
            objective = str(checkpoint.get("objective") or checkpoint.get("goal") or "resume")
            if not mission_id or not objective:
                # Missing identity/objective => unsafe for protected continuity decisions.
                return None, True
            normalized = build_handoff_context(
                mission_id=mission_id,
                objective=objective,
                approvals_state=approvals if isinstance(approvals, dict) else {},
                checkpoints=cps,
                next_step=str(checkpoint.get("next_step") or "verify_workspace_state_before_any_write"),
            )
            return normalized, False
        except Exception:
            return None, True
    return None, True


def classify_operation(tool: str, parameters: dict[str, Any] | None = None) -> str:
    """Return 'read', 'workspace_mutation', 'side_effect', or 'unknown'."""
    params = parameters or {}
    if tool in WORKSPACE_MUTATING_TOOLS:
        return "workspace_mutation"
    if tool in {"workspace_list_files", "workspace_read_file", "workspace_search", "recall_memory"}:
        return "read"
    if tool in WORKSPACE_SIDE_EFFECT_TOOLS:
        return "side_effect"
    if tool == "file_controller":
        action = str(params.get("action", "")).strip().lower()
        if action in FILE_CONTROLLER_MUTATING_ACTIONS:
            return "side_effect"
        if action in {"read", "list", "find", "search", "info", "stat", "exists"}:
            return "read"
        # Unknown file_controller action -> treat as side effect when guarded.
        return "side_effect"
    if tool in GENERIC_SIDE_EFFECT_TOOLS:
        return "side_effect"
    # Unknown tools: conservative for guarded missions.
    return "unknown"


def _history_has_uncertain_or_inflight(action_history: list[dict[str, Any]] | None) -> bool:
    for item in (action_history or [])[-50:]:
        status = str((item or {}).get("status", "unknown")).lower()
        if status in {"unknown", "in_progress", "running"}:
            return True
    return False


def evaluate_continuity_guard(
    context: ContinuityExecutionContext | None,
    *,
    tool: str,
    parameters: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """Central pre-dispatch guard for continuity-marked missions.

    Returns (allowed, issues). Fail-closed when verification is required.
    """
    if context is None or not context.requires_verification:
        return True, []

    op = classify_operation(tool, parameters)
    # For marked missions, be conservative: any non-read/unknown or mutating/side-effect op requires valid continuity state.
    if op == "read":
        # Reads are allowed only if we can at least validate mission identity context; proof still recommended.
        # To avoid blocking legitimate diagnostics during recovery, require proof when state uncertain.
        pass
    # Sensitive/side-effecting operations (and unknown) must pass full checks.
    sensitive = op in {"workspace_mutation", "side_effect", "unknown"}
    if not sensitive and not context.last_operation_uncertain and not _history_has_uncertain_or_inflight(context.action_history):
        # read in stable state: allow but still prefer proof if provided? historical non-breaking.
        return True, []

    issues: list[str] = []
    if not context.mission_id:
        issues.append("continuity_mission_id_missing")

    checkpoint_obj, checkpoint_invalid = _normalize_checkpoint(context.checkpoint)
    if checkpoint_invalid:
        issues.append("checkpoint_invalid_or_untrusted")
    # Refuse if checkpoint contains uncertain/in-progress actions that must not be replayed.
    if checkpoint_obj is not None:
        # Bind checkpoint identity to continuity mission when present.
        cp_mission = str(getattr(checkpoint_obj, "mission_id", "") or "")
        if cp_mission and context.mission_id and cp_mission != context.mission_id:
            issues.append("checkpoint_mission_mismatch")
        for cp in getattr(checkpoint_obj, "checkpoints", []) or []:
            if getattr(cp, "status", "unknown") in {"unknown", "in_progress"}:
                issues.append("checkpoint_uncertain_or_unverified")
                break
    if _history_has_uncertain_or_inflight(context.action_history):
        issues.append("prior_action_outcome_uncertain")
    if context.last_operation_uncertain:
        issues.append("last_operation_uncertain")
    if context.continuity_state in {"unknown", "handoff_pending", "recovery_pending"}:
        issues.append("continuity_state_not_verified")

    # Workspace proof validation (signature, mission, workspace, expiry, reinspection) is mandatory for sensitive ops.
    ws = context.workspace_root or None
    if sensitive:
        has_uncertainty = any(i in {
            "checkpoint_invalid_or_untrusted",
            "checkpoint_mission_mismatch",
            "checkpoint_uncertain_or_unverified",
            "prior_action_outcome_uncertain",
            "last_operation_uncertain",
            "continuity_state_not_verified",
            "continuity_mission_id_missing",
        } for i in issues)
        step_state = "unknown_unverified" if has_uncertainty else "verified_safe_for_new_action"
        # For a new operation after verified stable state, do not let generic completed side-effect
        # checkpoint markers block; uncertainty/in-progress/history risks are enforced above.
        handoff_for_auth = checkpoint_obj if has_uncertainty else None
        ok, proof_issues = authorize_risky_resume_or_write(
            mission_id=context.mission_id,
            workspace_root=ws,
            proof=context.workspace_proof,
            handoff=handoff_for_auth,
            current_step_state=step_state,
            allow_without_proof=False,
        )
        issues.extend(proof_issues)
        if has_uncertainty:
            return False, _dedupe(issues)
        if not ok:
            return False, _dedupe(issues)
        return True, []

    # Non-sensitive read but state/history indicates uncertainty: require proof before proceeding in guarded recovery.
    if issues:
        ok, proof_issues = validate_proof(
            context.workspace_proof,
            mission_id=context.mission_id,
            workspace_root=ws,
        )
        issues.extend(proof_issues)
        return (ok and not any(i.startswith("prior_action") or "uncertain" in i or "not_verified" in i or "invalid" in i or "mismatch" in i for i in issues), _dedupe(issues))

    return True, []


def _dedupe(items: list[str]) -> list[str]:
    out = []
    seen = set()
    for i in items:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out

from __future__ import annotations

from dataclasses import dataclass

from .models import MissionProfile, ModelCapabilities, ModelRecord


@dataclass(frozen=True)
class ClineEligibility:
    eligible: bool
    reason: str


def evaluate_cline_model(model: ModelCapabilities | ModelRecord) -> ClineEligibility:
    caps = model.capabilities if isinstance(model, ModelRecord) else model
    if not caps.supports_cline:
        return ClineEligibility(False, "model_not_declared_cline_compatible")
    if not caps.cline_tool_calling_verified:
        return ClineEligibility(False, "cline_tool_calling_not_verified")
    if not caps.capabilities.tool_calling:
        return ClineEligibility(False, "tool_calling_capability_missing")
    return ClineEligibility(True, "cline_compatible_verified")


def filter_cline_candidates(records: list[ModelRecord], profile: MissionProfile) -> list[ModelRecord]:
    if profile.engine != "cline":
        return records
    eligible: list[ModelRecord] = []
    for record in records:
        status = evaluate_cline_model(record)
        if status.eligible:
            eligible.append(record)
    return eligible

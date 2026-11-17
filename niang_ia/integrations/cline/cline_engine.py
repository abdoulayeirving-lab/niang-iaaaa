from __future__ import annotations

import logging
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

from agent import workspace_tools
from agent.secrets import detect_sensitive_data
from niang_ia.integrations.cline.cline_config import (
    CLINE_FREE_MODELS,
    ClineConfig,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    MAX_ACTIONS,
)
from niang_ia.integrations.cline.cline_events import redact_text
from niang_ia.integrations.cline.cline_health import check_cline_health
from niang_ia.integrations.cline.cline_models import ClineEvent, ClineMode, ClineResult
from niang_ia.integrations.cline.cline_policy import (
    ALLOWED_TOOLS,
    READ_TOOLS,
    approval_description,
    approval_required,
    validate_tool_input,
)
from niang_ia.integrations.cline.cline_process import (
    ClineCancelled,
    ClineFreeModelLimitError,
    ClineProcess,
    ClineProcessError,
)
from niang_ia.skills.catalog import SkillError, load_skill
from niang_ia.skills.quality_gate import evaluate_quality_gate
from niang_ia.skills.selector import select_skills


_LOGGER = logging.getLogger(__name__)
_SAFE_AUTONOMOUS_CHECKS = {
    "git-status", "git-diff-check", "python-compile", "php-lint",
}


class ClineEngineError(RuntimeError):
    pass


class ClineEngine:
    def __init__(
        self,
        process: ClineProcess | None = None,
        health_check: Callable[..., dict] = check_cline_health,
    ):
        self.process = process or ClineProcess()
        self.health_check = health_check

    def execute(
        self,
        goal: str,
        workspace_root: str | Path,
        mode: ClineMode | str,
        *,
        approval_callback: Callable[[str, dict, str, threading.Event], bool] | None = None,
        cancel_flag: threading.Event | None = None,
        on_progress: Callable[[dict], None] | None = None,
        on_action: Callable[[dict], None] | None = None,
        on_event: Callable[[ClineEvent], None] | None = None,
        provider_id: str = DEFAULT_PROVIDER,
        model_id: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
    ) -> ClineResult:
        if not isinstance(goal, str) or not goal.strip():
            raise ClineEngineError("A non-empty software-development task is required.")
        if len(goal) > 8000:
            raise ClineEngineError("The task description exceeds the 8,000-character limit.")
        try:
            selected_mode = ClineMode(mode)
            config = ClineConfig(
                workspace_root=Path(workspace_root),
                provider_id=provider_id,
                model_id=model_id,
                base_url=base_url,
            )
        except (TypeError, ValueError, OSError) as exc:
            raise ClineEngineError(str(exc)) from exc

        if detect_sensitive_data(goal):
            raise ClineEngineError(
                "The task description appears to contain a credential or token. "
                "Remove it before sending the task to the local model."
            )
        try:
            skill_selection = select_skills(goal, workspace_root=config.workspace_root)
        except SkillError as exc:
            raise ClineEngineError(f"NIANG IA could not prepare development skills: {exc}") from exc
        try:
            try:
                health = self.health_check(
                    base_url=config.base_url,
                    provider_id=config.provider_id,
                )
            except TypeError:
                health = self.health_check()
        except Exception as exc:
            raise ClineEngineError("The Cline provider health check failed.") from exc
        if not health.get("ready"):
            service = health.get("model_service", {})
            message = (
                service.get("error")
                if config.provider_id == "ollama"
                and isinstance(service, dict)
                and not service.get("available")
                else "Cline CLI or its Agent SDK is unavailable."
            )
            raise ClineEngineError(str(message))
        available_models = health.get("model_service", {}).get("models", [])
        if (
            config.provider_id == "ollama"
            and model_id not in available_models
            and f"{model_id}:latest" not in available_models
        ):
            raise ClineEngineError(f"The selected local Ollama model is not installed: {model_id}.")

        cancel_flag = cancel_flag or threading.Event()
        completed_actions = 0
        approval_lock = threading.Lock()
        approved_actions: list[tuple[str, dict]] = []
        selected_skill_ids = set(skill_selection.ids)
        loaded_skill_ids: set[str] = set()
        quality_checks: list[dict] = []

        def progress(event: ClineEvent) -> None:
            if on_progress:
                on_progress({
                    "phase": "cline",
                    "current_step": event.tool or event.event_type,
                    "completed_steps": completed_actions,
                    "total_steps": MAX_ACTIONS,
                })
            if on_event:
                on_event(event)

        def approve(tool: str, raw_args: dict) -> bool:
            if tool not in ALLOWED_TOOLS or not isinstance(raw_args, dict):
                return False
            try:
                args = validate_tool_input(tool, raw_args, config.workspace_root)
                required = requires_approval(tool, args)
            except (TypeError, ValueError, OSError):
                return False
            if not required:
                return not cancel_flag.is_set()
            if not approval_callback or cancel_flag.is_set():
                return False
            description = approval_description(tool, args)
            safe_parameters = {"action": tool, "description": description}
            approved = bool(
                approval_callback(tool, safe_parameters, description, cancel_flag)
            ) and not cancel_flag.is_set()
            if approved:
                with approval_lock:
                    approved_actions.append((tool, args))
            return approved

        def requires_approval(tool: str, args: dict) -> bool:
            required = approval_required(
                selected_mode, tool, args, config.workspace_root
            )
            if tool == "workspace_run_check" and args.get("check") not in _SAFE_AUTONOMOUS_CHECKS:
                return True
            return required

        def run_tool(tool: str, raw_args: dict) -> str:
            nonlocal completed_actions
            if cancel_flag.is_set():
                raise ClineCancelled("Mission cancelled by the user.")
            if tool == "workspace_load_skill":
                if not isinstance(raw_args, dict):
                    raise ClineEngineError("Cline sent invalid skill-loader arguments.")
                skill_id = raw_args.get("skill_id")
                if not isinstance(skill_id, str) or skill_id not in selected_skill_ids:
                    raise ClineEngineError("Cline requested a skill that was not selected for this mission.")
                try:
                    skill = load_skill(skill_id)
                except SkillError as exc:
                    raise ClineEngineError(f"Selected skill could not be loaded: {exc}") from exc
                loaded_skill_ids.add(skill_id)
                return f"# {skill.name}\n\n{skill.description}\n\n{skill.instructions}"
            if tool not in ALLOWED_TOOLS:
                raise ClineEngineError("Cline requested a tool that NIANG IA does not provide.")
            args = validate_tool_input(tool, raw_args, config.workspace_root)
            if selected_mode == ClineMode.PLAN and tool not in READ_TOOLS:
                raise ClineEngineError("Plan mode is read-only.")
            if requires_approval(tool, args):
                with approval_lock:
                    approval_index = next(
                        (
                            index
                            for index, approved in enumerate(approved_actions)
                            if approved == (tool, args)
                        ),
                        None,
                    )
                    if approval_index is not None:
                        approved_actions.pop(approval_index)
                if approval_index is None:
                    raise ClineEngineError(
                        "This action requires explicit human approval before execution."
                    )
            completed_actions += 1
            if completed_actions > config.max_actions:
                raise ClineEngineError(f"The mission action limit ({config.max_actions}) was reached.")
            description = approval_description(tool, args)
            if on_progress:
                on_progress({
                    "phase": "cline",
                    "current_step": description,
                    "completed_steps": completed_actions - 1,
                    "total_steps": config.max_actions,
                })
            try:
                output = _dispatch_tool(tool, args, config, cancel_flag)
                if tool == "workspace_run_check":
                    quality_checks.append({
                        "name": args["check"],
                        "status": "PASS",
                        "evidence": f"workspace_run_check: {args['check']}",
                    })
                safe_output = redact_text(output)
                if on_action:
                    on_action({
                        "number": completed_actions,
                        "tool": tool,
                        "description": description,
                        "status": "completed",
                        "result": safe_output[:4000],
                    })
                if on_progress:
                    on_progress({
                        "phase": "cline",
                        "current_step": description,
                        "completed_steps": completed_actions,
                        "total_steps": config.max_actions,
                    })
                return safe_output
            except Exception as exc:
                if tool == "workspace_run_check":
                    quality_checks.append({
                        "name": args["check"],
                        "status": "FAIL",
                        "evidence": f"workspace_run_check: {args['check']}",
                    })
                safe_error = redact_text(exc)
                if on_action:
                    on_action({
                        "number": completed_actions,
                        "tool": tool,
                        "description": description,
                        "status": "failed",
                        "result": safe_error[:1000],
                    })
                raise

        try:
            if config.provider_id == "cline":
                model_candidates = CLINE_FREE_MODELS[CLINE_FREE_MODELS.index(model_id):]
            else:
                model_candidates = (model_id,)
            deadline = time.monotonic() + config.mission_timeout_seconds
            selected_skills = [
                {"id": skill.id, "description": skill.description}
                for skill in skill_selection.skills
            ]
            result = None
            for attempt, candidate in enumerate(model_candidates):
                remaining = int(deadline - time.monotonic())
                if remaining <= 0:
                    raise ClineEngineError(
                        f"Cline mission exceeded its {config.mission_timeout_seconds}-second limit."
                    )
                attempt_config = replace(
                    config,
                    model_id=candidate,
                    mission_timeout_seconds=min(config.mission_timeout_seconds, remaining),
                )
                attempt_goal = goal
                if attempt:
                    attempt_goal += (
                        "\n\nA previous Cline free model exhausted its quota. "
                        "Continue from the current workspace state: inspect existing work, "
                        "avoid duplicating completed changes, and request approval before "
                        "overwriting existing files."
                    )
                try:
                    result = self.process.run(
                        attempt_goal,
                        attempt_config,
                        selected_mode,
                        on_tool_request=run_tool,
                        on_approval_request=approve,
                        selected_skills=selected_skills,
                        on_event=progress,
                        cancel_flag=cancel_flag,
                    )
                    break
                except ClineFreeModelLimitError as exc:
                    if cancel_flag.is_set():
                        raise ClineCancelled("Mission cancelled by the user.") from exc
                    if attempt + 1 == len(model_candidates):
                        raise ClineEngineError(
                            "All configured free Cline models have exhausted their quotas. "
                            "No paid model was used."
                        ) from exc
                    next_model = model_candidates[attempt + 1]
                    _LOGGER.info("Cline free quota exhausted; switching to the next free model.")
                    if on_progress:
                        on_progress({
                            "phase": "cline",
                            "current_step": f"Quota gratuite épuisée; passage à {next_model}",
                            "completed_steps": completed_actions,
                            "total_steps": config.max_actions,
                        })
            if result is None:
                raise ClineEngineError("Cline did not return a mission result.")
            if completed_actions == 0:
                raise ClineEngineError(
                    "Cline completed without using a workspace tool; no project work was performed. "
                    "Verify model tool-calling support or resolve any denied action."
                )
            result.actions = completed_actions
            result.quality_gate = evaluate_quality_gate(
                goal,
                quality_checks,
                selected_skill_ids=skill_selection.ids,
            )
            result.selected_skills = list(skill_selection.ids)
            result.loaded_skills = [
                skill_id for skill_id in skill_selection.ids
                if skill_id in loaded_skill_ids
            ]
            _LOGGER.info("Cline mission completed with %s workspace actions.", completed_actions)
            return result
        except (ClineCancelled, ClineProcessError) as exc:
            _LOGGER.warning("Cline mission stopped: %s", type(exc).__name__)
            raise ClineEngineError(redact_text(exc)) from exc
        except Exception as exc:
            _LOGGER.error("Cline mission failed: %s", redact_text(exc))
            raise ClineEngineError(redact_text(exc)) from exc


def _dispatch_tool(
    tool: str,
    args: dict,
    config: ClineConfig,
    cancel_flag: threading.Event,
) -> str:
    root = config.workspace_root
    if tool == "workspace_list_files":
        return workspace_tools.list_files(
            args.get("path", "."), workspace_root=root
        )
    if tool == "workspace_read_file":
        return workspace_tools.read_file(args["path"], workspace_root=root)
    if tool == "workspace_search":
        return workspace_tools.search_text(
            args["query"], args.get("path", "."), workspace_root=root
        )
    if tool == "workspace_write_file":
        return workspace_tools.write_file(
            args["path"], args["content"], workspace_root=root
        )
    if tool == "workspace_edit_file":
        return workspace_tools.edit_file(
            args["path"],
            args["find"],
            args["replace"],
            args.get("expected_occurrences", 1),
            workspace_root=root,
        )
    if tool == "workspace_apply_patch":
        return workspace_tools.apply_patch(args["patch"], workspace_root=root)
    if tool == "workspace_run_check":
        return workspace_tools.run_check(
            args["check"],
            args.get("timeout_seconds", config.action_timeout_seconds),
            workspace_root=root,
            cancel_flag=cancel_flag,
        )
    if tool == "workspace_install_dependency":
        return workspace_tools.install_dependency(
            args["ecosystem"],
            args["package"],
            workspace_root=root,
            timeout_seconds=config.action_timeout_seconds,
            cancel_flag=cancel_flag,
        )
    raise ClineEngineError(f"Unknown Cline action: {tool}.")

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from agent import workspace_tools
from agent.secrets import detect_sensitive_data
from niang_ia.integrations.cline.cline_config import ClineConfig, DEFAULT_BASE_URL, DEFAULT_MODEL, MAX_ACTIONS
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
from niang_ia.integrations.cline.cline_process import ClineCancelled, ClineProcess, ClineProcessError


_LOGGER = logging.getLogger(__name__)
_SAFE_AUTONOMOUS_CHECKS = {"git-status", "git-diff-check", "python-compile"}


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
        model_id: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
    ) -> ClineResult:
        if not isinstance(goal, str) or not goal.strip():
            raise ClineEngineError("A non-empty software-development task is required.")
        if len(goal) > 8000:
            raise ClineEngineError("The task description exceeds the 8,000-character limit.")
        try:
            selected_mode = ClineMode(mode)
            config = ClineConfig(workspace_root=Path(workspace_root), model_id=model_id, base_url=base_url)
        except (TypeError, ValueError, OSError) as exc:
            raise ClineEngineError(str(exc)) from exc

        if detect_sensitive_data(goal):
            raise ClineEngineError(
                "The task description appears to contain a credential or token. "
                "Remove it before sending the task to the local model."
            )
        try:
            try:
                health = self.health_check(base_url=config.base_url)
            except TypeError:
                health = self.health_check()
        except Exception as exc:
            raise ClineEngineError("The Cline and local-model health check failed.") from exc
        if not health.get("ready"):
            service = health.get("model_service", {})
            message = (
                service.get("error")
                if isinstance(service, dict) and not service.get("available")
                else "Cline CLI, its Agent SDK, or the local Ollama service is unavailable."
            )
            raise ClineEngineError(str(message))
        available_models = health.get("model_service", {}).get("models", [])
        if model_id not in available_models and f"{model_id}:latest" not in available_models:
            raise ClineEngineError(f"The selected local Ollama model is not installed: {model_id}.")

        cancel_flag = cancel_flag or threading.Event()
        completed_actions = 0
        approval_lock = threading.Lock()
        approved_actions: list[tuple[str, dict]] = []

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
            result = self.process.run(
                goal,
                config,
                selected_mode,
                on_tool_request=run_tool,
                on_approval_request=approve,
                on_event=progress,
                cancel_flag=cancel_flag,
            )
            if completed_actions == 0:
                raise ClineEngineError(
                    "Cline completed without using a workspace tool; no project work was performed. "
                    "Verify model tool-calling support or resolve any denied action."
                )
            result.actions = completed_actions
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

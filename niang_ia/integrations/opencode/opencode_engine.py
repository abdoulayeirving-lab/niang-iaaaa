from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Callable

from agent import workspace_tools
from niang_ia.integrations.cline.cline_events import redact_text
from niang_ia.integrations.opencode.opencode_health import workspace_mcp_status
from niang_ia.integrations.opencode.opencode_process import (
    OpenCodeCancelled,
    OpenCodeProcess,
    OpenCodeProcessError,
)
from niang_ia.skills.catalog import SkillError
from niang_ia.skills.quality_gate import evaluate_quality_gate
from niang_ia.skills.selector import select_skills


MAX_ACTIONS = 80
VALID_MODES = {"plan", "assisted", "autonomous_controlled"}
EDIT_KINDS = {"edit"}
WORKSPACE_TOOLS = {
    "niang_workspace_run_check": "run_check",
    "niang_workspace_install_dependency": "install_dependency",
    "niang_workspace_start_preview": "start_preview",
    "niang_workspace_stop_preview": "stop_preview",
    "niang_workspace_visual_asset_inspect": "visual_asset_inspect",
    "niang_workspace_visual_asset_search": "visual_asset_search",
    "niang_workspace_visual_asset_use": "visual_asset_use",
    "niang_workspace_visual_asset_verify": "visual_asset_verify",
}


class OpenCodeEngineError(RuntimeError):
    pass


class OpenCodeEngine:
    def __init__(self, process: OpenCodeProcess | None = None):
        self.process = process or OpenCodeProcess()

    def execute(
        self,
        goal: str,
        workspace_root: str | Path,
        mode: str,
        *,
        approval_callback: Callable[[str, dict, str, threading.Event], bool] | None = None,
        cancel_flag: threading.Event | None = None,
        on_progress: Callable[[dict], None] | None = None,
        on_action: Callable[[dict], None] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(goal, str) or not goal.strip():
            raise OpenCodeEngineError("A non-empty software-development task is required.")
        if len(goal) > 8000:
            raise OpenCodeEngineError("The task description exceeds the 8,000-character limit.")
        if mode not in VALID_MODES:
            raise OpenCodeEngineError("Unsupported OpenCode operating mode.")
        try:
            root = workspace_tools._workspace_root(workspace_root)
        except (TypeError, ValueError, OSError) as exc:
            raise OpenCodeEngineError(str(exc)) from exc
        mcp_available, mcp_error = workspace_mcp_status()
        if not mcp_available:
            raise OpenCodeEngineError(mcp_error or "The NIANG IA workspace tools are unavailable.")
        _validate_workspace_integrations(root)
        try:
            skill_selection = select_skills(goal, workspace_root=root)
        except SkillError as exc:
            raise OpenCodeEngineError(f"NIANG IA could not prepare development skills: {exc}") from exc

        cancel_flag = cancel_flag or threading.Event()
        action_count = 0
        completed_actions = 0
        text_chunks: list[str] = []
        tool_calls: dict[str, dict[str, Any]] = {}
        quality_checks: list[dict[str, Any]] = []
        loaded_skill_ids: set[str] = set()
        lock = threading.Lock()

        def emit_progress(step: str) -> None:
            if on_progress:
                on_progress({
                    "phase": "opencode",
                    "current_step": step[:300],
                    "completed_steps": completed_actions,
                    "total_steps": MAX_ACTIONS,
                })

        def handle_event(params: dict[str, Any]) -> None:
            nonlocal action_count, completed_actions
            routing = params.get("model_routing")
            if isinstance(routing, dict):
                model_id = routing.get("model_id")
                attempt = routing.get("attempt")
                total = routing.get("total")
                if isinstance(model_id, str):
                    suffix = (
                        f" ({attempt}/{total})"
                        if isinstance(attempt, int) and isinstance(total, int)
                        else ""
                    )
                    emit_progress(f"Modèle gratuit OpenCode : {model_id}{suffix}")
                return
            update = params.get("update")
            if not isinstance(update, dict):
                return
            update_type = update.get("sessionUpdate")
            if update_type == "agent_message_chunk":
                content = update.get("content")
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    with lock:
                        text_chunks.append(content["text"])
                return
            if update_type == "tool_call":
                call_id = str(update.get("toolCallId", ""))
                if call_id:
                    action_count += 1
                    if action_count > MAX_ACTIONS:
                        cancel_flag.set()
                        raise OpenCodeEngineError(
                            f"The mission action limit ({MAX_ACTIONS}) was reached."
                        )
                    tool_calls[call_id] = {
                        "name": update.get("name", "tool"),
                        "title": update.get("title", "OpenCode action"),
                        "kind": update.get("kind", "other"),
                        "locations": update.get("locations", []),
                        "raw_input": update.get("rawInput", {}),
                    }
                    emit_progress(str(update.get("title", "OpenCode action")))
                return
            if update_type == "tool_call_update":
                call_id = str(update.get("toolCallId", ""))
                status = str(update.get("status", ""))
                call = tool_calls.get(call_id)
                if call and status in {"completed", "failed"}:
                    call["status"] = status
                    if call["name"] == "skill" and status == "completed":
                        raw_input = call.get("raw_input")
                        skill_id = None
                        if isinstance(raw_input, dict):
                            for key in ("id", "skill_id"):
                                candidate = raw_input.get(key)
                                if isinstance(candidate, str) and candidate in skill_selection.ids:
                                    skill_id = candidate
                                    break
                        content_blocks = update.get("content")
                        if skill_id is None and isinstance(content_blocks, list):
                            for block in content_blocks:
                                if not isinstance(block, dict):
                                    continue
                                body = block.get("content")
                                text = (
                                    body.get("text")
                                    if isinstance(body, dict)
                                    else block.get("text")
                                )
                                if not isinstance(text, str):
                                    continue
                                skill_id = next(
                                    (
                                        candidate
                                        for candidate in skill_selection.ids
                                        if f'<skill_content name="{candidate}">' in text
                                    ),
                                    None,
                                )
                                if skill_id is not None:
                                    break
                        if isinstance(skill_id, str) and skill_id in skill_selection.ids:
                            loaded_skill_ids.add(skill_id)
                    if call["name"] == "niang_workspace_run_check":
                        raw_input = call.get("raw_input")
                        check = raw_input.get("check") if isinstance(raw_input, dict) else None
                        if isinstance(check, str):
                            quality_checks.append({
                                "name": check,
                                "status": "PASS" if status == "completed" else "FAIL",
                                "evidence": f"niang_workspace_run_check: {check}",
                            })
                    if (
                        call["name"] == "niang_workspace_visual_asset_verify"
                        and status == "completed"
                    ):
                        report = _parse_visual_asset_report(update.get("content"))
                        if report is not None and report.get("status") in {"PASS", "FAIL"}:
                            quality_checks.append({
                                "name": "visual-assets-integrity",
                                "status": report["status"],
                                "evidence": (
                                    "visual_asset_verify: "
                                    f"{len(report.get('issues', []))} issue(s)"
                                ),
                            })
                        quality_checks.append({
                            "name": "visual_asset_review",
                            "status": "NOT_TESTED",
                            "evidence": report.get(
                                "visual_review",
                                "Image composition and semantic fit were not visually reviewed.",
                            ) if report else "The visual verification report could not be parsed.",
                        })
                    if status == "completed":
                        completed_actions += 1
                    if on_action:
                        on_action({
                            "number": completed_actions if status == "completed" else action_count,
                            "tool": call["name"],
                            "description": str(call["title"])[:300],
                            "status": status,
                            "result": "",
                        })
                    emit_progress(str(call["title"]))
                return
            if update_type == "current_mode_update" and mode == "plan":
                if update.get("currentModeId") != "plan":
                    cancel_flag.set()
                    raise OpenCodeEngineError("OpenCode tried to leave read-only plan mode.")

        def permission_request(params: dict[str, Any]) -> bool:
            if cancel_flag.is_set():
                return False
            tool_call = params.get("toolCall")
            if not isinstance(tool_call, dict):
                return False
            kind = str(tool_call.get("kind", "other")).lower()
            name = str(tool_call.get("name", ""))
            call_id = str(tool_call.get("toolCallId", ""))
            if call_id in tool_calls:
                tool_calls[call_id]["raw_input"] = tool_call.get(
                    "rawInput",
                    tool_calls[call_id].get("raw_input", {}),
                )
            if name in WORKSPACE_TOOLS:
                if (
                    WORKSPACE_TOOLS[name].startswith("visual_asset_")
                    and "visual-asset-intelligence" not in loaded_skill_ids
                ):
                    return False
                return _approve_workspace_tool(
                    tool_call,
                    WORKSPACE_TOOLS[name],
                    root,
                    mode,
                    approval_callback,
                    cancel_flag,
                )
            if kind not in EDIT_KINDS or name.lower() in {"shell", "bash", "terminal"}:
                return False
            if mode == "plan":
                return False
            paths = _permission_paths(tool_call, root)
            if not paths or len(paths) > 20:
                return False
            if mode == "autonomous_controlled" and all(not (root / path).exists() for path in paths):
                return True
            if not approval_callback:
                return False
            public_tool = name or kind
            safe_parameters = {"paths": paths, "kind": kind}
            description = (
                "OpenCode demande l’autorisation de modifier : "
                + ", ".join(paths)
                + ". Refusez si cette modification n’est pas attendue."
            )
            return bool(
                approval_callback(public_tool, safe_parameters, description, cancel_flag)
            ) and not cancel_flag.is_set()

        try:
            result = self.process.run(
                goal,
                root,
                mode,
                selected_skill_ids=skill_selection.ids,
                on_permission=permission_request,
                on_event=handle_event,
                cancel_flag=cancel_flag,
            )
        except (OpenCodeCancelled, OpenCodeProcessError) as exc:
            raise OpenCodeEngineError(redact_text(exc)) from exc
        except Exception as exc:
            raise OpenCodeEngineError(redact_text(exc)) from exc

        if cancel_flag.is_set():
            raise OpenCodeEngineError("OpenCode mission was cancelled.")
        if result.get("stop_reason") not in {"end_turn", "completed"}:
            raise OpenCodeEngineError(
                f"OpenCode did not complete the task (stop reason: {result.get('stop_reason') or 'unknown'})."
            )
        if completed_actions == 0:
            raise OpenCodeEngineError(
                "OpenCode completed without reporting a workspace action; no project work was verified."
            )
        quality_gate = evaluate_quality_gate(
            goal,
            quality_checks,
            selected_skill_ids=skill_selection.ids,
        )
        return {
            "status": "completed",
            "text": redact_text("".join(text_chunks)),
            "actions": completed_actions,
            "session_id": result.get("session_id", ""),
            "quality_gate": quality_gate,
            "skills": {
                "selected": list(skill_selection.ids),
                "loaded": [
                    skill_id for skill_id in skill_selection.ids
                    if skill_id in loaded_skill_ids
                ],
            },
        }


def _approve_workspace_tool(
    tool_call: dict[str, Any],
    tool_name: str,
    workspace_root: Path,
    mode: str,
    approval_callback: Callable[[str, dict, str, threading.Event], bool] | None,
    cancel_flag: threading.Event,
) -> bool:
    if mode == "plan" or cancel_flag.is_set() or not approval_callback:
        return False
    raw_input = tool_call.get("rawInput")
    try:
        from niang_ia.integrations.opencode.opencode_tools_server import (
            _resolve_preview_directory,
            _validate_arguments as _validate_workspace_tool_arguments,
        )

        arguments = _validate_workspace_tool_arguments(tool_name, raw_input)
        if tool_name == "start_preview":
            target = _resolve_preview_directory(workspace_root, arguments["path"])
            arguments["path"] = target.relative_to(workspace_root).as_posix()
    except (TypeError, ValueError, OSError, workspace_tools.WorkspaceError):
        return False

    if tool_name == "run_check":
        detail = (
            f"Vérification « {arguments['check']} » "
            f"(limite : {arguments['timeout_seconds']} secondes)"
        )
    elif tool_name == "install_dependency":
        detail = (
            f"Installer « {arguments['package']} » pour "
            f"{arguments['ecosystem']} dans le projet"
        )
    elif tool_name == "start_preview":
        detail = f"Démarrer un aperçu statique local du dossier « {arguments['path']} »"
    elif tool_name == "visual_asset_inspect":
        detail = "Inspecter les images locales déjà présentes dans le projet"
    elif tool_name == "visual_asset_search":
        detail = (
            f"Envoyer la recherche « {arguments['query']} » à Pixabay/Unsplash"
            + (
                " et à Pexels (clé configurée)"
                if arguments.get("allow_pexels") is True
                else ""
            )
        )
    elif tool_name == "visual_asset_use":
        detail = (
            f"Enregistrer l’image {arguments['candidate_id']} dans "
            f"« {arguments['relative_path'] or arguments['placement']} » "
            "avec sa provenance"
        )
        if arguments["candidate_id"].startswith("local:"):
            detail += (
                "; confirmer que l’image a été fournie par l’utilisateur "
                "ou que ses droits d’utilisation ont été vérifiés"
            )
    elif tool_name == "visual_asset_verify":
        detail = "Vérifier les images, fichiers, crédits et métadonnées du projet"
        if arguments["check_external_urls"]:
            detail += " et contrôler les URL externes autorisées"
    else:
        detail = "Arrêter l’aperçu statique local du projet"
    description = (
        f"OpenCode demande l’autorisation pour : {detail}.\n"
        "Cette action reste limitée au projet sélectionné; aucun terminal arbitraire ne sera exécuté."
    )
    return bool(
        approval_callback(
            f"opencode_{tool_name}",
            arguments,
            description,
            cancel_flag,
        )
    ) and not cancel_flag.is_set()


def _parse_visual_asset_report(content: Any) -> dict[str, Any] | None:
    if not isinstance(content, list):
        return None
    for block in content:
        if not isinstance(block, dict):
            continue
        body = block.get("content")
        text = body.get("text") if isinstance(body, dict) else block.get("text")
        if not isinstance(text, str):
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _permission_paths(tool_call: dict[str, Any], workspace_root: Path) -> list[str]:
    values: list[str] = []
    locations = tool_call.get("locations", [])
    if isinstance(locations, list):
        for location in locations:
            if isinstance(location, dict) and isinstance(location.get("path"), str):
                values.append(location["path"])

    raw_input = tool_call.get("rawInput")
    if isinstance(raw_input, dict):
        for key in ("path", "filePath", "file_path", "target"):
            candidate = raw_input.get(key)
            if isinstance(candidate, str):
                values.append(candidate)

    paths: list[str] = []
    for value in values:
        candidate = Path(value)
        try:
            if candidate.is_absolute():
                resolved = candidate.resolve(strict=False)
                relative = resolved.relative_to(workspace_root)
                relative_path = relative.as_posix()
            else:
                relative_path = candidate.as_posix()
            safe = workspace_tools._resolve_workspace_path(
                relative_path, workspace_root=workspace_root
            )
            normalized = safe.relative_to(workspace_root).as_posix()
        except (OSError, ValueError, workspace_tools.WorkspaceError):
            return []
        if normalized not in paths:
            paths.append(normalized)
    return paths


def _validate_workspace_integrations(workspace_root: Path) -> None:
    config_key = re.compile(r'["\']?(?:plugins|mcp)["\']?\s*:')
    config_names = ("opencode.json", "opencode.jsonc")
    for directory in (workspace_root, *workspace_root.parents):
        plugin_directory = directory / ".opencode" / "plugins"
        try:
            if plugin_directory.is_dir() and any(plugin_directory.iterdir()):
                raise OpenCodeEngineError(
                    "This workspace contains OpenCode plugins. Remove or disable them before starting a NIANG IA mission."
                )
        except OSError as exc:
            raise OpenCodeEngineError(
                "The workspace OpenCode plugin configuration could not be checked."
            ) from exc

        config_paths = [directory / name for name in config_names]
        config_paths.extend(
            directory / ".opencode" / name for name in config_names
        )
        for config_path in config_paths:
            try:
                if not config_path.is_file():
                    continue
                if config_path.stat().st_size > 1_000_000:
                    raise OpenCodeEngineError(
                        "An OpenCode workspace configuration exceeds the 1 MB safety limit."
                    )
                contents = config_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise OpenCodeEngineError(
                    "An OpenCode workspace configuration is not valid UTF-8."
                ) from exc
            except OSError as exc:
                raise OpenCodeEngineError(
                    "An OpenCode workspace configuration could not be checked."
                ) from exc
            if config_key.search(contents):
                raise OpenCodeEngineError(
                    "This workspace configures OpenCode plugins or MCP servers, which NIANG IA does not launch."
                )

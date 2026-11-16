from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent import workspace_tools
from niang_ia.integrations.cline.cline_models import ClineMode


READ_TOOLS = {"workspace_list_files", "workspace_read_file", "workspace_search"}
WRITE_TOOLS = {"workspace_write_file", "workspace_edit_file", "workspace_apply_patch"}
CHECK_TOOLS = {"workspace_run_check"}
INSTALL_TOOLS = {"workspace_install_dependency"}
ALLOWED_TOOLS = READ_TOOLS | WRITE_TOOLS | CHECK_TOOLS | INSTALL_TOOLS

_PACKAGE_NAME = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9._-]*|@[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)(?:@[A-Za-z0-9.*<>=!~^+-]+)?$")


def validate_tool_input(tool: str, values: Any, workspace_root: Path) -> dict:
    if tool not in ALLOWED_TOOLS or not isinstance(values, dict):
        raise workspace_tools.WorkspaceError("This Cline tool is not allowed.")
    args = dict(values)
    if tool in {"workspace_list_files", "workspace_read_file", "workspace_search",
                "workspace_write_file", "workspace_edit_file"}:
        workspace_tools._resolve_workspace_path(
            args.get("path", "."), workspace_root=workspace_root
        )
    if tool == "workspace_run_check" and args.get("check") not in workspace_tools.APPROVED_CHECKS:
        raise workspace_tools.WorkspaceError("Only approved fixed project checks may be run.")
    if tool == "workspace_install_dependency":
        ecosystem = args.get("ecosystem")
        package = args.get("package")
        if ecosystem not in {"python", "node"} or not isinstance(package, str) or not _PACKAGE_NAME.fullmatch(package):
            raise workspace_tools.WorkspaceError("The requested dependency specification is not allowed.")
    return args


def approval_required(mode: ClineMode, tool: str, args: dict, workspace_root: Path) -> bool:
    if tool in READ_TOOLS:
        return False
    if tool in INSTALL_TOOLS:
        return True
    if tool in CHECK_TOOLS:
        return mode != ClineMode.AUTONOMOUS_CONTROLLED
    if tool in WRITE_TOOLS:
        target = args.get("path")
        if tool == "workspace_apply_patch":
            return True
        if tool == "workspace_edit_file":
            return mode != ClineMode.AUTONOMOUS_CONTROLLED
        path = workspace_tools._resolve_workspace_path(
            str(target or ""), workspace_root=workspace_root
        )
        return mode != ClineMode.AUTONOMOUS_CONTROLLED or path.exists()
    return True


def approval_description(tool: str, args: dict) -> str:
    if tool == "workspace_write_file":
        return f"Créer ou remplacer le fichier {Path(str(args.get('path', ''))).name}."
    if tool == "workspace_edit_file":
        return f"Modifier le fichier {Path(str(args.get('path', ''))).name}."
    if tool == "workspace_apply_patch":
        return "Appliquer un correctif aux fichiers du projet sélectionné."
    if tool == "workspace_run_check":
        return f"Exécuter le contrôle de projet « {args.get('check', '')} »."
    if tool == "workspace_install_dependency":
        return f"Installer la dépendance {args.get('package', '')} ({args.get('ecosystem', '')})."
    return "Autoriser cette action Cline."

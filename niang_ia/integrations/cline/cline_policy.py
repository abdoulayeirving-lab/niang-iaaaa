from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent import workspace_tools
from agent.secrets import detect_sensitive_data
from niang_ia.integrations.cline.cline_models import ClineMode


READ_TOOLS = {
    "workspace_list_files", "workspace_read_file", "workspace_search",
    "workspace_visual_asset_inspect",
}
OPEN_FOLDER_TOOLS = {"workspace_open_folder"}
WINDOW_READ_TOOLS = {"workspace_window_observe"}
WINDOW_ACTION_TOOLS = {
    "workspace_window_click",
    "workspace_window_type",
    "workspace_window_scroll",
    "workspace_window_press",
}
WINDOW_TOOLS = WINDOW_READ_TOOLS | WINDOW_ACTION_TOOLS
WRITE_TOOLS = {"workspace_write_file", "workspace_edit_file", "workspace_apply_patch"}
CHECK_TOOLS = {"workspace_run_check"}
INSTALL_TOOLS = {"workspace_install_dependency"}
VISUAL_ASSET_TOOLS = {
    "workspace_visual_asset_search",
    "workspace_visual_asset_use",
    "workspace_visual_asset_verify",
}
ALLOWED_TOOLS = (
    READ_TOOLS
    | OPEN_FOLDER_TOOLS
    | WINDOW_TOOLS
    | WRITE_TOOLS
    | CHECK_TOOLS
    | INSTALL_TOOLS
    | VISUAL_ASSET_TOOLS
)

_PACKAGE_NAME = re.compile(r"^(?:[A-Za-z0-9][A-Za-z0-9._-]*|@[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)(?:@[A-Za-z0-9.*<>=!~^+-]+)?$")


def validate_tool_input(
    tool: str,
    values: Any,
    workspace_root: Path,
    *,
    target_window_hwnd: int | None = None,
    target_window_pid: int | None = None,
) -> dict:
    if tool not in ALLOWED_TOOLS or not isinstance(values, dict):
        raise workspace_tools.WorkspaceError("This Cline tool is not allowed.")
    args = dict(values)
    if tool in WINDOW_TOOLS:
        if (
            type(target_window_hwnd) is not int
            or target_window_hwnd <= 0
            or type(target_window_pid) is not int
            or target_window_pid <= 0
        ):
            raise workspace_tools.WorkspaceError(
                "Choose a desktop window before using Cline window controls."
            )
        expected = {
            "workspace_window_observe": set(),
            "workspace_window_click": {"name", "automation_id", "role"},
            "workspace_window_type": {"name", "automation_id", "text"},
            "workspace_window_scroll": {"amount"},
            "workspace_window_press": {"key"},
        }[tool]
        if set(args) - expected:
            raise workspace_tools.WorkspaceError("Unknown desktop-control arguments.")
        if tool == "workspace_window_click":
            name, automation_id, role = (
                args.get("name", ""),
                args.get("automation_id", ""),
                args.get("role", ""),
            )
            if bool(name) == bool(automation_id) or role not in {
                "Button", "CheckBox", "Hyperlink", "ListItem", "MenuItem",
                "RadioButton", "TabItem", "TreeItem",
            }:
                raise workspace_tools.WorkspaceError("Specify one accessible control and its supported role.")
            if (
                not isinstance(name or automation_id, str)
                or len(name or automation_id) > 160
                or detect_sensitive_data(name or automation_id)
            ):
                raise workspace_tools.WorkspaceError("The desktop control identifier is invalid.")
        elif tool == "workspace_window_type":
            name, automation_id, text = (
                args.get("name", ""),
                args.get("automation_id", ""),
                args.get("text"),
            )
            if bool(name) == bool(automation_id):
                raise workspace_tools.WorkspaceError("Specify one accessible input control.")
            if not isinstance(text, str) or not text or len(text) > 1000:
                raise workspace_tools.WorkspaceError("Desktop input text must contain 1 to 1,000 characters.")
            if detect_sensitive_data(text):
                raise workspace_tools.WorkspaceError(
                    "Cline cannot type text that appears to contain credentials."
                )
        elif tool == "workspace_window_scroll":
            amount = args.get("amount")
            if type(amount) is not int or not -10 <= amount <= 10 or amount == 0:
                raise workspace_tools.WorkspaceError("Scroll amount must be from -10 to 10, excluding zero.")
        elif tool == "workspace_window_press":
            if args.get("key") not in {
                "tab", "shift+tab", "up", "down", "left", "right",
                "home", "end", "pageup", "pagedown", "esc",
            }:
                raise workspace_tools.WorkspaceError("Only non-submitting navigation keys are available.")
        return args
    if tool == "workspace_open_folder":
        if set(args) - {"path"}:
            raise workspace_tools.WorkspaceError("Unknown folder-opening arguments.")
        path = args.get("path", ".")
        try:
            target = workspace_tools._resolve_workspace_path(
                path, must_exist=True, workspace_root=workspace_root
            )
        except OSError as exc:
            raise workspace_tools.WorkspaceError(
                "The requested project folder does not exist or cannot be opened."
            ) from exc
        if not target.is_dir():
            raise workspace_tools.WorkspaceError(
                "The requested workspace path is not a directory."
            )
        return {"path": path}
    if tool == "workspace_visual_asset_inspect":
        if set(args) - {"path", "limit"}:
            raise workspace_tools.WorkspaceError("Unknown visual asset inspection arguments.")
        return args
    if tool == "workspace_visual_asset_search":
        if set(args) - {
            "query", "orientation", "min_width", "min_height", "limit", "allow_pexels",
        }:
            raise workspace_tools.WorkspaceError("Unknown visual asset search arguments.")
        query = args.get("query")
        if (
            not isinstance(query, str)
            or not 2 <= len(query.strip()) <= 120
            or detect_sensitive_data(query)
            or any(ord(char) < 32 for char in query)
        ):
            raise workspace_tools.WorkspaceError(
                "The visual search query is invalid or contains sensitive information."
            )
        return args
    if tool == "workspace_visual_asset_use":
        if set(args) - {
            "candidate_id", "relative_path", "placement", "output_format", "reuse_authorized",
        }:
            raise workspace_tools.WorkspaceError("Unknown visual asset use arguments.")
        return args
    if tool == "workspace_visual_asset_verify":
        if set(args) - {"check_external_urls"}:
            raise workspace_tools.WorkspaceError("Unknown visual asset verification arguments.")
        return args
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
        if ecosystem not in {"python", "node", "go", "rust", "dotnet", "php", "ruby"} or not isinstance(package, str) or not _PACKAGE_NAME.fullmatch(package):
            raise workspace_tools.WorkspaceError("The requested dependency specification is not allowed.")
    return args


def approval_required(
    mode: ClineMode,
    tool: str,
    args: dict,
    workspace_root: Path,
    *,
    target_window_hwnd: int | None = None,
    target_window_pid: int | None = None,
) -> bool:
    if tool in WINDOW_READ_TOOLS or tool in {
        "workspace_window_scroll", "workspace_window_press", "workspace_window_type",
    }:
        return False
    if tool == "workspace_window_click":
        label = " ".join(
            str(args.get(key, "")) for key in ("name", "automation_id", "role")
        ).casefold()
        risky_terms = (
            "send", "submit", "buy", "purchase", "checkout", "payment", "pay",
            "delete", "remove", "cancel", "confirm", "publish", "share", "install",
            "security", "password", "token", "account", "envoyer", "soumettre",
            "acheter", "paiement", "payer", "supprimer", "effacer", "annuler",
            "confirmer", "publier", "partager", "installer", "compte", "mot de passe",
            "logout", "log out", "sign out", "déconnexion", "deconnexion", "quitter",
        )
        if args.get("role") in {"Button", "CheckBox", "MenuItem", "RadioButton"}:
            return True
        return any(term in label for term in risky_terms)
    if tool in OPEN_FOLDER_TOOLS:
        return True
    if tool in VISUAL_ASSET_TOOLS:
        return True
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
    if tool == "workspace_window_click":
        target = args.get("name") or args.get("automation_id") or "contrôle"
        return f"Cliquer sur « {target} » dans la fenêtre sélectionnée."
    if tool == "workspace_window_type":
        return "Saisir du texte dans un champ de la fenêtre sélectionnée."
    if tool == "workspace_window_press":
        return f"Appuyer sur {args.get('key', '')} dans la fenêtre sélectionnée."
    if tool == "workspace_open_folder":
        folder = Path(str(args.get("path", "."))).name or "."
        return f"Ouvrir le dossier « {folder} » dans l’Explorateur Windows."
    if tool == "workspace_visual_asset_search":
        provider_note = (
            " Pexels is included only if explicitly enabled and configured."
            if args.get("allow_pexels") is True
            else ""
        )
        return (
            f"Envoyer la requête « {args.get('query', '')} » aux fournisseurs d’images "
            f"gratuits Pixabay/Unsplash.{provider_note}"
        )
    if tool == "workspace_visual_asset_use":
        rights_note = (
            " Confirmer que cette image locale a été fournie par l’utilisateur "
            "ou que ses droits d’utilisation ont été vérifiés."
            if str(args.get("candidate_id", "")).startswith("local:")
            else ""
        )
        return (
            f"Enregistrer l’asset {args.get('candidate_id', '')} dans le projet à "
            f"« {args.get('relative_path', '') or args.get('placement', '')} » "
            f"et ajouter ses métadonnées de provenance.{rights_note}"
        )
    if tool == "workspace_visual_asset_verify":
        suffix = (
            " Vérifiera aussi l’accès réseau aux URL Unsplash autorisées."
            if args.get("check_external_urls") is True
            else ""
        )
        return f"Vérifier les images, crédits et métadonnées du projet.{suffix}"
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

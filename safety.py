"""
safety.py — centralized risk classification + confirmation gate.

Single source of truth for:
  * which tools are risky (LOW / MEDIUM / HIGH)
  * whether a specific call (tool + args) requires explicit user confirmation
  * a short human-readable description of what an action will do
  * sanitizing sensitive args before they reach logs / UI / remote bridge

The confirmation gate itself lives in main.py (_execute_tool / _dispatch_tool),
but every decision about risk lives HERE, so a tool can never be gated by
ad-hoc per-tool logic. Extend TOOL_RISK / _ACTION_RISK instead of scattering
checks across the codebase.
"""

import json
import hashlib
import secrets
import threading
from enum import IntEnum
from typing import Any


class Risk(IntEnum):
    LOW = 0      # read-only / harmless — never requires confirmation
    MEDIUM = 1   # can change state, but reversible / low impact
    HIGH = 2     # destructive, irreversible, or arbitrary code — MUST confirm


# ── Per-tool base risk ────────────────────────────────────────────────────────
# Default risk for each tool when it has no action-specific override below.
TOOL_RISK = {
    # Read-only / informational
    "web_search":        Risk.LOW,
    "weather_report":    Risk.LOW,
    "system_status":     Risk.LOW,
    "recall_memory":     Risk.LOW,
    "read_pdf":          Risk.LOW,
    "pdf_qa":            Risk.LOW,
    "read_document":     Risk.LOW,
    "document_qa":       Risk.LOW,
    "search_documents":  Risk.MEDIUM,
    "analyze_data":      Risk.MEDIUM,
    "video_studio":      Risk.MEDIUM,
    "monitor_alerts":    Risk.LOW,
    "pc_health":         Risk.LOW,
    "translate":         Risk.LOW,
    "set_live_translation": Risk.LOW,
    "proactive_suggestions": Risk.LOW,
    "whatsapp_call":       Risk.LOW,
    "flight_finder":     Risk.LOW,
    "youtube_video":     Risk.LOW,
    "daily_briefing":    Risk.LOW,
    "create_presentation": Risk.LOW,
    "create_spreadsheet": Risk.LOW,
    "google_auth_status": Risk.LOW,

    # Style / memory / personality — local, reversible
    "set_mode":          Risk.LOW,
    "set_voice":         Risk.LOW,
    "set_mood":          Risk.LOW,
    "save_memory":       Risk.LOW,

    # Informational system access
    "screen_process":    Risk.LOW,
    "notify":            Risk.LOW,
    "media_control":     Risk.MEDIUM,

    # State-changing but user-friendly
    "open_app":          Risk.MEDIUM,
    "reminder":          Risk.MEDIUM,
    "schedule":          Risk.MEDIUM,
    "wake_word":         Risk.MEDIUM,
    "clipboard":         Risk.MEDIUM,
    "browser_control":   Risk.MEDIUM,
    "workspace_list_files": Risk.LOW,
    "workspace_read_file": Risk.LOW,
    "workspace_search": Risk.LOW,
    "workspace_write_file": Risk.HIGH,
    "workspace_edit_file": Risk.HIGH,
    "workspace_apply_patch": Risk.HIGH,
    "workspace_run_check": Risk.HIGH,
    "computer_settings": Risk.MEDIUM,
    "computer_control":  Risk.MEDIUM,
    "vision_gesture":    Risk.MEDIUM,
    "live_camera":       Risk.MEDIUM,
    "vision_click":      Risk.MEDIUM,
    "screen_process":    Risk.LOW,
    "smart_home_control": Risk.MEDIUM,
    "api_add_key":       Risk.MEDIUM,
    "google_auth":       Risk.MEDIUM,

    # Communicate externally
    "send_message":      Risk.MEDIUM,
    "gmail":             Risk.MEDIUM,

    # Arbitrary / destructive
    "cmd_control":       Risk.HIGH,
    "desktop_control":   Risk.HIGH,
    "code_helper":       Risk.MEDIUM,
    "dev_agent":         Risk.MEDIUM,
    "agent_task":        Risk.MEDIUM,
    "file_controller":   Risk.MEDIUM,
    "task_manager":      Risk.MEDIUM,
    "game_updater":      Risk.HIGH,
    "autostart":         Risk.MEDIUM,
    "calendar":          Risk.MEDIUM,
    "drive":             Risk.MEDIUM,
}


# ── Action-specific risk overrides ────────────────────────────────────────────
# (tool_name, action) -> Risk. High-impact / irreversible actions are HIGH.
# `None` as the action key means "any other action" for that tool.
_ACTION_RISK = {
    "video_studio": {
        "status": Risk.LOW,
        "analyze": Risk.MEDIUM,
        None: Risk.MEDIUM,
    },
    "computer_control": {
        "screen_size": Risk.LOW,
        "screen_info": Risk.LOW,
        "get_screen_info": Risk.LOW,
        "stop": Risk.LOW,
        "mouse_up": Risk.LOW,
        "screen_monitor_status": Risk.LOW,
        "screen_monitor_stop": Risk.LOW,
        "screen_monitor_start": Risk.HIGH,
        "list_windows": Risk.HIGH,
        "windows": Risk.HIGH,
        "what_is_open": Risk.HIGH,
        None: Risk.HIGH,
    },
    "live_camera": {
        "start": Risk.HIGH,
        "stop": Risk.LOW,
        "status": Risk.LOW,
        None: Risk.HIGH,
    },
    "file_controller": {
        "delete": Risk.HIGH,
        "move": Risk.HIGH,
        "rename": Risk.MEDIUM,
        "organize": Risk.HIGH,
        "organize_desktop": Risk.HIGH,
        "undo_organize": Risk.MEDIUM,
        "write": Risk.MEDIUM,
        "unzip": Risk.HIGH,
        "zip": Risk.MEDIUM,
        None: Risk.MEDIUM,
    },
    "cmd_control": {
        None: Risk.HIGH,
    },
    "desktop_control": {
        None: Risk.HIGH,
    },
    "gmail": {
        "send": Risk.HIGH,
        "compose": Risk.HIGH,
        "delete": Risk.HIGH,
        None: Risk.LOW,
    },
    "task_manager": {
        "kill": Risk.HIGH,
        "end": Risk.HIGH,
        "kill_process": Risk.HIGH,
        None: Risk.MEDIUM,
    },
    "autostart": {
        "enable": Risk.MEDIUM,
        "disable": Risk.MEDIUM,
        "add": Risk.MEDIUM,
        "remove": Risk.MEDIUM,
        "delete": Risk.MEDIUM,
        None: Risk.MEDIUM,
    },
    "code_helper": {
        "run": Risk.HIGH,
        "build": Risk.HIGH,
        "screen_debug": Risk.MEDIUM,
        None: Risk.MEDIUM,
    },
    "computer_settings": {
        "wifi_off": Risk.MEDIUM,
        "wifi_on": Risk.MEDIUM,
        "shutdown": Risk.HIGH,
        "restart": Risk.HIGH,
        "sleep": Risk.HIGH,
        "lock": Risk.MEDIUM,
        None: Risk.MEDIUM,
    },
    "calendar": {
        "delete": Risk.MEDIUM,
        "remove": Risk.MEDIUM,
        "cancel": Risk.MEDIUM,
        None: Risk.MEDIUM,
    },
    "drive": {
        "delete": Risk.HIGH,
        "remove": Risk.HIGH,
        None: Risk.MEDIUM,
    },
    "game_updater": {
        "update": Risk.HIGH,
        "close_game": Risk.MEDIUM,
        "quit_game": Risk.MEDIUM,
        None: Risk.HIGH,
    },
    "browser_control": {
        "submit_form": Risk.HIGH,
        None: Risk.MEDIUM,
    },
    "smart_home_control": {
        "unlock": Risk.HIGH,
        None: Risk.MEDIUM,
    },
    "whatsapp_call": {
        "connect": Risk.HIGH,
        "join": Risk.HIGH,
        "resume": Risk.HIGH,
        "unmute": Risk.HIGH,
        None: Risk.LOW,
    },
}

# Params that may carry the user's explicit "yes" — the model must set this to
# True after the user verbally approves a high-risk action.
CONFIRM_PARAM = "confirm"

# One-time token issued when a HIGH-risk call is blocked. The model must echo
# it back on the re-invocation; it is single-use and bound to the exact call.
CONFIRM_TOKEN_PARAM = "confirm_token"

# Message returned to the model when a high-risk tool is called WITHOUT the
# user's consent. The model must relay it, wait for an explicit yes, then
# re-invoke the tool with confirm=true.
CONFIRM_MESSAGE = (
    "⛔ This action requires your permission: {desc}. "
    "I must not run it without the user's explicit approval. "
    "Ask the user: 'May I {desc}?' and WAIT for an explicit yes or no. "
    "Only call this tool again with {param}=true after the user says yes."
)

# ── One-time confirmation tokens (technical enforcement) ─────────────────────
# confirm=true is NOT enough on its own: a HIGH-risk call must present a token
# that was issued by this module when the call was first blocked. The model
# cannot fabricate tokens (they are secrets), and each token is single-use and
# bound to the exact (tool, sanitized args) fingerprint of the blocked call.

_pending_tokens: dict[str, str] = {}
_token_lock = threading.Lock()
_TOKEN_TTL_SECONDS = 600
_screen_ocr_consent_granted = False


def reset_screen_ocr_consent() -> None:
    """Clear the screen-text sharing approval for a new NIANG IA session."""
    global _screen_ocr_consent_granted
    with _token_lock:
        _screen_ocr_consent_granted = False


def _grant_screen_ocr_consent() -> None:
    global _screen_ocr_consent_granted
    with _token_lock:
        _screen_ocr_consent_granted = True


def _fingerprint(name: str, args: dict | None) -> str:
    """Canonical fingerprint of a blocked call, so a token can't be replayed
    against a different tool or different arguments."""
    safe = sanitize(name, args or {})
    if name == "whatsapp_call":
        for key in ("contact_name", "owner_name"):
            if args and key in args:
                safe[f"{key}_fingerprint"] = hashlib.sha256(
                    str(args[key]).encode("utf-8")
                ).hexdigest()
    return json.dumps({"name": name, "args": safe}, sort_keys=True, default=str)


def issue_confirmation_token(name: str, args: dict | None) -> str:
    """Issue a single-use token authorizing THIS exact call after the user
    approves. Called only when the gate blocks a HIGH-risk tool."""
    token = secrets.token_urlsafe(24)
    with _token_lock:
        _pending_tokens[token] = _fingerprint(name, args)
    return token


def redeem_confirmation_token(name: str, args: dict | None, token: str) -> bool:
    """Validate a token issued for this call and consume it (single use).
    Returns False if the token is missing, invalid, expired, or bound to a
    different tool/args — the call stays blocked."""
    if not token:
        return False
    with _token_lock:
        expected = _pending_tokens.pop(token, None)
    if expected is None:
        return False
    if expected != _fingerprint(name, args):
        return False
    return True


def classify(name: str, args: dict | None) -> Risk:
    """Return the risk level for a concrete tool call (name + args)."""
    args = args or {}
    action = str(args.get("action", "")).lower().strip()
    if name == "screen_process":
        return Risk.HIGH
    if name == "computer_settings":
        action = action.replace(" ", "_").replace("-", "_")
        if not action and args.get("description"):
            return Risk.HIGH
        if action in {
            "type_text", "write_on_screen", "type", "write", "press_key",
            "screenshot", "take_screenshot", "capture_screen",
            "copy", "paste", "cut", "save", "save_file", "close_tab",
            "enter", "press_enter",
            "close_app", "close_window", "quit_app", "exit_app", "kill_app",
            "run", "open_run",
        }:
            return Risk.HIGH
    overrides = _ACTION_RISK.get(name)
    if overrides is not None:
        risk = overrides.get(action, overrides.get(None))
        if risk is not None:
            return risk
    return TOOL_RISK.get(name, Risk.MEDIUM)


def needs_confirmation(name: str, args: dict | None, confirm: bool = False,
                       confirm_token: str = "") -> bool:
    """True if this call must not run until the user confirms.

    confirm=true alone does NOT bypass the gate: a valid one-time token issued
    for THIS exact call must be presented too (technical enforcement). This
    stops the model from fabricating a "user said yes" on its own.
    """
    args = args or {}
    if classify(name, args) != Risk.HIGH:
        return False
    screen_ocr = (
        name == "screen_process"
        and str(args.get("angle", "screen")).lower().strip() == "screen"
    )
    if screen_ocr:
        with _token_lock:
            if _screen_ocr_consent_granted:
                return False
    if confirm and redeem_confirmation_token(name, args, confirm_token):
        if screen_ocr:
            _grant_screen_ocr_consent()
        return False
    return True


def describe(name: str, args: dict | None) -> str:
    """Short human-readable description of what an action will do."""
    args = args or {}
    action = str(args.get("action", "")).lower().strip()

    if name == "whatsapp_call" and action in {"connect", "join"}:
        contact = str(args.get("contact_name", "")).strip() or "the manually selected contact"
        return (
            f"join the WhatsApp call with {contact}; live call audio and the "
            "selected display names will be sent to Gemini for AI conversation"
        )
    if name == "whatsapp_call" and action == "resume":
        return "resume sending live WhatsApp call audio to Gemini and the AI voice to the call"
    if name == "computer_control":
        if action in {"screen_describe", "screen_find"}:
            return f"{action.replace('_', ' ')} is disabled to prevent screen images being sent to Gemini"
        if action == "screen_click":
            return "screen-based clicking is disabled to prevent screen images being sent to Gemini"
        if action == "screen_monitor_start":
            return "start local-only screen change sampling with a 30 ms target; no images or text are saved or uploaded"
        if action in {"screen_monitor_status", "screen_monitor_stop"}:
            return f"{action.replace('_', ' ')} for local-only screen change sampling"
        if action in {"screenshot", "copy", "user_data"}:
            return f"read potentially private computer data ({action})"
        return f"control or inspect the Windows interface ({action or 'unspecified action'})"
    if name == "screen_process":
        source = str(args.get("angle", "screen")).lower()
        if source != "camera":
            return (
                "capture the screen locally, extract up to 12,000 characters with "
                "OCR, and send only that text to Gemini; never send the screenshot. "
                "After one explicit approval, this remains allowed for screen OCR "
                "during the current NIANG IA session. The text may contain private "
                "information."
            )
        return (
            "capture the webcam only for this explicit request and send that image "
            "and question to Gemini for analysis"
        )
    if name == "computer_settings":
        action = action.replace(" ", "_").replace("-", "_")
    if name == "computer_settings" and not action and args.get("description"):
        return "ask Gemini to classify the computer-control instruction, then perform its selected action"
    if name == "computer_settings" and action in {"screenshot", "take_screenshot", "capture_screen"}:
        return "capture and analyze the current screen; its image will be sent to Gemini"
    if name == "computer_settings" and action in {
        "type_text", "write_on_screen", "type", "write", "press_key", "paste",
    }:
        return f"type text or send a key to the active Windows application ({action})"

    if name == "file_controller":
        target = args.get("name") or args.get("path") or "item"
        verbs = {
            "delete": f"delete {target}",
            "move": f"move {target}",
            "rename": f"rename {target}",
            "write": f"write to {target}",
            "unzip": f"extract archive to {args.get('destination', 'target folder')}",
            "organize": f"organize files in {args.get('scope', 'desktop')}",
            "organize_desktop": "organize desktop files",
        }
        return verbs.get(action, f"{action} {target}")

    if name == "live_camera" and action == "start":
        return "start streaming webcam frames to Gemini for this conversation"

    if name == "cmd_control":
        cmd = args.get("command") or args.get("cmd") or args.get("text") or ""
        return f"run the command: {cmd[:80]}"

    if name == "desktop_control":
        script = args.get("script") or args.get("code") or args.get("text") or ""
        return f"run this code on the desktop: {script[:80]}"

    if name == "gmail" and action in ("send", "compose"):
        return f"send an email to {args.get('to', args.get('recipient', 'recipient'))}"

    if name == "task_manager" and action in ("kill", "end", "kill_process"):
        return f"kill the process {args.get('process', args.get('name', 'unknown'))}"

    if name == "code_helper" and action in ("run", "build"):
        return f"{action} code for {args.get('file_path', args.get('description', 'the task'))}"

    if name in ("game_updater",):
        return f"update the game {args.get('game', '')}"

    if name == "computer_settings" and action in ("shutdown", "restart", "sleep"):
        return f"{action} the computer"

    if name == "drive" and action in ("delete", "remove"):
        return f"delete {args.get('file_id', args.get('name', 'a file'))} from Drive"

    if name == "browser_control" and action == "submit_form":
        target = args.get("text") or args.get("selector") or "the current form"
        return f"submit the form using {target}; this may save or change website data"

    if name == "workspace_write_file":
        return f"create or replace {args.get('path', 'a file')} inside the configured workspace"
    if name == "workspace_edit_file":
        return f"edit {args.get('path', 'a file')} inside the configured workspace"
    if name == "workspace_apply_patch":
        return "apply a verified code patch to existing files inside the configured workspace"
    if name == "workspace_run_check":
        return (
            f"run the approved {args.get('check', 'project')} check in the configured "
            "workspace as the current Windows user"
        )

    if name == "smart_home_control":
        target = args.get("area") or args.get("device", "smart home device")
        return f"{action} {target}"

    # Fallback: tool name + first couple of args
    brief = " ".join(str(v) for v in args.values())[:60]
    return f"{name} ({brief})" if brief else name


# ── Secret redaction for logs / UI / remote ──────────────────────────────────
_SECRET_KEYS = {
    "api_key", "api_key_id", "apikey", "token", "access_token", "auth_token",
    "password", "passwd", "secret", "client_secret", "code", "key",
}


def sanitize(name: str, args: dict | None) -> dict:
    """Return args with sensitive values masked, safe for logging/UI/remote."""
    if not args:
        return {}
    safe = {}
    for k, v in args.items():
        lk = str(k).lower()
        if (
            name in {
                "workspace_write_file", "workspace_edit_file",
                "workspace_apply_patch",
            }
            and lk in {"content", "find", "replace", "patch"}
        ):
            safe[k] = "[source content redacted]"
        elif (
            name in {"computer_control", "computer_settings", "screen_process"}
            and lk in {"text", "value", "description", "expected", "path", "image", "title"}
        ):
            safe[k] = "[private]"
        elif name == "whatsapp_call" and lk in {"contact_name", "owner_name"}:
            safe[k] = "[private]"
        elif lk in _SECRET_KEYS or "token" in lk or "key" in lk or "secret" in lk:
            safe[k] = "***"
        elif isinstance(v, dict):
            safe[k] = sanitize(name, v)
        elif isinstance(v, list):
            safe[k] = [sanitize(name, {"i": x})["i"] if isinstance(x, dict) else x for x in v]
        else:
            safe[k] = v
    return safe
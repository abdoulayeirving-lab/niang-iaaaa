from __future__ import annotations

import json

from agent.secrets import detect_sensitive_data
from agent.windows_desktop import WindowsDesktopAgent, WindowsDesktopError


_OBSERVABLE_ROLES = {
    "Button",
    "CheckBox",
    "ComboBox",
    "Edit",
    "Hyperlink",
    "ListItem",
    "MenuItem",
    "RadioButton",
    "TabItem",
    "TreeItem",
}
_CLICKABLE_ROLES = _OBSERVABLE_ROLES - {"ComboBox", "Edit"}
_EDIT_ROLES = {"ComboBox", "Edit"}
_SENSITIVE_FIELD_TERMS = (
    "password", "passwd", "secret", "token", "credential", "passcode",
    "api key", "api_key", "apikey", "private key", "mot de passe",
)


def _is_sensitive_control(control: dict) -> bool:
    if control.get("password") is True:
        return True
    metadata = f"{control.get('name', '')} {control.get('automation_id', '')}".casefold()
    return (
        detect_sensitive_data(metadata)
        or any(term in metadata for term in _SENSITIVE_FIELD_TERMS)
    )


def _selected_window(hwnd: int | None, pid: int | None, agent=None) -> tuple[WindowsDesktopAgent, dict]:
    if type(hwnd) is not int or hwnd <= 0 or type(pid) is not int or pid <= 0:
        raise WindowsDesktopError("Choose a visible desktop window before starting Cline.")
    desktop = agent or WindowsDesktopAgent()
    window = desktop.window(hwnd=hwnd)
    if window["pid"] != pid:
        raise WindowsDesktopError("The selected window changed; select it again before continuing.")
    if not window["visible"] or window["minimized"]:
        raise WindowsDesktopError("Restore the selected window before Cline interacts with it.")
    return desktop, window


def _control(
    desktop: WindowsDesktopAgent,
    hwnd: int,
    *,
    name: str = "",
    automation_id: str = "",
    roles: set[str],
) -> dict:
    if bool(name) == bool(automation_id):
        raise WindowsDesktopError("Specify exactly one accessible control name or automation ID.")
    requested = str(name if name else automation_id).strip()
    if not requested or len(requested) > 160 or detect_sensitive_data(requested):
        raise WindowsDesktopError("The requested control identifier is invalid or sensitive.")
    matches = [
        item for item in desktop.controls(hwnd, limit=500)
        if (
            (item.get("name", "").casefold() == requested.casefold())
            if name
            else (item.get("automation_id") == requested)
        )
    ]
    if len(matches) != 1:
        detail = "not found" if not matches else f"ambiguous ({len(matches)} matches)"
        raise WindowsDesktopError(f"The selected window control is {detail}.")
    control = matches[0]
    if control.get("role") not in roles:
        raise WindowsDesktopError("This kind of control is not available for the requested action.")
    if control.get("visible") is not True or control.get("enabled") is not True:
        raise WindowsDesktopError("The selected control is not visible and enabled.")
    if _is_sensitive_control(control):
        raise WindowsDesktopError("Cline cannot interact with password fields.")
    return control


def observe_window(hwnd: int | None, pid: int | None) -> str:
    desktop, window = _selected_window(hwnd, pid)
    controls = []
    for item in desktop.controls(window["hwnd"], limit=200):
        role = item.get("role")
        name = str(item.get("name", "")).strip()
        if (
            role not in _OBSERVABLE_ROLES
            or item.get("visible") is not True
            or _is_sensitive_control(item)
            or not name
            or detect_sensitive_data(name)
        ):
            continue
        controls.append({
            "name": name[:160],
            "role": role,
            "automation_id": str(item.get("automation_id", ""))[:120],
            "enabled": item.get("enabled"),
        })
    return json.dumps({"controls": controls[:100]}, ensure_ascii=False)


def click_control(
    hwnd: int | None,
    pid: int | None,
    *,
    name: str = "",
    automation_id: str = "",
    role: str,
) -> str:
    desktop, window = _selected_window(hwnd, pid)
    control = _control(
        desktop,
        window["hwnd"],
        name=name,
        automation_id=automation_id,
        roles=_CLICKABLE_ROLES,
    )
    if role != control["role"]:
        raise WindowsDesktopError("The selected control role changed; observe the window again.")
    result = desktop.click(
        window["hwnd"],
        name=name or None,
        automation_id=automation_id or None,
    )
    return json.dumps(result, ensure_ascii=False)


def type_into_control(
    hwnd: int | None,
    pid: int | None,
    *,
    name: str = "",
    automation_id: str = "",
    text: str,
) -> str:
    desktop, window = _selected_window(hwnd, pid)
    if not isinstance(text, str) or not text or len(text) > 1000:
        raise WindowsDesktopError("Text input must contain 1 to 1,000 characters.")
    if detect_sensitive_data(text):
        raise WindowsDesktopError("Cline cannot type text that appears to contain credentials.")
    control = _control(
        desktop,
        window["hwnd"],
        name=name,
        automation_id=automation_id,
        roles=_EDIT_ROLES,
    )
    result = desktop.type_text(
        window["hwnd"],
        text,
        name=name or None,
        automation_id=automation_id or None,
    )
    return json.dumps(
        {"role": control["role"], "verified": result["verified"]},
        ensure_ascii=False,
    )


def scroll_window(hwnd: int | None, pid: int | None, amount: int) -> str:
    desktop, window = _selected_window(hwnd, pid)
    if type(amount) is not int or not -10 <= amount <= 10 or amount == 0:
        raise WindowsDesktopError("Scroll amount must be from -10 to 10, excluding zero.")
    return json.dumps(desktop.scroll(window["hwnd"], amount), ensure_ascii=False)


def press_window_key(hwnd: int | None, pid: int | None, key: str) -> str:
    desktop, window = _selected_window(hwnd, pid)
    allowed = {"tab", "shift+tab", "up", "down", "left", "right", "home", "end", "pageup", "pagedown", "esc"}
    normalized = str(key or "").strip().casefold()
    if normalized not in allowed:
        raise WindowsDesktopError("Only non-submitting navigation keys are available to Cline.")
    return json.dumps(desktop.press(window["hwnd"], normalized), ensure_ascii=False)

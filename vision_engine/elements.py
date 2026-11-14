"""Interactive element discovery through Windows UI Automation.

`pywinauto` is optional and can block for a long time when the inspected
application is busy, so every inspection runs in a helper thread with a hard
timeout.  A timeout never breaks the vision engine: it simply reports that
the element list is unavailable for this observation.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

# UI Automation control type -> NIANG element kind.
ROLE_KINDS: dict[str, str] = {
    "Button": "button",
    "SplitButton": "button",
    "Hyperlink": "item",
    "Edit": "field",
    "Document": "field",
    "ComboBox": "field",
    "CheckBox": "field",
    "RadioButton": "field",
    "MenuItem": "menu",
    "Menu": "menu",
    "MenuBar": "menu",
    "ListItem": "item",
    "TreeItem": "item",
    "TabItem": "item",
    "ToolBar": "other",
    "StatusBar": "other",
    "TitleBar": "other",
    "Pane": "other",
    "Group": "other",
    "Text": "text",
    "Image": "icon",
    "Custom": "other",
}


@dataclass(slots=True)
class InteractiveElement:
    """A control the user could interact with."""

    name: str = ""
    role: str = ""
    kind: str = "other"
    bounds: dict[str, int] = field(default_factory=dict)
    enabled: bool = True
    visible: bool = True
    automation_id: str = ""
    sensitive: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "kind": self.kind,
            "bounds": dict(self.bounds),
            "enabled": self.enabled,
            "visible": self.visible,
            "automation_id": self.automation_id,
            "sensitive": self.sensitive,
        }

    def label(self) -> str:
        if self.name:
            return f"{self.name} ({self.role})"
        return self.role or "element"


class UIAInspector:
    """Reads the accessible control tree of a window."""

    def __init__(self, max_controls: int = 120, timeout: float = 4.0) -> None:
        self.max_controls = int(max_controls)
        self.timeout = float(timeout)
        self._error: str | None = None

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def available(self) -> bool:
        try:
            import pywinauto  # noqa: F401
        except Exception:
            return False
        return True

    # ── Public API ──────────────────────────────────────────────────────────
    def inspect(self, hwnd: int) -> list[InteractiveElement]:
        """Return the interactive elements of ``hwnd`` (empty list on failure)."""
        try:
            hwnd = int(hwnd)
        except (TypeError, ValueError):
            self._error = "A valid window handle is required to inspect elements."
            return []
        if hwnd <= 0:
            self._error = "A valid window handle is required to inspect elements."
            return []

        result: dict[str, Any] = {}

        def worker() -> None:
            try:
                result["elements"] = self._collect(hwnd)
            except Exception as exc:
                result["error"] = str(exc)

        thread = threading.Thread(
            target=worker, name="NIANG-VisionUIA", daemon=True
        )
        thread.start()
        thread.join(self.timeout)
        if thread.is_alive():
            self._error = (
                f"UI Automation timed out after {self.timeout:.1f}s "
                "(the application is busy or unresponsive)."
            )
            return []
        if "error" in result:
            self._error = f"UI Automation failed: {result['error']}"
            return []
        self._error = None
        return list(result.get("elements", []))

    # ── Internals ───────────────────────────────────────────────────────────
    def _collect(self, hwnd: int) -> list[InteractiveElement]:
        from pywinauto import Desktop

        root = Desktop(backend="uia").window(handle=hwnd).wrapper_object()
        descendants = root.descendants()
        elements: list[InteractiveElement] = []
        for control in descendants:
            if len(elements) >= self.max_controls:
                break
            try:
                info = control.element_info
                role = str(getattr(info, "control_type", "") or "")
                if not role:
                    continue
                kind = ROLE_KINDS.get(role)
                if kind is None:
                    continue
                rectangle = control.rectangle()
                name = str(getattr(info, "name", "") or "")
                elements.append(
                    InteractiveElement(
                        name=name[:200],
                        role=role,
                        kind=kind,
                        bounds={
                            "left": int(rectangle.left),
                            "top": int(rectangle.top),
                            "width": int(rectangle.width()),
                            "height": int(rectangle.height()),
                        },
                        enabled=_safe_bool(control, "is_enabled"),
                        visible=_safe_bool(control, "is_visible"),
                        automation_id=str(getattr(info, "automation_id", "") or "")[:120],
                    )
                )
            except Exception:
                continue
        return elements


def _safe_bool(control: Any, method: str) -> bool:
    try:
        value = getattr(control, method)()
        return bool(value)
    except Exception:
        return True


__all__ = ["UIAInspector", "InteractiveElement", "ROLE_KINDS"]

"""Shared tool metadata and invocation for live and autonomous agent turns."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from threading import Event
from typing import Any, Callable


AGENT_ENABLED_TOOLS = frozenset({
    "open_app", "web_search", "game_updater", "browser_control",
    "file_controller", "notify", "daily_briefing", "wake_word",
    "cmd_control", "computer_settings", "computer_control", "system_status",
    "windows_diagnostics", "windows_repair", "task_manager", "clipboard",
    "recall_memory", "vision_gesture", "screen_process", "send_message",
    "reminder", "desktop_control", "youtube_video", "weather_report",
    "flight_finder", "code_helper", "dev_agent", "vision_click", "gmail",
    "read_pdf", "pdf_qa", "autostart", "monitor_alerts", "email_watch",
    "pc_health", "translate", "media_control", "read_document",
    "document_qa", "search_documents", "calendar", "drive", "schedule",
    "create_presentation", "create_spreadsheet", "smart_home_control",
    "create_document", "analyze_data", "workspace_list_files",
    "workspace_read_file", "workspace_write_file", "workspace_edit_file",
    "workspace_apply_patch", "workspace_search", "workspace_run_check",
    "terminal_control", "project_execution",
})


class ToolRegistryError(ValueError):
    """Raised when tool metadata or an invocation is invalid."""


class ToolExecutionResult(str):
    """Text-compatible result carrying execution and verification metadata."""

    def __new__(
        cls,
        tool_name: str,
        content: str,
        *,
        ok: bool = True,
        status: str = "returned",
        verified: bool = False,
        error_kind: str = "",
    ):
        instance = super().__new__(cls, content)
        instance.tool_name = tool_name
        instance.ok = ok
        instance.status = status
        instance.verified = verified
        instance.error_kind = error_kind
        return instance


@dataclass(frozen=True)
class ToolExecutionContext:
    mission_id: str | None = None
    cancel_flag: Event | None = None
    speak: Callable[..., Any] | None = None
    agent_mode: bool = False


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], ToolExecutionContext], Any] | None
    timeout_seconds: float
    agent_enabled: bool
    permission_level: str = "runtime-policy"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        if not tool.name or tool.name in self._tools:
            raise ToolRegistryError(f"Tool name is empty or already registered: {tool.name!r}.")
        if not isinstance(tool.parameters, dict):
            raise ToolRegistryError(f"Tool '{tool.name}' must have an object parameter schema.")
        if tool.timeout_seconds <= 0:
            raise ToolRegistryError(f"Tool '{tool.name}' must have a positive timeout.")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def names(self, *, agent_only: bool = False) -> tuple[str, ...]:
        return tuple(
            name for name, tool in self._tools.items()
            if tool.handler is not None and (not agent_only or tool.agent_enabled)
        )

    def definitions(self, *, agent_only: bool = False) -> tuple[ToolDefinition, ...]:
        return tuple(
            tool for tool in self._tools.values()
            if tool.handler is not None and (not agent_only or tool.agent_enabled)
        )

    def function_declarations(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": copy.deepcopy(tool.parameters),
            }
            for tool in self._tools.values()
        ]

    def planner_catalog(self) -> str:
        catalog = [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "permission_level": tool.permission_level,
            }
            for tool in self.definitions(agent_only=True)
        ]
        import json

        return json.dumps(catalog, ensure_ascii=False, indent=2)

    def invoke(
        self,
        name: str,
        parameters: dict[str, Any],
        context: ToolExecutionContext | None = None,
    ) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolRegistryError(f"Unknown tool '{name}'.")
        if tool.handler is None:
            raise ToolRegistryError(f"Tool '{name}' has no execution handler.")
        if not isinstance(parameters, dict):
            raise ToolRegistryError(f"Tool '{name}' parameters must be an object.")
        if context and context.agent_mode and not tool.agent_enabled:
            raise ToolRegistryError(f"Tool '{name}' is not enabled for autonomous missions.")
        self.validate_parameters(name, parameters)
        raw_result = tool.handler(dict(parameters), context or ToolExecutionContext())
        if isinstance(raw_result, ToolExecutionResult):
            return raw_result
        if raw_result is None or raw_result == "":
            return ToolExecutionResult(
                name,
                f"Tool '{name}' returned no result; its outcome could not be verified.",
                ok=False,
                status="unknown",
                error_kind="unknown",
            )

        content = str(raw_result)
        verified = False
        if name == "workspace_run_check":
            verified = content.startswith("Check ") and " passed." in content
        elif name in {"terminal_control", "project_execution"}:
            try:
                details = json.loads(content)
            except json.JSONDecodeError:
                details = None
            if isinstance(details, dict):
                if name == "terminal_control":
                    verified = (
                        details.get("status") == "completed"
                        and details.get("exit_code") == 0
                    ) or (
                        details.get("action_status") == "running"
                        and details.get("state") == "running"
                    )
                else:
                    verified = details.get("verified") is True
        elif name == "computer_control":
            try:
                details = json.loads(content)
            except json.JSONDecodeError:
                details = None
            verified = (
                isinstance(details, dict)
                and details.get("executed") is True
                and details.get("verified") is True
            )
        elif name == "browser_control":
            action = str(parameters.get("action", "")).casefold()
            if action in {"state", "inspect", "get_text"}:
                verified = not content.casefold().startswith(
                    ("could not ", "blocked ", "navigation error:", "browser error:")
                )
            elif action == "go_to":
                requested_url = parameters.get("url")
                verified = (
                    isinstance(requested_url, str)
                    and requested_url in content
                    and content.casefold().startswith(("opened", "navigated"))
                )
        return ToolExecutionResult(name, content, verified=verified)

    def validate_parameters(self, name: str, parameters: dict[str, Any]) -> None:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolRegistryError(f"Unknown tool '{name}'.")
        if not isinstance(parameters, dict):
            raise ToolRegistryError(f"Tool '{name}' parameters must be an object.")
        schema = tool.parameters
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise ToolRegistryError(f"Tool '{name}' has a malformed parameter schema.")

        missing = [key for key in required if key not in parameters]
        if missing:
            raise ToolRegistryError(
                f"Tool '{name}' is missing required parameter(s): {', '.join(missing)}."
            )

        type_names = {
            "STRING": str,
            "OBJECT": dict,
            "ARRAY": list,
            "BOOLEAN": bool,
        }
        for key, value in parameters.items():
            spec = properties.get(key)
            if value is None or not isinstance(spec, dict):
                continue
            expected = str(spec.get("type", "")).upper()
            if expected == "INTEGER":
                valid = type(value) is int
            elif expected == "NUMBER":
                valid = type(value) in (int, float)
            elif expected in type_names:
                valid = isinstance(value, type_names[expected])
            else:
                continue
            if not valid:
                raise ToolRegistryError(
                    f"Tool '{name}' parameter '{key}' must be {expected.lower()}."
                )


def build_tool_registry(
    declarations: list[dict[str, Any]],
    handlers: dict[str, tuple[Callable[..., Any], float]],
    *,
    agent_tools: frozenset[str] = AGENT_ENABLED_TOOLS,
    context_handlers: dict[
        str, Callable[[dict[str, Any], ToolExecutionContext], Any]
    ] | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    context_handlers = context_handlers or {}
    seen: set[str] = set()

    for declaration in declarations:
        name = declaration.get("name")
        if not isinstance(name, str) or not name:
            raise ToolRegistryError("Every function declaration must have a non-empty name.")
        if name in seen:
            raise ToolRegistryError(f"Duplicate function declaration: {name}.")
        seen.add(name)

        entry = handlers.get(name)
        handler = None
        timeout = 60.0
        if entry is not None:
            base_handler, timeout = entry
            handler = context_handlers.get(name)
            if handler is None:
                handler = lambda args, _context, fn=base_handler: fn(args)

        registry.register(ToolDefinition(
            name=name,
            description=str(declaration.get("description", "")),
            parameters=copy.deepcopy(declaration.get("parameters", {})),
            handler=handler,
            timeout_seconds=float(timeout),
            agent_enabled=name in agent_tools,
            permission_level=(
                "operation-specific-confirmation"
                if name in {"terminal_control", "project_execution"}
                else "runtime-policy"
            ),
        ))

    return registry

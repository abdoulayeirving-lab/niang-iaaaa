"""Validated read-only adapter for the external Agent-Reach CLI."""

from __future__ import annotations

from threading import Event
from typing import Any

from agent.secrets import detect_sensitive_data

from .client import AgentReachClient, AgentReachError
from .command_registry import (
    COMMANDS,
    MAX_QUERY_CHARS,
    MAX_RESULTS,
    MAX_TIMEOUT_SECONDS,
)
from .health import discover_capabilities
from .models import ChannelStatus
from .result_parser import AgentReachProtocolError, parse_envelope
from .security import (
    AgentReachInputError,
    validate_channel_input,
    validate_option,
)


class AgentReachAdapter:
    def __init__(self, client: AgentReachClient | None = None):
        self.client = client or AgentReachClient()

    def execute(
        self,
        parameters: dict[str, Any],
        *,
        cancel_event: Event | None = None,
    ) -> dict[str, Any]:
        if not isinstance(parameters, dict):
            raise AgentReachInputError("Agent-Reach parameters must be an object.")
        action = parameters.get("action")
        channel = parameters.get("channel")
        if action == "status":
            if set(parameters) - {"action"}:
                raise AgentReachInputError("Status does not accept additional arguments.")
            return {
                "ok": True,
                "capabilities": [
                    entry.to_dict() for entry in discover_capabilities(self.client, cancel_event)
                ],
                "content_trust": "local_capability_metadata",
            }
        spec = COMMANDS.get((channel, action))
        if spec is None:
            raise AgentReachInputError("This Agent-Reach channel/action is not allowed.")
        allowed = {"action", "channel"}
        if spec.input_name:
            allowed.add(spec.input_name)
        allowed.update(spec.options)
        if set(parameters) - allowed:
            raise AgentReachInputError("Arguments not declared for this channel action are not allowed.")
        capabilities = {
            entry.name: entry
            for entry in discover_capabilities(self.client, cancel_event)
        }
        capability = capabilities.get(channel)
        if capability is None:
            return _blocked_result(channel, action, ChannelStatus.DISABLED.value, "Channel is not declared by this Agent-Reach build.")
        if action not in capability.actions:
            status = capability.status
            if status not in {ChannelStatus.UNAVAILABLE, ChannelStatus.DISABLED}:
                status = ChannelStatus.NEEDS_CONFIGURATION
            return _blocked_result(channel, action, status.value, capability.message)
        if capability.status in {ChannelStatus.UNAVAILABLE, ChannelStatus.DISABLED} or (
            not spec.public_without_login
            and capability.status != ChannelStatus.AVAILABLE
        ):
            return _blocked_result(channel, action, capability.status.value, capability.message)

        args = [channel, action]
        if spec.input_name:
            value = validate_channel_input(parameters.get(spec.input_name), spec.input_kind)
            if spec.input_kind == "query" and len(value) > MAX_QUERY_CHARS:
                raise AgentReachInputError("The query is too long.")
            args.append(value)
        for option in spec.options:
            if option == "limit":
                option_value = validate_option(parameters.get(option, MAX_RESULTS), option)
            elif option == "lang":
                option_value = validate_option(parameters.get(option, "fr,en"), option)
            elif option in parameters:
                option_value = validate_option(parameters[option], option)
            else:
                continue
            args.extend([f"--{option}", option_value])
        if spec.backend:
            args.extend(["--backend", spec.backend])

        sensitive = detect_sensitive_data(" ".join(args))
        if sensitive:
            raise AgentReachInputError("Sensitive data was detected; the request was not sent.")
        try:
            return parse_envelope(
                self.client.run(
                    [*args, "--timeout", str(MAX_TIMEOUT_SECONDS)],
                    timeout=MAX_TIMEOUT_SECONDS,
                    cancel_event=cancel_event,
                ),
                expected_channel=channel,
                expected_action=action,
            )
        except AgentReachError as exc:
            return {
                "ok": False,
                "channel": channel,
                "action": action,
                "items": [],
                "error": {"code": exc.code, "message": str(exc)},
                "content_trust": "local_execution_status",
            }
        except AgentReachProtocolError as exc:
            return {
                "ok": False,
                "channel": channel,
                "action": action,
                "items": [],
                "error": {"code": "INVALID_RESULT", "message": str(exc)},
                "content_trust": "local_execution_status",
            }


def _blocked_result(channel: str, action: str, status: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "channel": channel,
        "action": action,
        "items": [],
        "error": {
            "code": status,
            "message": message or f"Agent-Reach channel is {status}.",
        },
        "content_trust": "local_capability_metadata",
    }

"""Read-only local capability discovery; live availability requires explicit checks."""

from __future__ import annotations

import re
from threading import Event
from typing import Any

from .client import AgentReachClient, AgentReachError
from .command_registry import COMMANDS, SAFE_ACTIONS, SUPPORTED_CHANNELS
from .models import ChannelCapability, ChannelStatus
from .result_parser import AgentReachProtocolError, parse_management_output
from .security import session_reuse_allowed


_STATUS_MAP = {
    "ready": ChannelStatus.AVAILABLE,
    "available": ChannelStatus.AVAILABLE,
    "search_ready": ChannelStatus.AVAILABLE,
    "needs_login": ChannelStatus.NEEDS_AUTH,
    "needs_auth": ChannelStatus.NEEDS_AUTH,
    "needs_setup": ChannelStatus.NEEDS_CONFIGURATION,
    "needs_configuration": ChannelStatus.NEEDS_CONFIGURATION,
    "unverified": ChannelStatus.NEEDS_CONFIGURATION,
    "not_added": ChannelStatus.NEEDS_CONFIGURATION,
    "cooldown": ChannelStatus.DEGRADED,
    "degraded": ChannelStatus.DEGRADED,
    "needs_user_action": ChannelStatus.DEGRADED,
    "broken": ChannelStatus.DEGRADED,
    "unavailable": ChannelStatus.UNAVAILABLE,
    "disabled": ChannelStatus.DISABLED,
}
_CHANNEL_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,40}$")


def _unavailable(message: str = "") -> list[ChannelCapability]:
    return [
        ChannelCapability(
            name,
            ChannelStatus.UNAVAILABLE,
            actions,
            message or "Agent-Reach CLI is not installed or configured.",
        )
        for name, actions in SAFE_ACTIONS.items()
    ]


def discover_capabilities(
    client: AgentReachClient,
    cancel_event: Event | None = None,
) -> list[ChannelCapability]:
    if not client.find_executable():
        return _unavailable()
    try:
        channels = parse_management_output(
            client.run(("channels",), cancel_event=cancel_event), action="channels"
        ).get("channels")
        doctor = parse_management_output(
            client.run(("doctor",), cancel_event=cancel_event), action="doctor"
        ).get("result")
    except AgentReachError as exc:
        if exc.code == "CANCELLED":
            raise
        return _unavailable(str(exc))
    except AgentReachProtocolError as exc:
        return [
            ChannelCapability(name, ChannelStatus.DEGRADED, actions, str(exc))
            for name, actions in SAFE_ACTIONS.items()
        ]
    if not isinstance(channels, list) or not isinstance(doctor, dict):
        raise AgentReachProtocolError("Agent-Reach capability report has an invalid shape.")

    declared: dict[str, set[str]] = {}
    for channel in channels:
        if not isinstance(channel, dict) or not isinstance(channel.get("name"), str):
            continue
        actions = channel.get("actions")
        declared[channel["name"]] = {
            item["name"] for item in actions
            if isinstance(actions, list) and isinstance(item, dict) and isinstance(item.get("name"), str)
        } if isinstance(actions, list) else set()

    records = doctor.get("channels")
    if not isinstance(records, list):
        raise AgentReachProtocolError("Agent-Reach doctor report has no channel status list.")
    current: dict[str, dict[str, Any]] = {
        item["channel"]: item
        for item in records
        if isinstance(item, dict) and isinstance(item.get("channel"), str)
    }
    capabilities = []
    known_names = set(SUPPORTED_CHANNELS)
    allow_session_reuse = session_reuse_allowed()
    for name, safe_actions in SAFE_ACTIONS.items():
        supported = declared.get(name)
        if supported is None:
            capabilities.append(ChannelCapability(
                name,
                ChannelStatus.DISABLED,
                message="This channel is not declared by the installed Agent-Reach version.",
            ))
            continue
        actions = tuple(
            action
            for action in safe_actions
            if action in supported
            and (
                allow_session_reuse
                or COMMANDS[(name, action)].public_without_login
            )
        )
        record = current.get(name, {})
        status = _STATUS_MAP.get(record.get("status"), ChannelStatus.DEGRADED)
        message = "; ".join(record.get("problems", [])) if isinstance(record.get("problems"), list) else ""
        has_session_actions = any(
            action in supported
            and not COMMANDS[(name, action)].public_without_login
            for action in safe_actions
        )
        if name == "xiaoyuzhou":
            status = ChannelStatus.DISABLED
            message = "Podcast transcription is installed but disabled until a DPAPI-protected provider key and per-request approval are available."
        elif not actions:
            status = (
                ChannelStatus.NEEDS_CONFIGURATION
                if has_session_actions and not allow_session_reuse
                else ChannelStatus.DISABLED
            )
            message = (
                "Local browser-session reuse requires explicit consent."
                if has_session_actions and not allow_session_reuse
                else "No public, read-only action is allowlisted for this channel."
            )
        elif not allow_session_reuse and has_session_actions:
            message = (
                (message + "; ") if message else ""
            ) + "Browser-session actions are hidden until local session reuse is explicitly authorized."
        capabilities.append(ChannelCapability(name, status, actions, message))
    for name in declared:
        if name not in known_names and _CHANNEL_NAME.fullmatch(name):
            capabilities.append(ChannelCapability(
                name,
                ChannelStatus.DISABLED,
                message="This Agent-Reach connector has no NIANG IA allowlisted actions.",
            ))
    return capabilities

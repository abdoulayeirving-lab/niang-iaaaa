"""Strict parsing of Agent-Reach's versioned JSON result envelopes."""

from __future__ import annotations

import json
import math
from typing import Any
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agent.secrets import detect_sensitive_data, redact_if_sensitive

from .command_registry import MAX_RESULTS, MAX_TEXT_CHARS


class AgentReachProtocolError(ValueError):
    """Agent-Reach returned malformed or over-sized output."""


_SENSITIVE_QUERY_KEY = re.compile(
    r"(?i)(?:token|secret|password|passwd|auth|cookie|session|signature|credential|api[_-]?key)"
)


def _safe_source(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return None
        query = urlencode([
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if not _SENSITIVE_QUERY_KEY.search(key)
            and not detect_sensitive_data(f"{key}={item}")
        ])
        return urlunsplit((parts.scheme, parts.hostname, parts.path, query, ""))
    except ValueError:
        return None


def parse_envelope(
    text: str,
    *,
    expected_channel: str | None = None,
    expected_action: str | None = None,
) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise AgentReachProtocolError("Agent-Reach returned invalid JSON.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise AgentReachProtocolError("Agent-Reach returned an unsupported result schema.")
    if not isinstance(payload.get("ok"), bool):
        raise AgentReachProtocolError("Agent-Reach result is missing its success status.")
    if expected_channel and payload.get("channel") != expected_channel:
        raise AgentReachProtocolError("Agent-Reach returned a result for an unexpected channel.")
    if expected_action and payload.get("action") != expected_action:
        raise AgentReachProtocolError("Agent-Reach returned a result for an unexpected action.")
    error = payload.get("error")
    if error is not None:
        if not isinstance(error, dict):
            raise AgentReachProtocolError("Agent-Reach returned a malformed error.")
        return {
            "ok": False,
            "channel": payload.get("channel"),
            "action": payload.get("action"),
            "backend": None,
            "items": [],
            "error": {
                "code": str(error.get("code", "UNKNOWN"))[:80],
                "message": _redact(str(error.get("message", "The request failed."))[:500]),
                "hint": _redact(str(error.get("hint", ""))[:500]),
            },
            "meta": _safe_meta(payload.get("meta")),
        }
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise AgentReachProtocolError("Agent-Reach returned an invalid result list.")
    items = []
    for raw in raw_items[:MAX_RESULTS]:
        if not isinstance(raw, dict):
            raise AgentReachProtocolError("Agent-Reach returned a malformed result item.")
        text_value = raw.get("text")
        title = raw.get("title")
        items.append({
            "title": _redact(title[:1000]) if isinstance(title, str) else None,
            "url": _safe_source(raw.get("url")),
            "author": _redact(raw.get("author")[:500]) if isinstance(raw.get("author"), str) else None,
            "published_at": (
                _redact(raw.get("published_at")[:100])
                if isinstance(raw.get("published_at"), str) else None
            ),
            "text": _redact(text_value[:MAX_TEXT_CHARS]) if isinstance(text_value, str) else None,
        })
    return {
        "ok": True,
        "channel": payload.get("channel"),
        "action": payload.get("action"),
        "backend": _redact(str(payload.get("backend") or "")[:100]),
        "items": items,
        "error": None,
        "meta": _safe_meta(payload.get("meta")),
        "content_trust": "untrusted_external_data",
    }


def _redact(value: str) -> str:
    return redact_if_sensitive(value, "[redacted: content may contain a secret]")


def _safe_meta(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    attempts = value.get("attempts")
    safe_attempts = []
    if isinstance(attempts, list):
        for item in attempts[:8]:
            if not isinstance(item, dict):
                continue
            safe_attempts.append({
                key: _redact(str(item[key])[:100])
                for key in ("backend", "result")
                if isinstance(item.get(key), (str, int, float))
            })
    elapsed = value.get("elapsed_ms")
    return {
        "elapsed_ms": max(0, min(int(elapsed), 86_400_000))
        if isinstance(elapsed, (int, float))
        and not isinstance(elapsed, bool)
        and math.isfinite(elapsed)
        else None,
        "attempts": safe_attempts,
    }


def parse_management_output(text: str, *, action: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise AgentReachProtocolError("Agent-Reach returned invalid management JSON.") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise AgentReachProtocolError("Agent-Reach returned an unsupported management result.")
    if action == "channels":
        if payload.get("ok") is not True or not isinstance(payload.get("channels"), list):
            raise AgentReachProtocolError("Agent-Reach returned an invalid channel registry.")
        return payload
    if payload.get("action") != action or not isinstance(payload.get("ok"), bool):
        raise AgentReachProtocolError("Agent-Reach returned an unsupported management result.")
    return payload

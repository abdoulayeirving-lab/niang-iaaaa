from __future__ import annotations

import re
from typing import Any

from agent.secrets import redact_if_sensitive


_INLINE_SECRET = re.compile(
    r"(?i)\b(api[_ -]?key|token|secret|password|passwd|authorization)\b"
    r"(\s*[:=]\s*)([\"']?)([^\s,;\"']{6,})"
)


def redact_text(value: Any) -> str:
    text = str(value or "")
    text = _INLINE_SECRET.sub(r"\1\2***", text)
    return redact_if_sensitive(text, "[content redacted because it may contain a secret]")


def public_event(event: dict[str, Any]) -> dict[str, str]:
    event_type = str(event.get("type", "event"))[:80]
    tool = str(event.get("toolName") or event.get("tool") or "")[:80]
    message = redact_text(event.get("text") or event.get("message") or "")
    return {"type": event_type, "tool": tool, "message": message[:4000]}

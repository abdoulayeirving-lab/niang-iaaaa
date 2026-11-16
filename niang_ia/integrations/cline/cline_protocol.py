from __future__ import annotations

import json
from typing import Any


class ClineProtocolError(ValueError):
    pass


MAX_PROTOCOL_LINE_BYTES = 2_000_000


def encode_message(message: dict[str, Any]) -> bytes:
    try:
        encoded = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ClineProtocolError("The Cline message could not be encoded.") from exc
    if len(encoded) > MAX_PROTOCOL_LINE_BYTES:
        raise ClineProtocolError("The Cline protocol message exceeds its size limit.")
    return encoded


def decode_message(line: str | bytes) -> dict[str, Any]:
    raw = line.encode("utf-8") if isinstance(line, str) else line
    if len(raw) > MAX_PROTOCOL_LINE_BYTES:
        raise ClineProtocolError("The Cline protocol message exceeds its size limit.")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClineProtocolError("Cline emitted an invalid NDJSON message.") from exc
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise ClineProtocolError("Cline protocol messages require a string type.")
    return value

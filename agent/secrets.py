"""Conservative local heuristics for obvious secrets in mission text."""

from __future__ import annotations

import math
import re
from collections import Counter


_ASSIGNED_SECRET = re.compile(
    r"(?i)\b(api[_ -]?key|password|passwd|secret|access[_ -]?token|"
    r"auth[_ -]?token|client[_ -]?secret|bearer)\b\s*[:=]\s*"
    r"([\"']?)([^\s,;\"']{6,})"
)
_KNOWN_TOKEN = re.compile(
    r"\b(?:AIza[0-9A-Za-z_-]{30,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|"
    r"sk-[A-Za-z0-9_-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})\b"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")


def _shannon_entropy(value: str) -> float:
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def detect_sensitive_data(text: str) -> tuple[str, ...]:
    """Return categories only; never return a matched secret value."""
    if not isinstance(text, str) or not text:
        return ()

    categories = set()
    if _ASSIGNED_SECRET.search(text):
        categories.add("credential_assignment")
    if _KNOWN_TOKEN.search(text):
        categories.add("recognized_token")
    if _PRIVATE_KEY.search(text):
        categories.add("private_key")
    if re.search(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{20,}", text):
        categories.add("bearer_token")

    for candidate in re.findall(r"(?<![A-Za-z0-9])[A-Za-z0-9_+/-]{32,}(?![A-Za-z0-9])", text):
        if len(set(candidate)) >= 10 and _shannon_entropy(candidate) >= 4.0:
            categories.add("high_entropy_token_like_string")
            break
    return tuple(sorted(categories))


def redact_if_sensitive(text: str, replacement: str) -> str:
    if detect_sensitive_data(text):
        return replacement
    return text

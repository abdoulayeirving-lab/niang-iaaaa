"""Privacy guards for the vision pipeline.

Rules enforced here:

* Password / secret fields are never reported (name and content).
* Text that looks like a credential assignment is redacted before it leaves
  the vision engine.
* Privacy mode stops every capture, so nothing is observed at all.
* Screenshots are never written to disk by the engine.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

REDACTED = "[REDACTED]"

# Labels that identify a secret-bearing control.
SENSITIVE_LABEL_PATTERNS: tuple[str, ...] = (
    r"password",
    r"passwd",
    r"pass\s*word",
    r"pass\s*code",
    r"passphrase",
    r"\bpin\b",
    r"\bsecret\b",
    r"api[\s_-]*key",
    r"access[\s_-]*token",
    r"refresh[\s_-]*token",
    r"auth[\s_-]*token",
    r"bearer[\s_-]*token",
    r"private[\s_-]*key",
    r"client[\s_-]*secret",
    r"credential",
    r"\botp\b",
    r"one[\s-]?time[\s-]?(?:code|password)",
    r"security[\s_-]*(?:code|answer|question)",
    r"\bcvv2?\b",
    r"card[\s_-]*number",
    r"\biban\b",
    r"social[\s_-]*security",
    r"\bssn\b",
    r"recovery[\s_-]*(?:code|phrase)",
)

_SENSITIVE_LABEL_RE = re.compile("|".join(SENSITIVE_LABEL_PATTERNS), re.IGNORECASE)

# Text that exposes a credential directly on screen.
_SENSITIVE_TEXT_RE = re.compile(
    r"(?P<full>"
    r"\b(?:password|passwd|passphrase|secret|api[_\- ]?key|token)\b\s*[:=]\s*\S+"
    r"|\bbearer\s+[A-Za-z0-9._\-]{12,}"
    r"|\bsk-[A-Za-z0-9\-_]{12,}"
    r"|\bAKIA[0-9A-Z]{12,}"
    r"|\bghp_[A-Za-z0-9]{20,}"
    r"|\bxox[baprs]-[A-Za-z0-9\-]{10,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r")",
    re.IGNORECASE,
)


class PrivacyGuard:
    """Applies the redaction rules to observations leaving the engine."""

    def __init__(self, enabled: bool = False, redact_passwords: bool = True) -> None:
        self.enabled = bool(enabled)
        self.redact_passwords = bool(redact_passwords)

    # ── Labels ──────────────────────────────────────────────────────────────
    def is_sensitive_label(self, text: Any) -> bool:
        if not text:
            return False
        return bool(_SENSITIVE_LABEL_RE.search(str(text)))

    # ── Free text ───────────────────────────────────────────────────────────
    def redact_text(self, text: Any) -> str:
        """Replace credential-looking assignments with a placeholder."""
        if not text:
            return ""
        value = str(text)
        if not self.redact_passwords:
            return value
        return _SENSITIVE_TEXT_RE.sub(REDACTED, value)

    def contains_sensitive_text(self, text: Any) -> bool:
        if not text:
            return False
        return bool(_SENSITIVE_TEXT_RE.search(str(text)))

    # ── UI elements ─────────────────────────────────────────────────────────
    def filter_elements(self, elements: Iterable[dict]) -> list[dict]:
        """Redact the accessible name of secret-bearing controls."""
        result: list[dict] = []
        for element in elements or []:
            item = dict(element)
            if self.redact_passwords and self.is_sensitive_label(item.get("name")):
                item["name"] = REDACTED
                item["sensitive"] = True
            else:
                item.setdefault("sensitive", False)
            result.append(item)
        return result

    # ── OCR output ──────────────────────────────────────────────────────────
    def sensitive_regions(self, elements: Iterable[dict]) -> list[tuple[int, int, int, int]]:
        """Bounding boxes of secret-bearing controls, in screen coordinates.

        The ``sensitive`` marker set by :meth:`filter_elements` is honoured,
        so the regions are still known once the accessible names have been
        redacted.
        """
        regions: list[tuple[int, int, int, int]] = []
        for element in elements or []:
            name = str(element.get("name") or "")
            marked = bool(element.get("sensitive"))
            if not (marked or (self.redact_passwords and self.is_sensitive_label(name))):
                continue
            bounds = element.get("bounds") or {}
            try:
                left = int(bounds.get("left", 0))
                top = int(bounds.get("top", 0))
                width = int(bounds.get("width", 0))
                height = int(bounds.get("height", 0))
            except (TypeError, ValueError):
                continue
            if width > 0 and height > 0:
                regions.append((left, top, width, height))
        return regions

    def redact_ocr(
        self,
        items: Iterable[dict],
        elements: Iterable[dict] | None = None,
    ) -> list[dict]:
        """Drop OCR words that sit inside a password field, redact the rest."""
        regions = self.sensitive_regions(elements or [])
        result: list[dict] = []
        for item in items or []:
            candidate = dict(item)
            text = str(candidate.get("text") or "")
            bounds = candidate.get("bounds") or {}
            try:
                left = int(bounds.get("left", 0))
                top = int(bounds.get("top", 0))
                width = int(bounds.get("width", 0))
                height = int(bounds.get("height", 0))
            except (TypeError, ValueError):
                left = top = width = height = 0
            if regions and _intersects(
                (left, top, width, height), regions
            ):
                # The word came from a secret field: never report it.
                continue
            if self.redact_passwords:
                candidate["text"] = self.redact_text(text)
            result.append(candidate)
        return result

    # ── Mode ────────────────────────────────────────────────────────────────
    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)


def _intersects(
    box: tuple[int, int, int, int],
    regions: list[tuple[int, int, int, int]],
) -> bool:
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return False
    for rx, ry, rw, rh in regions:
        if x < rx + rw and x + w > rx and y < ry + rh and y + h > ry:
            return True
    return False


__all__ = ["PrivacyGuard", "REDACTED", "SENSITIVE_LABEL_PATTERNS"]

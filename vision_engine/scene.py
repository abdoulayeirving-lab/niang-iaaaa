"""The structured representation of what NIANG IA sees.

`ScreenObservation` is the single object exchanged between the engine, the
visual memory and the decision brain.  It never contains pixels: only
descriptions, positions and text.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# Patterns that indicate a problem visible on screen.
_PROBLEM_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\berror\b", "error"),
    (r"\bexception\b", "exception"),
    (r"\bfailed\b|\bfailure\b", "failure"),
    (r"\bcrash(?:ed)?\b", "crash"),
    (r"\bwarning\b", "warning"),
    (r"\bdenied\b|\baccess is denied\b", "denied"),
    (r"\bunauthori[sz]ed\b|\bunauthorized\b", "unauthorized"),
    (r"\bnot (?:found|installed|available|responding)\b", "missing"),
    (r"\btimed? out\b|\btimeout\b", "timeout"),
    (r"\bimpossible\b|\bunable to\b|\bcannot\b|\bcould not\b", "blocked"),
    (r"\binvalid\b", "invalid"),
    (r"\battention\b", "attention"),
    (r"\bterminated\b|\baborted\b", "terminated"),
    (r"\berreur\b", "erreur"),
    (r"\béchec\b|\béchoué\b", "echec"),
    (r"\baccès refusé\b", "refus"),
    (r"\bintrouvable\b", "introuvable"),
)

_PROBLEM_RE = re.compile(
    "|".join(pattern for pattern, _label in _PROBLEM_PATTERNS), re.IGNORECASE
)


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")


@dataclass(slots=True)
class ScreenObservation:
    """A structured snapshot of the screen at a given moment."""

    timestamp: float = field(default_factory=time.time)
    app_name: str = ""
    window_title: str = ""
    foreground: dict[str, Any] | None = None
    windows: list[dict[str, Any]] = field(default_factory=list)
    elements: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    text_blocks: list[dict[str, Any]] = field(default_factory=list)
    problems: list[dict[str, Any]] = field(default_factory=list)
    monitors: list[dict[str, Any]] = field(default_factory=list)
    change_score: float = 0.0
    changed: bool = False
    deep: bool = False
    state: str = "running"
    privacy_mode: bool = False
    note: str = ""

    # ── Serialisation ───────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "observed_at": _iso(self.timestamp),
            "app_name": self.app_name,
            "window_title": self.window_title,
            "foreground": dict(self.foreground) if self.foreground else None,
            "windows": [dict(item) for item in self.windows],
            "elements": [dict(item) for item in self.elements],
            "text": self.text,
            "text_blocks": [dict(item) for item in self.text_blocks],
            "problems": [dict(item) for item in self.problems],
            "monitors": [dict(item) for item in self.monitors],
            "change_score": round(float(self.change_score), 3),
            "changed": self.changed,
            "deep": self.deep,
            "state": self.state,
            "privacy_mode": self.privacy_mode,
            "note": self.note,
        }

    def summary(self) -> str:
        """One-line human readable description."""
        if self.privacy_mode:
            return "Privacy mode: nothing is being observed."
        app = self.app_name or "unknown application"
        title = self.window_title or "no window title"
        parts = [f"{app} — {title}"]
        if self.elements:
            kinds: dict[str, int] = {}
            for element in self.elements:
                kind = str(element.get("kind", "other"))
                kinds[kind] = kinds.get(kind, 0) + 1
            detail = ", ".join(
                f"{count} {kind}" for kind, count in sorted(kinds.items())
            )
            parts.append(f"{len(self.elements)} elements ({detail})")
        if self.text:
            parts.append(f"{len(self.text)} chars of text")
        if self.problems:
            parts.append(f"{len(self.problems)} problem(s)")
        return " | ".join(parts)

    # ── Derived helpers ─────────────────────────────────────────────────────
    def element_names(self, kind: str | None = None) -> list[str]:
        names: list[str] = []
        for element in self.elements:
            if kind and str(element.get("kind")) != kind:
                continue
            name = str(element.get("name") or "")
            if name:
                names.append(name)
        return names

    def has_text(self, needle: str) -> bool:
        target = str(needle or "").strip().casefold()
        if not target:
            return False
        if target in self.text.casefold():
            return True
        return any(target in str(block.get("text", "")).casefold() for block in self.text_blocks)


def detect_problems(
    window_titles: list[str],
    text: str,
    *,
    max_items: int = 12,
) -> list[dict[str, Any]]:
    """Find error / message markers in window titles and OCR text."""
    problems: list[dict[str, Any]] = []
    seen: set[str] = set()

    for title in window_titles:
        match = _PROBLEM_RE.search(title or "")
        if not match:
            continue
        label = _label_for(match.group(0))
        key = f"title:{label}:{(title or '')[:60]}"
        if key in seen:
            continue
        seen.add(key)
        problems.append(
            {
                "kind": label,
                "source": "window_title",
                "message": (title or "")[:200],
                "severity": "error" if label in {"error", "exception", "failure", "crash", "denied", "unauthorized"} else "warning",
            }
        )

    if text:
        for line in str(text).splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            match = _PROBLEM_RE.search(stripped)
            if not match:
                continue
            label = _label_for(match.group(0))
            key = f"text:{label}:{stripped[:60]}"
            if key in seen:
                continue
            seen.add(key)
            problems.append(
                {
                    "kind": label,
                    "source": "screen_text",
                    "message": stripped[:200],
                    "severity": "error" if label in {"error", "exception", "failure", "crash", "denied", "unauthorized"} else "warning",
                }
            )
            if len(problems) >= max_items:
                break
    return problems[:max_items]


def _label_for(matched: str) -> str:
    value = (matched or "").strip().casefold()
    for pattern, label in _PROBLEM_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE):
            return label
    return "notice"


__all__ = ["ScreenObservation", "detect_problems"]

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ClineMode(str, Enum):
    PLAN = "plan"
    ASSISTED = "assisted"
    AUTONOMOUS_CONTROLLED = "autonomous_controlled"


@dataclass(frozen=True)
class ClineEvent:
    event_type: str
    message: str
    tool: str = ""


@dataclass
class ClineResult:
    status: str
    text: str
    actions: int = 0
    events: list[ClineEvent] = field(default_factory=list)
    verified: bool = False
    quality_gate: dict[str, Any] = field(default_factory=dict)
    selected_skills: list[str] = field(default_factory=list)
    loaded_skills: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return self.text

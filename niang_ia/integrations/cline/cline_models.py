from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


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

    def __str__(self) -> str:
        return self.text

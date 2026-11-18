from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ChannelStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    NEEDS_AUTH = "NEEDS_AUTH"
    NEEDS_CONFIGURATION = "NEEDS_CONFIGURATION"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class ChannelCapability:
    name: str
    status: ChannelStatus
    actions: tuple[str, ...] = ()
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.name,
            "status": self.status.value,
            "actions": list(self.actions),
            "message": self.message,
        }

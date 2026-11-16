"""Compatibility helpers for Cline CLI detection and version reporting."""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from niang_ia.integrations.cline.cline_events import redact_text
from niang_ia.integrations.cline.cline_health import (
    check_cline_health,
    find_cline_binary,
    get_cline_version,
)


class ClineCliNotFoundError(RuntimeError):
    pass


class ClineCliVersionError(RuntimeError):
    pass


class ClineCliAuthError(RuntimeError):
    pass


class ClineExecutionError(RuntimeError):
    pass


def check_cline_available(binary: Path | None = None) -> dict[str, Any]:
    health = check_cline_health()
    if binary is not None:
        health["binary_path"] = str(binary)
    return {
        "available": bool(health["cli_available"]),
        "binary_path": health["binary_path"],
        "version": health["version"],
        "error": None if health["cli_available"] else "Cline CLI binary or version was not found.",
    }


class ClineTask:
    """Compatibility data shape; missions are persisted by NIANG IA's TaskQueue."""

    def __init__(
        self,
        task_id: str,
        goal: str,
        working_dir: str,
        timeout_seconds: int = 180,
        model: str | None = None,
        provider: str | None = None,
        auto_approve: bool = False,
    ):
        self.task_id = task_id or str(uuid.uuid4())[:8]
        self.goal = goal
        self.working_dir = working_dir
        self.timeout_seconds = timeout_seconds
        self.model = model
        self.provider = provider
        self.auto_approve = auto_approve
        self.cancel_flag = threading.Event()
        self.status = "pending"
        self.result = None
        self.error = ""
        self.events: list[dict[str, Any]] = []
        self.start_time: float | None = None
        self.end_time: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "working_dir": self.working_dir,
            "timeout_seconds": self.timeout_seconds,
            "model": self.model,
            "provider": self.provider,
            "auto_approve": self.auto_approve,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "events_count": len(self.events),
            "duration_seconds": (
                self.end_time - self.start_time
                if self.start_time is not None and self.end_time is not None
                else None
            ),
        }


class ClineManager:
    """Legacy facade; raw CLI task execution is disabled in favor of ClineEngine."""

    def __init__(
        self,
        binary: Path | None = None,
        logger: Callable[[str], None] | None = None,
    ):
        self.binary = binary or find_cline_binary()
        self.logger = logger or (lambda _message: None)

    def is_available(self) -> bool:
        return self.binary is not None and self.binary.is_file()

    def start_task(
        self,
        goal: str,
        working_dir: str,
        timeout_seconds: int = 180,
        model: str | None = None,
        provider: str | None = None,
        auto_approve: bool = False,
    ) -> ClineTask:
        raise ClineExecutionError(
            "Direct Cline CLI task execution is disabled. Use ClineEngine so workspace, "
            "action limits, and human approvals are enforced."
        )

    def cancel_task(self, _task_id: str) -> bool:
        return False

    def get_task(self, _task_id: str) -> None:
        return None

    def get_all_tasks(self) -> list[ClineTask]:
        return []


def redact_secrets(text: str) -> str:
    return redact_text(text)

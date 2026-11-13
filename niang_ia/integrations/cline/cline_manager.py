"""Niang IA Cline CLI integration - Manager module.

Manages Cline CLI detection, version checking, task execution, and monitoring.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class ClineCliNotFoundError(RuntimeError):
    """Raised when the Cline CLI binary cannot be located."""


class ClineCliVersionError(RuntimeError):
    """Raised when the Cline CLI version cannot be determined."""


class ClineCliAuthError(RuntimeError):
    """Raised when Cline CLI is not authenticated."""


class ClineExecutionError(RuntimeError):
    """Raised when Cline CLI execution fails."""


def find_cline_binary() -> Optional[Path]:
    """Locate the Cline CLI binary."""
    env_path = os.environ.get("CLINE_BIN_PATH")
    if env_path and Path(env_path).is_file():
        return Path(env_path)

    npm_root = shutil.which("npm")
    if npm_root:
        npm_global = Path(npm_root).parent / "node_modules" / "cline" / "bin" / "cline"
        if npm_global.is_file():
            return npm_global
        npm_global_exe = npm_global.with_suffix(".exe")
        if npm_global_exe.is_file():
            return npm_global_exe

    for start in (Path.cwd(), Path.home()):
        current = start
        for _ in range(10):
            candidate = current / "node_modules" / "cline" / "bin" / "cline"
            if candidate.is_file():
                return candidate
            candidate_exe = candidate.with_suffix(".exe")
            if candidate_exe.is_file():
                return candidate_exe
            parent = current.parent
            if parent == current:
                break
            current = parent

    found = shutil.which("cline")
    if found:
        return Path(found)

    return None



def get_cline_version(binary: Optional[Path] = None) -> Optional[str]:
    """Get the Cline CLI version."""
    if binary is None:
        binary = find_cline_binary()
    if binary is None:
        return None

    try:
        result = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            for line in output.splitlines():
                line = line.strip()
                if line and not line.startswith("Cline"):
                    parts = line.split()
                    for part in parts:
                        if part and part[0].isdigit() and "." in part:
                            return part
            return output.splitlines()[0] if output else None
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def check_cline_available(binary: Optional[Path] = None) -> Dict[str, Any]:
    """Check if Cline CLI is available and functional."""
    if binary is None:
        binary = find_cline_binary()

    if binary is None:
        return {
            "available": False,
            "binary_path": None,
            "version": None,
            "error": "Cline CLI binary not found. Install with: npm install -g cline",
        }

    version = get_cline_version(binary)
    if version is None:
        return {
            "available": False,
            "binary_path": str(binary),
            "version": None,
            "error": "Cline CLI binary found but version could not be determined.",
        }

    return {
        "available": True,
        "binary_path": str(binary),
        "version": version,
        "error": None,
    }


class ClineTask:
    """Represents a single Cline CLI task."""

    def __init__(
        self,
        task_id: str,
        goal: str,
        working_dir: str,
        timeout_seconds: int = 180,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        auto_approve: bool = False,
    ):
        self.task_id = task_id
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
        self.events: List[Dict[str, Any]] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
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
                (self.end_time - self.start_time) if self.start_time and self.end_time else None
            ),
        }


class ClineManager:
    """Manages Cline CLI tasks and execution."""

    def __init__(
        self,
        binary: Optional[Path] = None,
        logger: Optional[Callable[[str], None]] = None,
    ):
        self.binary = binary or find_cline_binary()
        self.logger = logger or (lambda msg: print("[ClineManager] " + msg))
        self._tasks: Dict[str, ClineTask] = {}
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        """Check if Cline CLI is available."""
        return self.binary is not None and self.binary.is_file()

    def start_task(
        self,
        goal: str,
        working_dir: str,
        timeout_seconds: int = 180,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        auto_approve: bool = False,
    ) -> ClineTask:
        """Start a new Cline CLI task."""
        task_id = str(uuid.uuid4())[:8]
        task = ClineTask(
            task_id=task_id,
            goal=goal,
            working_dir=working_dir,
            timeout_seconds=timeout_seconds,
            model=model,
            provider=provider,
            auto_approve=auto_approve,
        )

        with self._lock:
            self._tasks[task_id] = task

        thread = threading.Thread(
            target=self._execute_task,
            args=(task,),
            daemon=True,
        )
        thread.start()

        return task


    def _execute_task(self, task: ClineTask) -> None:
        """Execute a Cline CLI task (runs in background thread)."""
        if not self.is_available():
            task.status = "failed"
            task.error = "Cline CLI binary not available"
            return

        task.status = "running"
        task.start_time = time.time()

        try:
            cmd = [str(self.binary)]
            cmd.extend(["--json", task.goal])
            cmd.extend(["--cwd", task.working_dir])
            cmd.extend(["--timeout", str(task.timeout_seconds)])

            if task.model:
                cmd.extend(["--model", task.model])
            if task.provider:
                cmd.extend(["--provider", task.provider])
            if task.auto_approve:
                cmd.extend(["--auto-approve", "true"])
            else:
                cmd.extend(["--auto-approve", "false"])

            self.logger("Starting Cline task " + task.task_id + ": " + task.goal[:100])

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=task.working_dir,
            )

            stdout_lines = []
            stderr_lines = []

            def read_stdout():
                for line in process.stdout:
                    line = line.strip()
                    if line:
                        stdout_lines.append(line)
                        try:
                            event = json.loads(line)
                            task.events.append(event)
                        except json.JSONDecodeError:
                            task.events.append({"type": "raw", "text": line})

            def read_stderr():
                for line in process.stderr:
                    line = line.strip()
                    if line:
                        stderr_lines.append(line)

            stdout_thread = threading.Thread(target=read_stdout, daemon=True)
            stderr_thread = threading.Thread(target=read_stderr, daemon=True)
            stdout_thread.start()
            stderr_thread.start()

            try:
                process.wait(timeout=task.timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                task.status = "timeout"
                task.error = "Task exceeded " + str(task.timeout_seconds) + "s timeout"
                task.end_time = time.time()
                return

            stdout_thread.join(timeout=5)
            stderr_thread.join(timeout=5)

            task.end_time = time.time()

            if process.returncode == 0:
                task.status = "completed"
                final_text = ""
                for event in reversed(task.events):
                    if event.get("type") == "run_result":
                        final_text = event.get("text", "")
                        break
                if not final_text:
                    for event in reversed(task.events):
                        if "text" in event:
                            final_text = event["text"]
                            break
                task.result = final_text or "\n".join(stdout_lines)
            else:
                task.status = "failed"
                task.error = "Exit code " + str(process.returncode) + ": " + "\n".join(stderr_lines[:10])

        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            task.end_time = time.time()
            self.logger("Task " + task.task_id + " failed: " + str(exc))

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        task = self._tasks.get(task_id)
        if task is None:
            return False
        task.cancel_flag.set()
        task.status = "cancelled"
        return True

    def get_task(self, task_id: str) -> Optional[ClineTask]:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> List[ClineTask]:
        """Get all tasks."""
        with self._lock:
            return list(self._tasks.values())


def redact_secrets(text: str) -> str:
    """Redact potential secrets from text before logging or sending to Cline."""
    import re

    patterns = [
        (r"(api[_-]?key|token|secret|password|passwd)\s*[:=]\s*\S+", r"\1=***"),
        (r"AQ\.[A-Za-z0-9_-]{20,}", "***"),
        (r"sk-[A-Za-z0-9_-]{20,}", "***"),
        (r"ghp_[A-Za-z0-9]{36,}", "***"),
    ]

    result = text
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result

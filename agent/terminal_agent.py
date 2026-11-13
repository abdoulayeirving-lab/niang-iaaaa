"""Workspace-scoped, approval-gated PowerShell/Bash process execution."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
import uuid
import atexit
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from agent.secrets import redact_if_sensitive
from agent.workspace_tools import WorkspaceError, _resolve_workspace_path


MAX_COMMAND_LENGTH = 8_000
MAX_OUTPUT_CHARS = 40_000
MAX_MANAGED_PROCESSES = 16
_DANGEROUS_COMMAND = re.compile(
    r"(?i)(?:\bremove-item\b|\bdel(?:ete)?\b|\brmdir\b|\brd\b|"
    r"\bformat(?:-volume)?\b|\bdiskpart\b|\bbcdedit\b|\breg(?:\.exe)?\b|"
    r"\bset-executionpolicy\b|\binvoke-expression\b|\biex\b|"
    r"\binvoke-webrequest\b|\binvoke-restmethod\b|\bcurl(?:\.exe)?\b|"
    r"\bwget(?:\.exe)?\b|\bshutdown\b|\brestart-computer\b|"
    r"\bstop-computer\b|\btaskkill\b|\bsc(?:\.exe)?\s+delete\b)"
)
_SYSTEM_MUTATION = re.compile(
    r"(?i)(?:\binstall-(?:module|package)\b|\bwinget\s+install\b|"
    r"\bchoco\s+install\b|\bpip\s+install\b|\b(?:npm|pnpm|yarn)\s+install\b|"
    r"\b(?:npm|pnpm|yarn)\s+add\b|\bapt(?:-get)?\s+install\b)"
)


class TerminalAgentError(RuntimeError):
    """A terminal action was invalid, unavailable, or could not be completed."""


@dataclass
class _ManagedProcess:
    process_id: str
    process: subprocess.Popen
    cwd: Path
    shell: str
    command_fingerprint: str
    started_at: float = field(default_factory=time.monotonic)
    stdout: deque[str] = field(default_factory=lambda: deque(maxlen=256))
    stderr: deque[str] = field(default_factory=lambda: deque(maxlen=256))
    output_lock: threading.Lock = field(default_factory=threading.Lock)
    readers: list[threading.Thread] = field(default_factory=list)


def command_risk(command: str) -> str:
    """Classify obvious high-impact command families without implying a sandbox."""
    if _DANGEROUS_COMMAND.search(command):
        return "destructive-or-external"
    if _SYSTEM_MUTATION.search(command):
        return "dependency-or-system-change"
    return "project-code-execution"


def _read_stream(stream: TextIO | None, destination: deque[str], lock: threading.Lock) -> None:
    if stream is None:
        return
    try:
        while True:
            line = stream.readline(4096)
            if not line:
                break
            with lock:
                destination.append(line[-4_000:])
    finally:
        try:
            stream.close()
        except OSError:
            pass


class TerminalAgent:
    """Runs approved commands in the configured workspace and owns launched PIDs."""

    def __init__(self) -> None:
        self._processes: dict[str, _ManagedProcess] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _workspace_directory(relative_path: str) -> Path:
        try:
            target = _resolve_workspace_path(relative_path or ".", must_exist=True)
        except (OSError, WorkspaceError) as exc:
            raise TerminalAgentError(str(exc)) from exc
        if not target.is_dir():
            raise TerminalAgentError("The working directory must be a folder inside the authorized workspace.")
        return target

    @staticmethod
    def _command_argv(shell: str, command: str) -> list[str]:
        shell_name = str(shell or "").strip().lower()
        if not isinstance(command, str) or not command.strip():
            raise TerminalAgentError("A non-empty command is required.")
        if len(command) > MAX_COMMAND_LENGTH or "\x00" in command:
            raise TerminalAgentError(f"Commands must be at most {MAX_COMMAND_LENGTH} characters.")

        if shell_name in {"powershell", "powershell.exe", "pwsh"}:
            candidates = (
                ("powershell.exe", "powershell"),
                ("pwsh.exe", "pwsh"),
            )
            executable = next(
                (shutil.which(name) for name, _ in candidates if shutil.which(name)),
                None,
            )
            if executable is None:
                raise TerminalAgentError("PowerShell is not available on PATH.")
            return [executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command]
        if shell_name == "bash":
            executable = shutil.which("bash")
            if executable is None:
                raise TerminalAgentError("Bash is not available on PATH.")
            return [executable, "--noprofile", "--norc", "-lc", command]
        raise TerminalAgentError("Shell must be 'powershell' or 'bash'.")

    @staticmethod
    def _environment() -> dict[str, str]:
        allowed = {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
            "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME", "COMSPEC",
            "PATHEXT", "PROCESSOR_ARCHITECTURE",
        }
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in allowed
        }
        environment["PYTHONNOUSERSITE"] = "1"
        return environment

    @staticmethod
    def _append_output(record: _ManagedProcess, output: deque[str]) -> str:
        with record.output_lock:
            text = "".join(output)[-MAX_OUTPUT_CHARS:]
        return redact_if_sensitive(text, "[output redacted because it may contain a secret]")

    def _prune_finished(self) -> None:
        with self._lock:
            finished = [
                key for key, record in self._processes.items()
                if record.process.poll() is not None
            ]
            while len(self._processes) >= MAX_MANAGED_PROCESSES and finished:
                self._processes.pop(finished.pop(0), None)
            if len(self._processes) >= MAX_MANAGED_PROCESSES:
                raise TerminalAgentError(
                    f"At most {MAX_MANAGED_PROCESSES} managed process records are retained."
                )

    def _start(
        self,
        shell: str,
        command: str,
        cwd: str = ".",
    ) -> _ManagedProcess:
        argv = self._command_argv(shell, command)
        return self._spawn(argv, shell, cwd, _fingerprint(command))

    def _spawn(
        self,
        argv: list[str],
        shell: str,
        cwd: str,
        command_fingerprint: str,
    ) -> _ManagedProcess:
        working_directory = self._workspace_directory(cwd)
        self._prune_finished()
        kwargs: dict = {
            "cwd": working_directory,
            "env": self._environment(),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(argv, **kwargs)
        except OSError as exc:
            raise TerminalAgentError(f"Could not start the approved command: {exc}") from exc

        record = _ManagedProcess(
            process_id=uuid.uuid4().hex,
            process=process,
            cwd=working_directory,
            shell=shell,
            command_fingerprint=command_fingerprint,
        )
        for stream, output, label in (
            (process.stdout, record.stdout, "stdout"),
            (process.stderr, record.stderr, "stderr"),
        ):
            reader = threading.Thread(
                target=_read_stream,
                args=(stream, output, record.output_lock),
                daemon=True,
                name=f"TerminalOutput-{record.process_id[:8]}-{label}",
            )
            reader.start()
            record.readers.append(reader)
        with self._lock:
            self._processes[record.process_id] = record
        return record

    def start_program(
        self,
        argv: list[str],
        *,
        cwd: str = ".",
        process_identity: str,
        cancel_event: threading.Event | None = None,
    ) -> str:
        if cancel_event is not None and cancel_event.is_set():
            raise TerminalAgentError("Command cancelled before it started.")
        if (
            not isinstance(argv, list)
            or not argv
            or len(argv) > 64
            or any(not isinstance(value, str) or not value or "\x00" in value for value in argv)
            or any(len(value) > MAX_COMMAND_LENGTH for value in argv)
        ):
            raise TerminalAgentError("A direct process requires a valid, bounded argument list.")
        if not isinstance(process_identity, str) or not process_identity:
            raise TerminalAgentError("A stable process identity is required.")
        executable = Path(argv[0])
        if not executable.is_absolute() or not executable.is_file():
            raise TerminalAgentError("The direct process executable must be an existing absolute file path.")
        record = self._spawn(
            argv,
            "direct",
            cwd,
            _fingerprint(process_identity),
        )
        if cancel_event is not None and cancel_event.is_set():
            self._stop_record(record)
            raise TerminalAgentError(
                "Command cancelled during startup; it has been stopped if possible."
            )
        return json.dumps({
            "status": "started" if record.process.poll() is None else "exited",
            "process_id": record.process_id,
            "pid": record.process.pid,
            "cwd": self._relative_cwd(record.cwd),
            "risk_category": "project-code-execution",
        }, ensure_ascii=False)

    def run(
        self,
        shell: str,
        command: str,
        *,
        cwd: str = ".",
        timeout_seconds: int = 120,
        cancel_event: threading.Event | None = None,
    ) -> str:
        timeout = _bounded_timeout(timeout_seconds)
        if cancel_event is not None and cancel_event.is_set():
            raise TerminalAgentError("Command cancelled before it started.")
        record = self._start(shell, command, cwd)
        deadline = time.monotonic() + timeout
        try:
            while record.process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    self._stop_record(record)
                    raise TerminalAgentError(
                        "Command cancelled; it has been stopped if possible. "
                        "Changes already performed may persist."
                    )
                if time.monotonic() >= deadline:
                    self._stop_record(record)
                    raise TerminalAgentError(
                        f"Command exceeded its {timeout}-second timeout; "
                        "its final state is not known."
                    )
                time.sleep(0.05)
            for reader in record.readers:
                reader.join(timeout=1)
            stdout = self._append_output(record, record.stdout)
            stderr = self._append_output(record, record.stderr)
            status = "completed" if record.process.returncode == 0 else "failed"
            return json.dumps({
                "status": status,
                "exit_code": record.process.returncode,
                "risk_category": command_risk(command),
                "stdout": stdout,
                "stderr": stderr,
            }, ensure_ascii=False)
        finally:
            self._remove_if_finished(record)

    def start(
        self,
        shell: str,
        command: str,
        *,
        cwd: str = ".",
        cancel_event: threading.Event | None = None,
    ) -> str:
        if cancel_event is not None and cancel_event.is_set():
            raise TerminalAgentError("Command cancelled before it started.")
        record = self._start(shell, command, cwd)
        if cancel_event is not None and cancel_event.is_set():
            self._stop_record(record)
            raise TerminalAgentError(
                "Command cancelled during startup; it has been stopped if possible."
            )
        return json.dumps({
            "status": "started" if record.process.poll() is None else "exited",
            "process_id": record.process_id,
            "pid": record.process.pid,
            "cwd": self._relative_cwd(record.cwd),
            "risk_category": command_risk(command),
        }, ensure_ascii=False)

    def status(self, process_id: str) -> str:
        record = self._get_record(process_id)
        code = record.process.poll()
        return json.dumps({
            "process_id": record.process_id,
            "pid": record.process.pid,
            "state": "running" if code is None else "exited",
            "exit_code": code,
            "cwd": self._relative_cwd(record.cwd),
            "uptime_seconds": round(time.monotonic() - record.started_at, 2),
        }, ensure_ascii=False)

    def logs(self, process_id: str) -> str:
        record = self._get_record(process_id)
        if record.process.poll() is not None:
            for reader in record.readers:
                reader.join(timeout=1)
        return json.dumps({
            "process_id": record.process_id,
            "state": "running" if record.process.poll() is None else "exited",
            "stdout": self._append_output(record, record.stdout),
            "stderr": self._append_output(record, record.stderr),
        }, ensure_ascii=False)

    def stop(self, process_id: str, grace_seconds: float = 3) -> str:
        record = self._get_record(process_id)
        stopped = self._stop_record(record, grace_seconds=grace_seconds)
        return json.dumps({
            "process_id": record.process_id,
            "state": "stopped" if stopped else "termination_unconfirmed",
            "exit_code": record.process.poll(),
        }, ensure_ascii=False)

    def find_running(self, cwd: str, command_fragment: str = "") -> str | None:
        target = self._workspace_directory(cwd)
        fingerprint = _fingerprint(command_fragment)
        with self._lock:
            for record in self._processes.values():
                if record.process.poll() is not None or record.cwd != target:
                    continue
                if not fingerprint or record.command_fingerprint == fingerprint:
                    return record.process_id
        return None

    def owns_listening_port(self, process_id: str, port: int) -> bool:
        record = self._get_record(process_id)
        if record.process.poll() is not None:
            return False
        try:
            import psutil
        except ImportError:
            return False
        try:
            process = psutil.Process(record.process.pid)
            pids = {record.process.pid}
            pids.update(child.pid for child in process.children(recursive=True))
            return any(
                connection.type == socket.SOCK_STREAM
                and connection.laddr
                and connection.laddr.port == port
                and connection.pid in pids
                and (
                    connection.status == psutil.CONN_LISTEN
                    or (
                        os.name == "nt"
                        and connection.status == psutil.CONN_NONE
                        and self._tcp_port_is_open(port)
                    )
                )
                for connection in psutil.net_connections(kind="inet")
            )
        except (OSError, psutil.Error):
            return False

    @staticmethod
    def _tcp_port_is_open(port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except OSError:
            return False

    def _get_record(self, process_id: str) -> _ManagedProcess:
        with self._lock:
            record = self._processes.get(str(process_id or ""))
        if record is None:
            raise TerminalAgentError("Unknown or expired managed process ID.")
        return record

    def _stop_record(self, record: _ManagedProcess, grace_seconds: float = 3) -> bool:
        if record.process.poll() is not None:
            return True
        grace = max(0.1, min(float(grace_seconds), 10))
        descendants = []
        try:
            import psutil
        except ImportError:
            psutil = None
        if psutil is not None:
            try:
                descendants = psutil.Process(record.process.pid).children(recursive=True)
            except psutil.NoSuchProcess:
                descendants = []
            except (OSError, RuntimeError):
                descendants = []
        try:
            if os.name == "nt":
                record.process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(record.process.pid, signal.SIGTERM)
        except (OSError, ValueError):
            try:
                record.process.terminate()
            except OSError:
                return record.process.poll() is not None
        try:
            record.process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            try:
                if os.name != "nt":
                    os.killpg(record.process.pid, signal.SIGKILL)
                else:
                    record.process.kill()
                record.process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                return False
        for child in reversed(descendants):
            try:
                if child.is_running():
                    child.terminate()
            except (OSError, RuntimeError, psutil.NoSuchProcess):
                continue
        if descendants:
            if psutil is not None:
                try:
                    _, alive = psutil.wait_procs(descendants, timeout=grace)
                    for child in alive:
                        try:
                            child.kill()
                        except (OSError, RuntimeError, psutil.NoSuchProcess):
                            continue
                    if alive:
                        psutil.wait_procs(alive, timeout=2)
                except (OSError, RuntimeError, psutil.NoSuchProcess):
                    pass
        for reader in record.readers:
            reader.join(timeout=0.5)
        return record.process.poll() is not None

    def _remove_if_finished(self, record: _ManagedProcess) -> None:
        if record.process.poll() is not None:
            with self._lock:
                self._processes.pop(record.process_id, None)

    @staticmethod
    def _relative_cwd(path: Path) -> str:
        try:
            from agent.workspace_tools import _workspace_root
            return path.relative_to(_workspace_root()).as_posix() or "."
        except (OSError, ValueError, WorkspaceError):
            return "."

    def close(self) -> None:
        with self._lock:
            records = tuple(self._processes.values())
        for record in records:
            if record.process.poll() is None:
                self._stop_record(record)


def _bounded_timeout(value: int) -> int:
    if type(value) is not int:
        raise TerminalAgentError("timeout_seconds must be an integer.")
    if not 1 <= value <= 1800:
        raise TerminalAgentError("timeout_seconds must be between 1 and 1800.")
    return value


def _fingerprint(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_DEFAULT_TERMINAL_AGENT = TerminalAgent()
atexit.register(_DEFAULT_TERMINAL_AGENT.close)


def terminal_control(
    parameters: dict,
    cancel_event: threading.Event | None = None,
) -> str:
    args = dict(parameters or {})
    action = str(args.get("action", "")).strip().lower()
    if action == "run":
        return _DEFAULT_TERMINAL_AGENT.run(
            str(args.get("shell", "")),
            args.get("command", ""),
            cwd=args.get("cwd", "."),
            timeout_seconds=args.get("timeout_seconds", 120),
            cancel_event=cancel_event,
        )
    if action == "start":
        return _DEFAULT_TERMINAL_AGENT.start(
            str(args.get("shell", "")),
            args.get("command", ""),
            cwd=args.get("cwd", "."),
            cancel_event=cancel_event,
        )
    if action == "status":
        return _DEFAULT_TERMINAL_AGENT.status(args.get("process_id", ""))
    if action == "logs":
        return _DEFAULT_TERMINAL_AGENT.logs(args.get("process_id", ""))
    if action == "stop":
        return _DEFAULT_TERMINAL_AGENT.stop(args.get("process_id", ""))
    raise TerminalAgentError("Unsupported terminal action. Use run, start, status, logs, or stop.")

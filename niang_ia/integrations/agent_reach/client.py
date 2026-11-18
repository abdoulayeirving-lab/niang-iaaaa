"""Bounded subprocess client; it never invokes a shell or management command."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from threading import Event
from typing import Sequence

from agent.secrets import detect_sensitive_data, redact_if_sensitive

from .command_registry import (
    CHANNEL_STATUS_ARGS,
    COMMANDS,
    DOCTOR_ARGS,
    MAX_STDERR_BYTES,
    MAX_STDOUT_BYTES,
    MAX_TIMEOUT_SECONDS,
)


class AgentReachError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class AgentReachClient:
    def __init__(self, executable: str | None = None):
        self._configured_executable = executable

    def find_executable(self) -> str | None:
        configured = (
            self._configured_executable
            or os.environ.get("NIANG_IA_AGENT_REACH_EXECUTABLE", "").strip()
        )
        if configured:
            candidate = Path(configured).expanduser()
            if (
                candidate.name.casefold() not in {"agent-reach.exe", "agent-reach"}
                or not candidate.is_absolute()
                or not candidate.is_file()
            ):
                return None
            return str(candidate)
        candidate = _managed_executable_path()
        if candidate and candidate.is_file():
            return str(candidate)
        found = shutil.which("agent-reach")
        if found and Path(found).suffix.casefold() not in {".cmd", ".bat"}:
            return found
        return None

    def run(
        self,
        args: Sequence[str],
        *,
        timeout: float = MAX_TIMEOUT_SECONDS,
        cancel_event: Event | None = None,
    ) -> str:
        if not _is_allowed_command(args):
            raise AgentReachError("BAD_COMMAND", "The requested Agent-Reach operation is not allowed.")
        if not isinstance(timeout, (int, float)) or not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
            raise AgentReachError("BAD_INPUT", "The Agent-Reach timeout is outside the allowed limit.")
        executable = self.find_executable()
        if not executable:
            raise AgentReachError("UNAVAILABLE", "Agent-Reach CLI is not installed or not configured.")

        managed_executable = _managed_executable_path()
        use_isolated_home = bool(
            managed_executable
            and os.path.normcase(os.path.abspath(executable))
            == os.path.normcase(os.path.abspath(managed_executable))
        )
        env = _safe_environment(isolated_home=use_isolated_home)
        argv = [executable, *args]
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            )
        else:
            kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=str(Path.home()),
                env=env,
                shell=False,
                **kwargs,
            )
        except OSError as exc:
            raise AgentReachError("UNAVAILABLE", f"Could not start Agent-Reach ({type(exc).__name__}).") from exc

        output = {"stdout": bytearray(), "stderr": bytearray()}
        overflow = threading.Event()

        def drain(stream, key: str, maximum: int) -> None:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    return
                remaining = maximum - len(output[key])
                if remaining > 0:
                    output[key].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()

        readers = [
            threading.Thread(target=drain, args=(process.stdout, "stdout", MAX_STDOUT_BYTES), daemon=True),
            threading.Thread(target=drain, args=(process.stderr, "stderr", MAX_STDERR_BYTES), daemon=True),
        ]
        for reader in readers:
            reader.start()
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if cancel_event is not None and cancel_event.is_set():
                    _stop_process_tree(process)
                    raise AgentReachError("CANCELLED", "Agent-Reach request was cancelled.")
                if overflow.is_set():
                    _stop_process_tree(process)
                    raise AgentReachError("OUTPUT_LIMIT", "Agent-Reach exceeded its output size limit.")
                if time.monotonic() >= deadline:
                    _stop_process_tree(process)
                    raise AgentReachError("TIMEOUT", "Agent-Reach exceeded its time limit.")
                time.sleep(0.05)
            for reader in readers:
                reader.join(timeout=1)
            if overflow.is_set():
                raise AgentReachError("OUTPUT_LIMIT", "Agent-Reach exceeded its output size limit.")
        finally:
            if process.poll() is None:
                _stop_process_tree(process)
            if process.stdout:
                process.stdout.close()
            if process.stderr:
                process.stderr.close()
            for reader in readers:
                reader.join(timeout=1)

        stdout = bytes(output["stdout"]).decode("utf-8", errors="replace")
        if process.returncode:
            try:
                envelope = json.loads(stdout)
            except json.JSONDecodeError:
                envelope = None
            if (
                isinstance(envelope, dict)
                and envelope.get("schema_version") == 1
                and envelope.get("ok") is False
                and isinstance(envelope.get("error"), dict)
            ):
                return stdout
            stderr = bytes(output["stderr"]).decode("utf-8", errors="replace")
            stderr = redact_if_sensitive(stderr[:1000], "[redacted: CLI error may contain a secret]")
            raise AgentReachError(
                "CLI_ERROR",
                f"Agent-Reach exited with code {process.returncode}; {stderr}",
            )
        return stdout

    def channels(self) -> str:
        return self.run(CHANNEL_STATUS_ARGS)

    def doctor(self) -> str:
        return self.run(DOCTOR_ARGS)


def _managed_executable_path() -> Path | None:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        return None
    return (
        Path(local_app_data)
        / "NIANG IA"
        / "agent_reach"
        / "uv_tools"
        / "agent-reach"
        / "Scripts"
        / "agent-reach.exe"
    )


def _safe_environment(*, isolated_home: bool = False) -> dict[str, str]:
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
        "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
        "HOME", "LANG", "LC_ALL", "PYTHONUTF8", "PYTHONIOENCODING",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    local_app_data = env.get("LOCALAPPDATA")
    if isolated_home and local_app_data:
        env["HOME"] = str(
            Path(local_app_data) / "NIANG IA" / "agent_reach" / "home"
        )
    env["AGENT_REACH_NO_UPDATE_CHECK"] = "1"
    return env


def _is_allowed_command(args: Sequence[str]) -> bool:
    if not isinstance(args, (list, tuple)) or not args or not all(isinstance(arg, str) for arg in args):
        return False
    if detect_sensitive_data(" ".join(args)):
        return False
    if tuple(args) in {CHANNEL_STATUS_ARGS, DOCTOR_ARGS}:
        return True
    if len(args) < 3 or (args[0], args[1]) not in COMMANDS:
        return False
    spec = COMMANDS[(args[0], args[1])]
    tail = list(args[2:])
    if "--timeout" in tail:
        index = tail.index("--timeout")
        if index != len(tail) - 2 or not _is_valid_timeout(tail[index + 1]):
            return False
        tail = tail[:index]
    backend_args = [index for index, value in enumerate(tail) if value == "--backend"]
    if spec.backend:
        if len(backend_args) != 1:
            return False
        index = backend_args[0]
        if index != len(tail) - 2 or tail[index + 1] != spec.backend:
            return False
        tail = tail[:index]
    elif backend_args or "--backend" in tail:
        return False

    positional_count = 1 if spec.input_name else 0
    if len(tail) < positional_count:
        return False
    if positional_count:
        value = tail.pop(0)
        if (
            not value.strip()
            or value.startswith("-")
            or len(value) > 2048
            or any(ord(char) < 32 for char in value)
        ):
            return False
        if spec.input_kind == "query" and len(value) > 500:
            return False

    seen = set()
    while tail:
        flag = tail.pop(0)
        if not flag.startswith("--") or flag[2:] not in spec.options:
            return False
        name = flag[2:]
        if name in seen or not tail:
            return False
        value = tail.pop(0)
        if not value or value.startswith("--") or any(ord(char) < 32 for char in value):
            return False
        seen.add(name)
        if name == "limit":
            if not value.isdigit() or not 1 <= int(value) <= 5:
                return False
        elif name == "lang":
            if len(value) > 80 or not all(
                part and all(char.isalnum() or char == "-" for char in part)
                for part in value.split(",")
            ):
                return False
        elif name in {"location", "city"} and len(value) > 100:
            return False
    return "limit" not in spec.options or "limit" in seen


def _is_valid_timeout(value: str) -> bool:
    try:
        return 1 <= float(value) <= MAX_TIMEOUT_SECONDS
    except ValueError:
        return False


def _stop_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        try:
            subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
    else:
        try:
            import signal

            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)

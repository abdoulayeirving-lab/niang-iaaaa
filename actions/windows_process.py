"""Bounded subprocess execution for fixed Windows diagnostic commands."""

from __future__ import annotations

import subprocess
import threading
import time


class WindowsProcessCancelled(RuntimeError):
    """The specific child process was terminated after a cancellation request."""


class WindowsProcessTimeout(subprocess.TimeoutExpired):
    """A child process exceeded its deadline, with its termination outcome."""

    def __init__(self, command, timeout, termination_confirmed: bool):
        super().__init__(command, timeout)
        self.termination_confirmed = termination_confirmed


def _decode_output(output: bytes | str | None) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output.replace("\x00", "") if output.count("\x00") > len(output) // 8 else output
    if output.startswith(b"\xff\xfe"):
        return output[2:].decode("utf-16-le", errors="replace")
    if output.startswith(b"\xfe\xff"):
        return output[2:].decode("utf-16-be", errors="replace")
    if output.count(b"\x00") > len(output) // 8:
        return output.decode("utf-16-le", errors="replace").replace("\x00", "")
    for encoding in ("utf-8", "mbcs", "cp1252"):
        try:
            return output.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return output.decode("utf-8", errors="replace")


def _terminate(process: subprocess.Popen) -> bool:
    try:
        process.kill()
    except OSError:
        if process.poll() is not None:
            return True
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
    return process.poll() is not None


def run_windows_process(
    command: list[str],
    timeout_seconds: int,
    cancel_event: threading.Event | None = None,
) -> subprocess.CompletedProcess:
    """Run an explicit argv without a shell, with cancellation and a hard timeout."""
    if cancel_event is not None and cancel_event.is_set():
        raise WindowsProcessCancelled("The command was cancelled before it started.")
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    deadline = time.monotonic() + timeout_seconds
    while process.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            terminated = _terminate(process)
            message = (
                "The targeted process was terminated; any changes already performed may persist."
                if terminated
                else "Cancellation was requested, but process termination could not be confirmed."
            )
            raise WindowsProcessCancelled(
                f"{message} The final system state is unknown."
            )
        if time.monotonic() >= deadline:
            terminated = _terminate(process)
            raise WindowsProcessTimeout(
                command,
                timeout_seconds,
                termination_confirmed=terminated,
            )
        time.sleep(0.1)
    stdout, stderr = process.communicate()
    return subprocess.CompletedProcess(
        command,
        process.returncode,
        _decode_output(stdout),
        _decode_output(stderr),
    )

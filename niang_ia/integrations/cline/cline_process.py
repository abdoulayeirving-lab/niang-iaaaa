from __future__ import annotations

import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from niang_ia.integrations.cline.cline_config import ClineConfig, MAX_MISSION_SECONDS
from niang_ia.integrations.cline.cline_events import public_event, redact_text
from niang_ia.integrations.cline.cline_health import find_agent_sdk_entrypoint
from niang_ia.integrations.cline.cline_models import ClineEvent, ClineMode, ClineResult
from niang_ia.integrations.cline.cline_protocol import ClineProtocolError, decode_message, encode_message


class ClineProcessError(RuntimeError):
    pass


class ClineFreeModelLimitError(ClineProcessError):
    pass


class ClineCancelled(ClineProcessError):
    pass


class ClineProcess:
    def __init__(
        self,
        *,
        node_executable: str | None = None,
        worker_path: Path | None = None,
        sdk_entrypoint: Path | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
    ):
        self.node_executable = node_executable or shutil.which("node.exe") or shutil.which("node")
        self.worker_path = worker_path or Path(__file__).with_name("cline_worker.mjs")
        self.sdk_entrypoint = sdk_entrypoint or find_agent_sdk_entrypoint()
        self._popen = popen

    def run(
        self,
        goal: str,
        config: ClineConfig,
        mode: ClineMode,
        *,
        on_tool_request: Callable[[str, dict], str],
        on_approval_request: Callable[[str, dict], bool],
        selected_skills: Sequence[dict[str, str]] = (),
        on_event: Callable[[ClineEvent], None] | None = None,
        cancel_flag: threading.Event | None = None,
    ) -> ClineResult:
        if not self.node_executable or not self.worker_path.is_file() or not self.sdk_entrypoint:
            raise ClineProcessError("Node.js or the installed Cline Agent SDK is unavailable.")
        if cancel_flag is None:
            cancel_flag = threading.Event()

        env = _safe_child_environment()
        env["NIANG_CLINE_AGENT_ENTRY"] = str(self.sdk_entrypoint)
        process = self._popen(
            [self.node_executable, str(self.worker_path)],
            cwd=str(config.workspace_root),
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            **({"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {}),
        )
        incoming: queue.Queue[tuple[str, str]] = queue.Queue()
        events: list[ClineEvent] = []
        send_lock = threading.Lock()
        pending_approvals: set[str] = set()
        completed: dict[str, Any] = {}
        stderr_output: list[str] = []
        final_result: ClineResult | None = None
        quota_exhausted = False
        deadline = time.monotonic() + min(config.mission_timeout_seconds, MAX_MISSION_SECONDS)
        cancel_sent_at: float | None = None

        def pump(stream: Any, source: str) -> None:
            try:
                for line in stream:
                    incoming.put((source, line))
            finally:
                incoming.put((f"{source}_eof", ""))

        stdout_thread = threading.Thread(target=pump, args=(process.stdout, "stdout"), daemon=True)
        stderr_thread = threading.Thread(target=pump, args=(process.stderr, "stderr"), daemon=True)
        stdout_thread.start()
        stderr_thread.start()

        def send(message: dict) -> None:
            if process.stdin is None:
                raise ClineProcessError("Cline worker input is unavailable.")
            with send_lock:
                process.stdin.write(encode_message(message).decode("utf-8"))
                process.stdin.flush()

        def handle_tool(request: dict) -> None:
            request_id = str(request.get("requestId", ""))
            name = str(request.get("toolName", ""))
            args = request.get("input")
            try:
                if not request_id or not isinstance(args, dict):
                    raise ClineProcessError("Cline sent an invalid tool request.")
                output = on_tool_request(name, args)
                response = {"type": "tool_result", "requestId": request_id, "output": str(output)}
            except Exception as exc:
                response = {
                    "type": "tool_result",
                    "requestId": request_id,
                    "isError": True,
                    "error": redact_text(exc),
                }
            if request_id in completed or cancel_flag.is_set():
                return
            completed[request_id] = True
            try:
                send(response)
            except (OSError, ClineProtocolError, ClineProcessError):
                pass

        def handle_approval(request: dict) -> None:
            request_id = str(request.get("requestId", ""))
            name = str(request.get("toolName", ""))
            args = request.get("input")
            pending_approvals.add(request_id)
            approved = False
            if request_id and isinstance(args, dict) and not cancel_flag.is_set():
                try:
                    approved = bool(on_approval_request(name, args))
                except Exception:
                    approved = False
            if request_id not in pending_approvals:
                return
            pending_approvals.discard(request_id)
            try:
                send({
                    "type": "approval_result",
                    "requestId": request_id,
                    "approved": approved and not cancel_flag.is_set(),
                    "reason": "NIANG IA denied this action." if not approved else "",
                })
            except (OSError, ClineProtocolError, ClineProcessError):
                pass

        try:
            send({
                "type": "start",
                "goal": goal,
                "workspace_root": str(config.workspace_root),
                "mode": mode.value,
                "provider_id": config.provider_id,
                "model_id": config.model_id,
                "base_url": config.base_url if config.provider_id == "ollama" else "",
                "selected_skills": list(selected_skills),
            })
            stdout_eof = False
            while not stdout_eof:
                if cancel_flag.is_set() and cancel_sent_at is None:
                    cancel_sent_at = time.monotonic()
                    for request_id in tuple(pending_approvals):
                        pending_approvals.discard(request_id)
                        send({
                            "type": "approval_result",
                            "requestId": request_id,
                            "approved": False,
                            "reason": "Mission cancelled by the user.",
                        })
                    try:
                        send({"type": "cancel"})
                    except (OSError, ClineProcessError):
                        pass
                if time.monotonic() >= deadline:
                    raise ClineProcessError(
                        f"Cline mission exceeded its {config.mission_timeout_seconds}-second limit."
                    )
                if cancel_sent_at is not None and time.monotonic() - cancel_sent_at > 5:
                    raise ClineCancelled("Cline mission was cancelled.")
                try:
                    source, line = incoming.get(timeout=0.1)
                except queue.Empty:
                    if process.poll() is not None and incoming.empty():
                        break
                    continue
                if source == "stderr":
                    if sum(len(item) for item in stderr_output) < 8_000:
                        stderr_output.append(redact_text(line.strip()))
                    continue
                if source == "stdout_eof":
                    stdout_eof = True
                    continue
                if source != "stdout":
                    continue
                if len(line.encode("utf-8", errors="replace")) > 2_000_000:
                    raise ClineProtocolError("Cline emitted an oversized NDJSON message.")
                message = decode_message(line)
                message_type = message["type"]
                if message_type == "tool_request":
                    threading.Thread(target=handle_tool, args=(message,), daemon=True).start()
                elif message_type == "approval_request":
                    threading.Thread(target=handle_approval, args=(message,), daemon=True).start()
                elif message_type == "agent_event":
                    quota_exhausted = quota_exhausted or message.get("quotaExhausted") is True
                    event_data = public_event({
                        "type": message.get("eventType", "agent_event"),
                        "message": message.get("message", ""),
                    })
                    event = ClineEvent(
                        event_type=event_data["type"],
                        tool=event_data["tool"],
                        message=event_data["message"],
                    )
                    events.append(event)
                    if on_event:
                        on_event(event)
                elif message_type == "run_result":
                    text = redact_text(message.get("outputText", ""))
                    status = str(message.get("status", "failed"))
                    if status != "completed":
                        if cancel_flag.is_set() or status == "aborted":
                            raise ClineCancelled("Cline mission was cancelled.")
                        if quota_exhausted or message.get("quotaExhausted") is True:
                            raise ClineFreeModelLimitError(
                                text or f"The free quota for {config.model_id} is exhausted."
                            )
                        raise ClineProcessError(text or f"Cline run ended with status {status}.")
                    final_result = ClineResult(status="completed", text=text, events=events)
                elif message_type == "fatal":
                    raise ClineProcessError(redact_text(message.get("message", "Cline worker failed.")))
                else:
                    raise ClineProtocolError(f"Unexpected Cline message type: {message_type}.")
            if final_result is not None:
                return final_result
            if cancel_flag.is_set():
                raise ClineCancelled("Cline mission was cancelled.")
            code = process.poll()
            details = "\n".join(stderr_output[-20:])
            suffix = f"\n{details}" if details else ""
            raise ClineProcessError(
                f"Cline worker exited without a result (exit code {code}).{suffix}"
            )
        except (ClineProcessError, ClineProtocolError):
            raise
        except Exception as exc:
            raise ClineProcessError(redact_text(exc)) from exc
        finally:
            try:
                if process.stdin:
                    process.stdin.close()
            except OSError:
                pass
            if process.poll() is None:
                try:
                    if final_result is not None:
                        process.wait(timeout=2)
                    else:
                        process.terminate()
                        process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)


def _safe_child_environment() -> dict[str, str]:
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
        "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
    }
    return {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed
    }

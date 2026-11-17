from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Sequence

from niang_ia.integrations.cline.cline_events import redact_text
from niang_ia.integrations.opencode.opencode_health import find_opencode_binary
from agent.task_routing import is_web_frontend_request
from niang_ia.skills.catalog import ALL_SKILL_IDS, DEFAULT_SKILL_ROOT


MAX_MISSION_SECONDS = 1800
MAX_STDERR_CHARS = 8000
FREE_MODEL_CATALOG_URL = "https://models.dev/api.json"
MAX_FREE_MODEL_CATALOG_BYTES = 10_000_000
FREE_MODEL_CATALOG_TTL_SECONDS = 900
_MODEL_ID_PATTERN = re.compile(r"(?:opencode|opencode-go)/[A-Za-z0-9._:-]+\Z")
_FREE_MODEL_CACHE: tuple[float, frozenset[str]] | None = None
_FREE_MODEL_CACHE_LOCK = threading.Lock()


class OpenCodeProcessError(RuntimeError):
    pass


class OpenCodeCancelled(OpenCodeProcessError):
    pass


class OpenCodeFreeModelLimitError(OpenCodeProcessError):
    pass


class _PendingRequest:
    def __init__(self) -> None:
        self.event = threading.Event()
        self.response: dict[str, Any] | None = None


class OpenCodeProcess:
    def __init__(
        self,
        *,
        binary: Path | None = None,
        free_model_ids: Sequence[str] | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
    ):
        self.binary = binary or find_opencode_binary()
        self._free_model_ids = tuple(free_model_ids) if free_model_ids is not None else None
        self._popen = popen

    def run(
        self,
        goal: str,
        workspace_root: Path,
        mode: str,
        *,
        selected_skill_ids: Sequence[str] = (),
        on_permission: Callable[[dict[str, Any]], bool],
        on_event: Callable[[dict[str, Any]], None] | None = None,
        cancel_flag: threading.Event | None = None,
    ) -> dict[str, Any]:
        if self.binary is None or not self.binary.is_file():
            raise OpenCodeProcessError("OpenCode CLI is unavailable.")
        if cancel_flag is None:
            cancel_flag = threading.Event()
        if any(skill_id not in ALL_SKILL_IDS for skill_id in selected_skill_ids):
            raise OpenCodeProcessError("OpenCode was given an unregistered skill ID.")
        candidates = self._available_free_models(
            workspace_root,
            mode,
            selected_skill_ids,
        )
        if not candidates:
            raise OpenCodeProcessError(
                "No enabled OpenCode model was verified as zero-cost. "
                "Configure an OpenCode free model account; no paid model will be used."
            )

        deadline = time.monotonic() + MAX_MISSION_SECONDS
        for index, model_id in enumerate(candidates):
            remaining = int(deadline - time.monotonic())
            if remaining <= 0:
                raise OpenCodeProcessError(
                    f"OpenCode mission exceeded its {MAX_MISSION_SECONDS}-second limit."
                )
            attempt_goal = goal
            if index:
                attempt_goal += (
                    "\n\nA previous OpenCode free model exhausted its quota. "
                    "Continue from the current workspace state: inspect existing work, "
                    "avoid duplicating completed changes, and request approval before "
                    "overwriting existing files."
                )
            if on_event:
                on_event({
                    "model_routing": {
                        "model_id": model_id,
                        "attempt": index + 1,
                        "total": len(candidates),
                    },
                })
            try:
                return self._run_model(
                    attempt_goal,
                    workspace_root,
                    mode,
                    model_id=model_id,
                    mission_timeout_seconds=remaining,
                    selected_skill_ids=selected_skill_ids,
                    on_permission=on_permission,
                    on_event=on_event,
                    cancel_flag=cancel_flag,
                )
            except OpenCodeFreeModelLimitError as exc:
                if cancel_flag.is_set():
                    raise OpenCodeCancelled("OpenCode mission was cancelled.") from exc
                if index + 1 == len(candidates):
                    raise OpenCodeProcessError(
                        "All enabled zero-cost OpenCode models have exhausted their quotas. "
                        "No paid model was used."
                    ) from exc
        raise OpenCodeProcessError("OpenCode did not return a mission result.")

    def _available_free_models(
        self,
        workspace_root: Path,
        mode: str,
        selected_skill_ids: Sequence[str],
    ) -> list[str]:
        if self._free_model_ids is not None:
            candidates = [
                model_id for model_id in self._free_model_ids
                if isinstance(model_id, str) and _MODEL_ID_PATTERN.fullmatch(model_id)
            ]
        else:
            free_ids = _verified_free_model_ids()
            try:
                result = subprocess.run(
                    [str(self.binary), "models"],
                    cwd=str(workspace_root),
                    env=_safe_child_environment(mode, selected_skill_ids),
                    capture_output=True,
                    text=True,
                    timeout=45,
                    encoding="utf-8",
                    errors="replace",
                    check=False,
                    shell=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise OpenCodeProcessError(
                    "OpenCode's available-model list could not be checked."
                ) from exc
            if result.returncode != 0:
                raise OpenCodeProcessError(
                    "OpenCode could not list models for the configured account."
                )
            available_ids = [
                line.strip() for line in result.stdout.splitlines()
                if _MODEL_ID_PATTERN.fullmatch(line.strip())
            ]
            candidates = [model_id for model_id in available_ids if model_id in free_ids]

        preferred = (
            "opencode/nemotron-3.5-super-vl-free",
            "opencode/nemotron-3.5-lightning-free",
        )
        candidate_set = set(candidates)
        return [
            model_id for model_id in preferred if model_id in candidate_set
        ] + [
            model_id for model_id in candidates if model_id not in preferred
        ]

    def _run_model(
        self,
        goal: str,
        workspace_root: Path,
        mode: str,
        *,
        model_id: str,
        mission_timeout_seconds: int = MAX_MISSION_SECONDS,
        selected_skill_ids: Sequence[str] = (),
        on_permission: Callable[[dict[str, Any]], bool],
        on_event: Callable[[dict[str, Any]], None] | None = None,
        cancel_flag: threading.Event | None = None,
    ) -> dict[str, Any]:
        if self.binary is None or not self.binary.is_file():
            raise OpenCodeProcessError("OpenCode CLI is unavailable.")
        if cancel_flag is None:
            cancel_flag = threading.Event()
        if any(skill_id not in ALL_SKILL_IDS for skill_id in selected_skill_ids):
            raise OpenCodeProcessError("OpenCode was given an unregistered skill ID.")

        process = self._popen(
            [str(self.binary), "--print-logs", "acp"],
            cwd=str(workspace_root),
            env=_safe_child_environment(mode, selected_skill_ids, model_id),
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
        pending: dict[int, _PendingRequest] = {}
        pending_lock = threading.Lock()
        write_lock = threading.Lock()
        stderr_output: list[str] = []
        stderr_size = 0
        next_request_id = 1
        reader_failed: list[str] = []

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

        def send(message: dict[str, Any]) -> None:
            if process.stdin is None:
                raise OpenCodeProcessError("OpenCode ACP input is unavailable.")
            encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
            if len(encoded.encode("utf-8")) > 2_000_000:
                raise OpenCodeProcessError("OpenCode ACP message exceeds the size limit.")
            with write_lock:
                process.stdin.write(encoded + "\n")
                process.stdin.flush()

        def request(method: str, params: dict[str, Any], timeout: float = 30) -> dict[str, Any]:
            nonlocal next_request_id
            with pending_lock:
                request_id = next_request_id
                next_request_id += 1
                waiting = _PendingRequest()
                pending[request_id] = waiting
            send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
            deadline = time.monotonic() + timeout
            while not waiting.event.wait(0.1):
                if reader_failed:
                    raise OpenCodeProcessError(reader_failed[0])
                if cancel_flag.is_set():
                    if method == "session/prompt":
                        threading.Thread(
                            target=_send_cancel,
                            args=(request, params.get("sessionId", "")),
                            daemon=True,
                        ).start()
                    raise OpenCodeCancelled("OpenCode mission was cancelled.")
                if time.monotonic() >= deadline:
                    raise OpenCodeProcessError(f"OpenCode ACP request timed out: {method}.")
            with pending_lock:
                pending.pop(request_id, None)
            response = waiting.response or {}
            if "error" in response:
                error = response["error"]
                message = error.get("message", "OpenCode returned an ACP error.") if isinstance(error, dict) else str(error)
                if method == "session/prompt" and _is_free_model_quota_error(error):
                    raise OpenCodeFreeModelLimitError(
                        f"The zero-cost quota for {model_id} is exhausted: {redact_text(message)}"
                    )
                raise OpenCodeProcessError(redact_text(message))
            result = response.get("result")
            if not isinstance(result, dict):
                raise OpenCodeProcessError(f"OpenCode returned an invalid ACP response for {method}.")
            return result

        def handle_permission(message: dict[str, Any]) -> None:
            request_id = message.get("id")
            params = message.get("params")
            approved = False
            selected_option = None
            if isinstance(params, dict) and not cancel_flag.is_set():
                options = params.get("options", [])
                if isinstance(options, list):
                    selected_option = next(
                        (
                            item.get("optionId")
                            for item in options
                            if isinstance(item, dict)
                            and item.get("kind") == "allow_once"
                            and isinstance(item.get("optionId"), str)
                        ),
                        None,
                    )
                if selected_option:
                    try:
                        approved = bool(on_permission(params))
                    except Exception:
                        approved = False
            if cancel_flag.is_set():
                result = {"outcome": {"outcome": "cancelled"}}
            elif approved and selected_option:
                result = {"outcome": {"outcome": "selected", "optionId": selected_option}}
            else:
                reject = next(
                    (
                        item.get("optionId")
                        for item in params.get("options", [])
                        if isinstance(item, dict) and item.get("kind") == "reject_once"
                    ),
                    None,
                ) if isinstance(params, dict) and isinstance(params.get("options"), list) else None
                result = {
                    "outcome": (
                        {"outcome": "selected", "optionId": reject}
                        if reject
                        else {"outcome": "cancelled"}
                    )
                }
            try:
                send({"jsonrpc": "2.0", "id": request_id, "result": result})
            except (OSError, OpenCodeProcessError):
                pass

        def dispatch(message: dict[str, Any]) -> None:
            if "id" in message and "method" not in message:
                request_id = message.get("id")
                if isinstance(request_id, int):
                    with pending_lock:
                        waiting = pending.get(request_id)
                    if waiting:
                        waiting.response = message
                        waiting.event.set()
                return
            method = message.get("method")
            if method == "session/request_permission":
                threading.Thread(target=handle_permission, args=(message,), daemon=True).start()
                return
            if method == "session/update" and on_event:
                params = message.get("params")
                if isinstance(params, dict):
                    try:
                        on_event(params)
                    except Exception as exc:
                        reader_failed.append(redact_text(exc))
                        cancel_flag.set()
                return
            if method and "id" in message:
                try:
                    send({
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": {"code": -32601, "message": "Method not supported by NIANG IA."},
                    })
                except (OSError, OpenCodeProcessError):
                    pass

        def read_messages() -> None:
            nonlocal stderr_size
            stdout_eof = False
            while not stdout_eof:
                try:
                    source, line = incoming.get(timeout=0.1)
                except queue.Empty:
                    if process.poll() is not None and incoming.empty():
                        break
                    continue
                if source == "stderr":
                    if stderr_size < MAX_STDERR_CHARS:
                        safe_line = redact_text(line.rstrip())
                        stderr_output.append(safe_line[:MAX_STDERR_CHARS - stderr_size])
                        stderr_size += len(safe_line)
                    continue
                if source == "stdout_eof":
                    stdout_eof = True
                    continue
                if source != "stdout":
                    continue
                if len(line.encode("utf-8", errors="replace")) > 2_000_000:
                    reader_failed.append("OpenCode emitted an oversized ACP message.")
                    break
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    reader_failed.append("OpenCode emitted invalid ACP JSON.")
                    break
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    reader_failed.append("OpenCode emitted an invalid ACP envelope.")
                    break
                dispatch(message)
            if not reader_failed and process.poll() is not None:
                stderr_text = "\n".join(stderr_output[-20:])
                reason = "OpenCode ACP process exited unexpectedly."
                reader_failed.append(f"{reason} {stderr_text}".strip())
            with pending_lock:
                outstanding = tuple(pending.values())
            for waiting in outstanding:
                waiting.event.set()

        reader_thread = threading.Thread(target=read_messages, daemon=True)
        reader_thread.start()
        session_id = ""
        try:
            initialized = request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {"auth": {"terminal": False}},
                    "clientInfo": {"name": "NIANG IA", "title": "NIANG IA", "version": "1.0"},
                },
                timeout=60,
            )
            if initialized.get("protocolVersion") != 1:
                raise OpenCodeProcessError("OpenCode ACP protocol version 1 is not supported.")
            session = request(
                "session/new",
                {
                    "cwd": str(workspace_root),
                    "mcpServers": [_workspace_tools_server(workspace_root)],
                },
                timeout=120,
            )
            session_id = session.get("sessionId", "")
            if not isinstance(session_id, str) or not session_id:
                raise OpenCodeProcessError("OpenCode did not create an ACP session.")
            _select_session_model(request, session, session_id, model_id)
            target_mode = "plan" if mode == "plan" else "build"
            _select_session_mode(request, session, session_id, target_mode, mode)

            response = request(
                "session/prompt",
                {
                    "sessionId": session_id,
                    "prompt": [{
                        "type": "text",
                        "text": _skill_prompt(goal, selected_skill_ids),
                    }],
                },
                timeout=min(MAX_MISSION_SECONDS, mission_timeout_seconds),
            )
            return {
                "session_id": session_id,
                "stop_reason": response.get("stopReason", ""),
            }
        finally:
            try:
                if process.stdin:
                    process.stdin.close()
            except OSError:
                pass
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
            reader_thread.join(timeout=1)
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)


def _send_cancel(request: Callable[..., dict[str, Any]], session_id: str) -> None:
    if not session_id:
        return
    try:
        request("session/cancel", {"sessionId": session_id}, timeout=5)
    except (OpenCodeProcessError, OSError):
        pass


def _verified_free_model_ids() -> frozenset[str]:
    global _FREE_MODEL_CACHE
    with _FREE_MODEL_CACHE_LOCK:
        now = time.monotonic()
        if (
            _FREE_MODEL_CACHE is not None
            and now - _FREE_MODEL_CACHE[0] < FREE_MODEL_CATALOG_TTL_SECONDS
        ):
            return _FREE_MODEL_CACHE[1]

        request = urllib.request.Request(
            FREE_MODEL_CATALOG_URL,
            headers={"User-Agent": "NIANG-IA"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read(MAX_FREE_MODEL_CATALOG_BYTES + 1)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise OpenCodeProcessError(
                "OpenCode free-model pricing could not be verified; no model was started."
            ) from exc
        if len(body) > MAX_FREE_MODEL_CATALOG_BYTES:
            raise OpenCodeProcessError("The OpenCode model catalog exceeds its size limit.")
        try:
            catalog = json.loads(body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise OpenCodeProcessError("The OpenCode free-model catalog is invalid.") from exc
        if not isinstance(catalog, dict):
            raise OpenCodeProcessError("The OpenCode free-model catalog is invalid.")

        free_ids: set[str] = set()
        for provider_id in ("opencode", "opencode-go"):
            provider = catalog.get(provider_id)
            models = provider.get("models") if isinstance(provider, dict) else None
            if not isinstance(models, dict):
                continue
            for model_id, model in models.items():
                if not isinstance(model_id, str) or not isinstance(model, dict):
                    continue
                cost = model.get("cost")
                if not isinstance(cost, dict) or model.get("tool_call") is not True:
                    continue
                required = (cost.get("input"), cost.get("output"))
                if any(
                    isinstance(value, bool) or not isinstance(value, (int, float)) or value != 0
                    for value in required
                ):
                    continue
                if any(
                    isinstance(value, bool) or not isinstance(value, (int, float)) or value != 0
                    for value in cost.values()
                ):
                    continue
                full_id = f"{provider_id}/{model_id}"
                if _MODEL_ID_PATTERN.fullmatch(full_id):
                    free_ids.add(full_id)

        _FREE_MODEL_CACHE = (now, frozenset(free_ids))
        return _FREE_MODEL_CACHE[1]


def _is_free_model_quota_error(error: Any) -> bool:
    quota_message = re.compile(
        r"\b429\b|\brate limit\b|\bquota\b.{0,40}\b(?:exhausted|exceeded|limit)\b"
        r"|\b(?:exhausted|exceeded)\b.{0,40}\bquota\b"
        r"|\bfree model\b.{0,40}\b(?:limit|quota)\b",
        re.IGNORECASE,
    )

    def inspect(value: Any) -> bool:
        if isinstance(value, dict):
            for key in ("status", "statusCode", "status_code", "httpStatus", "http_status"):
                status = value.get(key)
                if not isinstance(status, bool) and status == 429:
                    return True
            message = value.get("message")
            if isinstance(message, str) and quota_message.search(message):
                return True
            return any(
                inspect(value.get(key))
                for key in ("data", "error", "details", "cause")
                if key in value
            )
        if isinstance(value, str):
            return bool(quota_message.search(value))
        return False

    return inspect(error)


def _safe_child_environment(
    mode: str,
    selected_skill_ids: Sequence[str] = (),
    model_id: str | None = None,
) -> dict[str, str]:
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
        "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
        "HOMEDRIVE", "HOMEPATH", "XDG_CONFIG_HOME",
    }
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed
    }
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps(
        _managed_config(mode, selected_skill_ids, model_id),
        separators=(",", ":"),
    )
    return env


def _select_session_mode(
    request: Callable[..., dict[str, Any]],
    session: dict[str, Any],
    session_id: str,
    target_mode: str,
    requested_mode: str,
) -> None:
    options = session.get("configOptions")
    mode_option = next(
        (
            option for option in options
            if isinstance(option, dict) and option.get("id") == "mode"
        ),
        None,
    ) if isinstance(options, list) else None
    if mode_option is not None:
        available = _select_option_values(mode_option.get("options", []))
        if target_mode not in available:
            raise OpenCodeProcessError(
                f"OpenCode does not expose the requested {target_mode} mode."
            )
        if mode_option.get("currentValue") != target_mode:
            updated = request(
                "session/set_config_option",
                {
                    "sessionId": session_id,
                    "configId": "mode",
                    "value": target_mode,
                },
                timeout=30,
            )
            updated_options = updated.get("configOptions", [])
            selected = next(
                (
                    option for option in updated_options
                    if isinstance(option, dict) and option.get("id") == "mode"
                ),
                None,
            ) if isinstance(updated_options, list) else None
            if not selected or selected.get("currentValue") != target_mode:
                raise OpenCodeProcessError(
                    f"OpenCode did not switch to the requested {target_mode} mode."
                )
        return

    modes = session.get("modes", {}).get("availableModes", [])
    if isinstance(modes, list) and any(
        isinstance(item, dict) and item.get("id") == target_mode
        for item in modes
    ):
        request(
            "session/set_mode",
            {"sessionId": session_id, "modeId": target_mode},
            timeout=30,
        )
    elif requested_mode == "plan":
        raise OpenCodeProcessError("OpenCode did not expose a read-only plan mode.")


def _select_session_model(
    request: Callable[..., dict[str, Any]],
    session: dict[str, Any],
    session_id: str,
    model_id: str,
) -> None:
    options = session.get("configOptions")
    model_option = next(
        (
            option for option in options
            if isinstance(option, dict) and option.get("id") == "model"
        ),
        None,
    ) if isinstance(options, list) else None
    if model_option is None:
        raise OpenCodeProcessError(
            "OpenCode did not expose model selection; NIANG IA cannot verify a free model."
        )
    if model_id not in _select_option_values(model_option.get("options", [])):
        raise OpenCodeProcessError(
            f"The verified free model is not enabled in OpenCode: {model_id}."
        )
    if model_option.get("currentValue") == model_id:
        return

    updated = request(
        "session/set_config_option",
        {
            "sessionId": session_id,
            "configId": "model",
            "value": model_id,
        },
        timeout=30,
    )
    updated_options = updated.get("configOptions", [])
    selected = next(
        (
            option for option in updated_options
            if isinstance(option, dict) and option.get("id") == "model"
        ),
        None,
    ) if isinstance(updated_options, list) else None
    if not selected or selected.get("currentValue") != model_id:
        raise OpenCodeProcessError(
            f"OpenCode did not switch to the verified free model: {model_id}."
        )


def _select_option_values(options: Any) -> set[str]:
    values: set[str] = set()
    if not isinstance(options, list):
        return values
    for option in options:
        if not isinstance(option, dict):
            continue
        if isinstance(option.get("value"), str):
            values.add(option["value"])
        if isinstance(option.get("options"), list):
            values.update(_select_option_values(option["options"]))
    return values


def _managed_config(
    mode: str,
    selected_skill_ids: Sequence[str] = (),
    model_id: str | None = None,
) -> dict[str, Any]:
    if any(skill_id not in ALL_SKILL_IDS for skill_id in selected_skill_ids):
        raise OpenCodeProcessError("OpenCode was given an unregistered skill ID.")
    if model_id is not None and not _MODEL_ID_PATTERN.fullmatch(model_id):
        raise OpenCodeProcessError("OpenCode was given an invalid free-model ID.")

    def permissions(edit_effect: str, tool_effect: str) -> list[dict[str, str]]:
        return [
            {"action": "*", "resource": "*", "effect": "deny"},
            {"action": "read", "resource": "*", "effect": "allow"},
            {"action": "read", "resource": "*.env", "effect": "deny"},
            {"action": "read", "resource": "*.env.*", "effect": "deny"},
            {"action": "read", "resource": "**/.opencode/**", "effect": "deny"},
            {"action": "read", "resource": "opencode.json", "effect": "deny"},
            {"action": "read", "resource": "opencode.jsonc", "effect": "deny"},
            {"action": "read", "resource": "**/api_keys.json", "effect": "deny"},
            {"action": "read", "resource": "**/credentials.json", "effect": "deny"},
            {"action": "read", "resource": "**/token.json", "effect": "deny"},
            {"action": "read", "resource": "**/client_secret.json", "effect": "deny"},
            {"action": "read", "resource": "**/service_account.json", "effect": "deny"},
            {"action": "read", "resource": "**/.netrc", "effect": "deny"},
            {"action": "read", "resource": "**/.npmrc", "effect": "deny"},
            {"action": "read", "resource": "**/id_rsa", "effect": "deny"},
            {"action": "read", "resource": "**/id_ed25519", "effect": "deny"},
            {"action": "glob", "resource": "*", "effect": "allow"},
            {"action": "grep", "resource": "*", "effect": "allow"},
            {"action": "edit", "resource": "*", "effect": edit_effect},
            {"action": "shell", "resource": "*", "effect": "deny"},
            {"action": "external_directory", "resource": "*", "effect": "deny"},
            {"action": "subagent", "resource": "*", "effect": "deny"},
            {"action": "webfetch", "resource": "*", "effect": "deny"},
            {"action": "websearch", "resource": "*", "effect": "deny"},
            {"action": "skill", "resource": "*", "effect": "deny"},
            *[
                {"action": "skill", "resource": skill_id, "effect": "allow"}
                for skill_id in selected_skill_ids
            ],
            {"action": "question", "resource": "*", "effect": "allow"},
            {"action": "niang_workspace_run_check", "resource": "*", "effect": tool_effect},
            {"action": "niang_workspace_install_dependency", "resource": "*", "effect": tool_effect},
            {"action": "niang_workspace_start_preview", "resource": "*", "effect": tool_effect},
            {"action": "niang_workspace_stop_preview", "resource": "*", "effect": tool_effect},
        ]

    config = {
        "default_agent": "plan" if mode == "plan" else "build",
        "agents": {
            "build": {"permissions": permissions("ask", "ask"), "steps": 80},
            "plan": {"permissions": permissions("deny", "deny"), "steps": 80},
        },
        "skills": [str(DEFAULT_SKILL_ROOT.resolve())],
        "mcp": {"servers": {}},
    }
    if model_id is not None:
        config["model"] = model_id
    return config


def _skill_prompt(goal: str, selected_skill_ids: Sequence[str]) -> str:
    sections = [goal]
    if is_web_frontend_request(goal):
        sections.append(
            "WEB PROJECT DELIVERABLE: Build the actual browser-facing website, "
            "not a Python script that generates a website. Inspect the workspace "
            "and use its existing frontend framework when present. For a new "
            "project without a frontend stack, create real, separate index.html, "
            "styles.css, and app.js files; do not install a framework just for a "
            "landing page. Deliver a polished, responsive page with semantic "
            "sections, working navigation and interactions, accessible controls, "
            "and reduced-motion support. Verify the page files and report their "
            "paths; never claim a website is complete if only a Python file was made."
        )
    if selected_skill_ids:
        available = ", ".join(selected_skill_ids)
        sections.append(
            "NIANG IA has preselected these vetted development skills for this task: "
            f"{available}. Load the relevant skills with the skill tool before "
            "implementing, and always load testing-debugging-mastery. Other skill IDs are unavailable."
        )
    return "\n\n".join(sections)


def _workspace_tools_server(workspace_root: Path) -> dict[str, Any]:
    server_script = Path(__file__).with_name("opencode_tools_server.py").resolve()
    return {
        "name": "niang_workspace",
        "command": sys.executable,
        "args": ["-u", str(server_script), "--workspace", str(workspace_root)],
        "env": {},
    }

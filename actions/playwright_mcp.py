"""Persistent client for Microsoft's Playwright MCP server."""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus


PLAYWRIGHT_MCP_VERSION = "0.0.84"


class PlaywrightMCPUnavailable(RuntimeError):
    """The MCP server could not be started or initialized."""


class PlaywrightMCPError(RuntimeError):
    """The MCP server returned an error or failed during an action."""


class PlaywrightMCPActionUnsupported(PlaywrightMCPError):
    """The installed MCP server does not support a requested action."""


class PlaywrightMCPCancelled(PlaywrightMCPError):
    """The MCP browser action was cancelled and its session was closed."""


_ACTION_TO_TOOL = {
    "go_to": "browser_navigate",
    "search": "browser_navigate",
    "back": "browser_navigate_back",
    "state": "browser_snapshot",
    "inspect": "browser_snapshot",
    "get_text": "browser_snapshot",
    "click": "browser_click",
    "submit_form": "browser_click",
    "download": "browser_click",
    "type": "browser_type",
    "fill_form": "browser_fill_form",
    "select_option": "browser_select_option",
    "press": "browser_press_key",
    "screenshot": "browser_take_screenshot",
    "tabs": "browser_tabs",
    "new_tab": "browser_tabs",
    "close_tab": "browser_tabs",
    "close": "browser_close",
    "wait_for_element": "browser_wait_for",
    "handle_dialog": "browser_handle_dialog",
    "switch_tab": "browser_tabs",
}

_SENSITIVE_LABELS = re.compile(
    r"(password|passcode|secret|api[\s_-]*key|access[\s_-]*token|cookie|"
    r"authorization|credit[\s_-]*card|card[\s_-]*number)",
    re.IGNORECASE,
)
_TRANSIENT_ARTIFACT_NAME = re.compile(
    r"(?:page-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z\.yml|"
    r"console-\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}-\d{3}Z\.log)"
)


def _redact_accessibility_text(value: str) -> str:
    lines = []
    for line in value.splitlines():
        if _SENSITIVE_LABELS.search(line) and ":" in line:
            line = line.split(":", 1)[0] + ": [REDACTED]"
        lines.append(line)
    return "\n".join(lines)


def _saved_screenshot_path(output: str, output_dir: Path) -> Path | None:
    match = re.search(r"\]\(([^)]+)\)", output)
    if not match:
        return None
    filename = match.group(1).replace("\\", "/").rsplit("/", 1)[-1]
    if not filename.startswith("page-") or Path(filename).suffix.lower() not in {
        ".png", ".jpeg", ".jpg", ".webp",
    }:
        return None
    destination = output_dir / filename
    return destination if destination.is_file() else None


def _download_filename(output: str) -> str | None:
    match = re.search(
        r"Downloaded file .+? to [\"']([^\"']+)[\"']",
        output,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r"Downloading file\s+(.+?)(?:\s*\.{3}|[\r\n]|$)",
            output,
            re.IGNORECASE,
        )
    if not match:
        return None
    filename = match.group(1).replace("\\", "/").rsplit("/", 1)[-1]
    if not filename or filename in {".", ".."}:
        return None
    return filename


def _saved_download_path(output: str, output_dir: Path) -> Path | None:
    filename = _download_filename(output)
    if not filename:
        return None
    destination = output_dir / filename
    return destination if destination.is_file() else None


def _cleanup_transient_artifacts(
    output_dir: Path,
    existing_names: set[str],
) -> bool:
    failed = False
    try:
        transient_files = (
            path
            for path in output_dir.iterdir()
            if path.is_file()
            and path.name not in existing_names
            and _TRANSIENT_ARTIFACT_NAME.fullmatch(path.name)
        )
    except OSError:
        return True

    for path in transient_files:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            failed = True
    return failed


class PlaywrightMCPClient:
    """Owns one stdio MCP session and its browser for the process lifetime."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._startup_error: Exception | None = None
        self._session: Any = None
        self._tools: dict[str, Any] = {}
        self._last_snapshot = ""
        self._session_task: asyncio.Task | None = None
        self._session_ready: asyncio.Event | None = None
        self._shutdown_requested: asyncio.Event | None = None
        self._lock = threading.Lock()
        self._network_proxy: Any = None
        self._active_cancel_event: threading.Event | None = None

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._ready.clear()
            self._startup_error = None
            self._thread = threading.Thread(
                target=self._run_loop,
                daemon=True,
                name="PlaywrightMCP",
            )
            self._thread.start()
        if not self._ready.wait(timeout=10):
            raise PlaywrightMCPUnavailable("Playwright MCP event loop did not start.")
        if self._startup_error:
            raise PlaywrightMCPUnavailable(str(self._startup_error)) from self._startup_error

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            self._loop.close()

    def _stop_event_loop(self) -> None:
        loop = self._loop
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if self._thread:
            self._thread.join(timeout=3)
        if not self._thread or not self._thread.is_alive():
            self._loop = None
            self._thread = None

    async def _connect(self) -> None:
        if self._session is not None:
            return
        if self._session_task is None:
            self._session_ready = asyncio.Event()
            self._shutdown_requested = asyncio.Event()
            self._session_task = asyncio.create_task(self._session_loop())
        if self._session_ready is None:
            raise PlaywrightMCPUnavailable("Playwright MCP session could not be initialized.")
        try:
            await asyncio.wait_for(self._session_ready.wait(), timeout=120)
        except asyncio.TimeoutError as exc:
            raise PlaywrightMCPUnavailable(
                "Timed out while starting Microsoft Playwright MCP."
            ) from exc
        if self._startup_error:
            raise PlaywrightMCPUnavailable(str(self._startup_error)) from self._startup_error
        if self._session is None:
            raise PlaywrightMCPUnavailable("Microsoft Playwright MCP disconnected during startup.")

    async def _session_loop(self) -> None:
        try:
            await self._open_session()
        except Exception as exc:
            self._startup_error = exc
            if self._session_ready is not None:
                self._session_ready.set()
            return

    async def _open_session(self) -> None:

        node = shutil.which("node")
        npx = shutil.which("npx")
        if not node or not npx:
            raise PlaywrightMCPUnavailable(
                "Playwright MCP requires Node.js 18+ and npm/npx on PATH. "
                "The existing Python Playwright browser remains available."
            )
        try:
            version_result = await asyncio.to_thread(
                subprocess.run,
                [node, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise PlaywrightMCPUnavailable(f"Could not check the Node.js version: {exc}") from exc
        match = re.match(r"v?(\d+)", version_result.stdout.strip())
        if version_result.returncode or not match or int(match.group(1)) < 18:
            raise PlaywrightMCPUnavailable(
                "Playwright MCP requires Node.js 18 or newer."
            )

        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise PlaywrightMCPUnavailable(
                "The Python MCP client is missing. Install requirements.txt."
            ) from exc

        output_dir = Path.home() / "Downloads" / "NIANG_IA_Agent"
        output_dir.mkdir(parents=True, exist_ok=True)
        from actions.browser_network_proxy import BrowserNetworkProxy
        self._network_proxy = BrowserNetworkProxy()
        args = [
            "--yes",
            f"@playwright/mcp@{PLAYWRIGHT_MCP_VERSION}",
            "--output-dir",
            str(output_dir),
            "--isolated",
            "--block-service-workers",
            "--ignore-roots",
            "--proxy-server",
            self._network_proxy.endpoint,
            "--proxy-bypass",
            '"<-loopback>"',
        ]
        blocked = os.environ.get("NIANG_IA_BROWSER_BLOCKED_ORIGINS", "").strip()
        allowed = os.environ.get("NIANG_IA_BROWSER_ALLOWED_ORIGINS", "").strip()
        if blocked:
            args.extend(["--blocked-origins", blocked])
        if allowed:
            args.extend(["--allowed-origins", allowed])

        try:
            async with stdio_client(
                StdioServerParameters(command=npx, args=args)
            ) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self._session = session
                    self._tools = {tool.name: tool for tool in listed.tools}
                    if self._session_ready is not None:
                        self._session_ready.set()
                    if self._shutdown_requested is not None:
                        await self._shutdown_requested.wait()
                    self._session = None
                    self._tools.clear()
        except Exception as exc:
            raise PlaywrightMCPUnavailable(
                f"Could not initialize Microsoft Playwright MCP: {exc}"
            ) from exc
        finally:
            if self._network_proxy is not None:
                await asyncio.to_thread(self._network_proxy.close)
                self._network_proxy = None

    @staticmethod
    def _tool_arguments(action: str, parameters: dict, schema: dict) -> dict:
        properties = schema.get("properties", {})
        values: dict[str, Any] = {}
        ref = parameters.get("ref")
        element = parameters.get("description")
        target = (
            ref
            or parameters.get("selector")
            or parameters.get("description")
            or parameters.get("text")
        )

        if action in {"go_to", "search"}:
            values["url"] = parameters.get("url", "")
        elif action in {"state", "inspect", "get_text"}:
            pass
        elif action in {"click", "submit_form", "download"}:
            values.update({"element": element, "target": target})
        elif action == "type":
            values.update({
                "element": element,
                "target": ref or parameters.get("selector") or element,
                "text": parameters.get("text", ""),
            })
        elif action == "fill_form":
            fields = parameters.get("fields", [])
            if isinstance(fields, dict):
                fields = [{"name": key, "value": value} for key, value in fields.items()]
            item_schema = properties.get("fields", {}).get("items", {})
            item_properties = item_schema.get("properties", {})
            values["fields"] = [
                {
                    key: value
                    for key, value in {
                        "name": field.get("selector", field.get("name", "")),
                        "element": field.get("selector", field.get("name", "")),
                        "target": field.get("ref", field.get("selector", field.get("name", ""))),
                        "type": field.get("type", "textbox"),
                        "value": (
                            str(field.get("value", "")).lower()
                            if isinstance(field.get("value"), bool)
                            else str(field.get("value", ""))
                        ),
                    }.items()
                    if key in item_properties
                }
                for field in fields
            ]
        elif action == "select_option":
            values.update({
                "element": element,
                "target": target,
                "values": [str(parameters.get("value", ""))],
            })
        elif action == "press":
            values["key"] = parameters.get("key", "Enter")
        elif action == "screenshot":
            values.update({"fullPage": True, "scale": "css"})
        elif action in {"tabs", "new_tab", "close_tab", "switch_tab"}:
            values["action"] = {
                "tabs": "list",
                "new_tab": "new",
                "close_tab": "close",
                "switch_tab": "select",
            }[action]
            if action in {"close_tab", "switch_tab"}:
                index = PlaywrightMCPClient._tab_index(parameters)
                if index is not None:
                    values["index"] = index
        elif action == "wait_for_element":
            values.update({
                "text": parameters.get("selector", ""),
                "time": min(30, max(1, int(parameters.get("timeout_ms", 10000)) / 1000)),
            })
        elif action == "handle_dialog":
            values.update({
                "accept": bool(parameters.get("accept", False)),
                "promptText": parameters.get("prompt_text", ""),
            })

        return {
            key: value for key, value in values.items()
            if key in properties and value is not None
        }

    @staticmethod
    def _tab_index(parameters: dict) -> int | None:
        supplied = parameters.get("index")
        if isinstance(supplied, int) and not isinstance(supplied, bool) and supplied >= 0:
            return supplied
        tab_id = str(parameters.get("tab_id", ""))
        if tab_id.isdigit():
            return int(tab_id)
        suffix = tab_id.rsplit("-", 1)[-1]
        if suffix.isdigit():
            return max(0, int(suffix) - 1)
        return None

    def _field_type(self, target: str) -> str:
        if not target or not self._last_snapshot:
            return "textbox"
        role_pattern = r"^\s*-\s+(textbox|checkbox|radio|combobox|slider)\b"
        match = re.search(
            role_pattern + rf".*\[ref={re.escape(target)}\]",
            self._last_snapshot,
            re.MULTILINE,
        )
        if match:
            return match.group(1)
        for line in self._last_snapshot.splitlines():
            role = re.match(role_pattern, line)
            if role and f'"{target}"' in line:
                return role.group(1)
        return "textbox"

    async def _call_tool(self, action: str, parameters: dict) -> str:
        await self._connect()
        tool_name = _ACTION_TO_TOOL.get(action)
        if action == "forward":
            tool_name = "browser_navigate_forward"
        if tool_name not in self._tools:
            raise PlaywrightMCPActionUnsupported(
                f"Microsoft Playwright MCP does not provide the required "
                f"'{tool_name or action}' tool in version {PLAYWRIGHT_MCP_VERSION}."
            )

        if action in {"go_to", "search", "new_tab"}:
            from actions.browser_security import validate_browser_url
            parameters = dict(parameters)
            if action == "search":
                search_urls = {
                    "google": "https://www.google.com/search?q=",
                    "bing": "https://www.bing.com/search?q=",
                    "duckduckgo": "https://html.duckduckgo.com/html/?q=",
                    "youtube": "https://www.youtube.com/results?search_query=",
                }
                engine = str(parameters.get("engine", "")).lower()
                if not engine:
                    tabs_tool = self._tools.get("browser_tabs")
                    if tabs_tool:
                        tabs = await self._session.call_tool(
                            "browser_tabs",
                            {"action": "list"},
                        )
                        tab_text = "\n".join(
                            item.text for item in tabs.content
                            if getattr(item, "text", None)
                        )
                        active_url = re.search(
                            r"\(current\).*?\((https?://[^)]+)\)",
                            tab_text,
                            re.IGNORECASE,
                        )
                        engine = (
                            "youtube"
                            if active_url and "youtube.com" in active_url.group(1).lower()
                            else "google"
                        )
                    else:
                        engine = "google"
                if engine not in search_urls:
                    raise PlaywrightMCPError(f"Unsupported search engine: {engine}")
                parameters["url"] = search_urls[engine] + quote_plus(
                    str(parameters.get("query", ""))
                )
            parameters["url"] = await asyncio.to_thread(
                validate_browser_url, parameters.get("url", "")
            )

        tool = self._tools[tool_name]
        if action == "new_tab":
            tab_tool = self._tools.get("browser_tabs")
            if tab_tool is None:
                raise PlaywrightMCPActionUnsupported(
                    "Microsoft Playwright MCP does not provide managed tabs."
                )
            await self._session.call_tool(
                "browser_tabs",
                self._tool_arguments("new_tab", parameters, tab_tool.inputSchema),
            )
            action = "go_to"
            tool_name = _ACTION_TO_TOOL[action]
            tool = self._tools[tool_name]

        if action == "forward" and tool_name not in self._tools:
            raise PlaywrightMCPActionUnsupported(
                "This Playwright MCP version does not expose forward navigation."
            )
        if action == "switch_tab":
            tab_index = self._tab_index(parameters)
            if tab_index is None:
                raise PlaywrightMCPActionUnsupported(
                    "Switching tabs requires the index returned by the latest tab listing."
                )
            parameters = dict(parameters)
            parameters["index"] = tab_index
        if action == "fill_form":
            parameters = dict(parameters)
            fields = parameters.get("fields", [])
            if isinstance(fields, dict):
                fields = [
                    {"selector": name, "value": value}
                    for name, value in fields.items()
                ]
            if isinstance(fields, list):
                parameters["fields"] = [
                    {
                        **field,
                        "type": field.get(
                            "type",
                            self._field_type(str(field.get("ref", field.get("selector", "")))),
                        ),
                    }
                    for field in fields
                ]

        arguments = self._tool_arguments(action, parameters, tool.inputSchema)
        required = tool.inputSchema.get("required", [])
        if any(key not in arguments for key in required):
            raise PlaywrightMCPActionUnsupported(
                f"Action '{action}' needs a fresh accessibility snapshot and "
                "the matching element reference before it can run."
            )
        download_started_at = time.time() if action == "download" else None
        output_dir = Path.home() / "Downloads" / "NIANG_IA_Agent"
        existing_artifacts = {
            path.name
            for path in output_dir.iterdir()
            if path.is_file() and _TRANSIENT_ARTIFACT_NAME.fullmatch(path.name)
        } if output_dir.is_dir() else set()
        try:
            result = await self._session.call_tool(tool_name, arguments)
        except Exception as exc:
            raise PlaywrightMCPError(f"Playwright MCP action '{action}' failed: {exc}") from exc
        if result.isError:
            error_text = "\n".join(
                item.text for item in result.content if getattr(item, "text", None)
            )
            raise PlaywrightMCPError(
                f"Playwright MCP action '{action}' failed: {error_text or 'unknown MCP error'}"
            )

        pieces = []
        images = []
        for item in result.content:
            text = getattr(item, "text", None)
            if text:
                pieces.append(_redact_accessibility_text(text))
                continue
            if getattr(item, "type", None) == "image" and getattr(item, "data", None):
                images.append(item)
        output = "\n".join(pieces) or f"Playwright MCP action '{action}' completed."
        if _cleanup_transient_artifacts(output_dir, existing_artifacts):
            output += "\nTemporary browser text artifacts could not all be removed from Downloads."
        if action == "type":
            return "Text entered into the requested browser control; typed value omitted."
        if action == "fill_form":
            fields = parameters.get("fields", [])
            field_count = len(fields) if isinstance(fields, (dict, list)) else 0
            return f"Filled {field_count} browser form field(s); values omitted."
        if action == "download":
            download_filename = _download_filename(output)
            download_path = _saved_download_path(
                output,
                output_dir,
            )
            deadline = time.monotonic() + 10
            while (
                download_filename
                and download_started_at is not None
                and time.monotonic() < deadline
                and (
                    download_path is None
                    or download_path.stat().st_mtime < download_started_at
                )
            ):
                await asyncio.sleep(0.1)
                download_path = _saved_download_path(output, output_dir)
            if (
                download_path is not None
                and download_started_at is not None
                and download_path.stat().st_mtime < download_started_at
            ):
                download_path = None
            if not download_path:
                return "Could not verify that the requested browser download was saved."
            output += f"\nDownload saved: {download_path}"
        if action == "screenshot":
            screenshot_path = _saved_screenshot_path(
                output,
                Path.home() / "Downloads" / "NIANG_IA_Agent",
            )
            if screenshot_path:
                output += f"\nScreenshot saved: {screenshot_path}"
            elif images:
                output += "\n" + self._save_screenshot_image(images[0])
        elif images:
            output += "\n" + self._save_screenshot_image(images[0])
        if action in {"state", "inspect", "get_text"}:
            self._last_snapshot = output
            return "[UNTRUSTED BROWSER ACCESSIBILITY SNAPSHOT]\n" + output
        return output

    @staticmethod
    def _save_screenshot_image(item: Any) -> str:
        output_dir = Path.home() / "Downloads" / "NIANG_IA_Agent"
        output_dir.mkdir(parents=True, exist_ok=True)
        extension = "jpg" if "jpeg" in item.mimeType else "png"
        destination = output_dir / (
            f"browser_{int(time.time())}_{uuid.uuid4().hex[:8]}.{extension}"
        )
        destination.write_bytes(base64.b64decode(item.data))
        return f"Screenshot saved: {destination}"

    def request_cancel(self) -> None:
        event = self._active_cancel_event
        if event is not None:
            event.set()

    def _abort_pending_action(self, future: concurrent.futures.Future) -> None:
        future.cancel()
        if not self._loop or not self._loop.is_running():
            return
        close_future = asyncio.run_coroutine_threadsafe(self._close(), self._loop)
        try:
            close_future.result(timeout=5)
        except concurrent.futures.TimeoutError:
            close_future.cancel()
        except Exception as exc:
            print(f"[Playwright MCP] Session cleanup after cancellation failed: {exc}")
        self._stop_event_loop()

    def call_tool(
        self,
        action: str,
        parameters: dict | None = None,
        cancel_event: threading.Event | None = None,
        timeout_s: float = 90,
    ) -> str:
        self._ensure_thread()
        if self._loop is None:
            raise PlaywrightMCPUnavailable("Playwright MCP event loop is not available.")
        if cancel_event is not None:
            self._active_cancel_event = cancel_event
        future = asyncio.run_coroutine_threadsafe(
            self._call_tool(action, dict(parameters or {})), self._loop
        )
        deadline = time.monotonic() + timeout_s
        try:
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    self._abort_pending_action(future)
                    raise PlaywrightMCPCancelled(
                        "Browser action cancellation requested; the MCP session was closed."
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._abort_pending_action(future)
                    raise PlaywrightMCPError(
                        f"Playwright MCP action '{action}' timed out after {timeout_s:g}s."
                    )
                try:
                    return future.result(timeout=min(0.1, remaining))
                except concurrent.futures.TimeoutError:
                    continue
        except PlaywrightMCPCancelled:
            raise
        except PlaywrightMCPUnavailable:
            raise
        except PlaywrightMCPError:
            raise
        except concurrent.futures.CancelledError as exc:
            raise PlaywrightMCPCancelled(
                "The Playwright MCP browser action was cancelled."
            ) from exc
        except Exception as exc:
            raise PlaywrightMCPError(
                f"Playwright MCP action '{action}' did not complete: {exc}"
            ) from exc
        finally:
            if self._active_cancel_event is cancel_event:
                self._active_cancel_event = None

    def status(self) -> str:
        return (
            f"Microsoft Playwright MCP {PLAYWRIGHT_MCP_VERSION}: "
            f"{'connected' if self._session is not None else 'not started'}"
        )

    async def _close(self) -> None:
        if self._shutdown_requested is not None:
            self._shutdown_requested.set()
        if self._session_task is not None:
            await asyncio.gather(self._session_task, return_exceptions=True)
        self._session_task = None
        self._session_ready = None
        self._shutdown_requested = None
        self._startup_error = None
        self._session = None
        self._tools.clear()

    def close(self) -> None:
        if not self._loop or not self._loop.is_running():
            return
        future = asyncio.run_coroutine_threadsafe(self._close(), self._loop)
        try:
            future.result(timeout=10)
        finally:
            self._stop_event_loop()


_client = PlaywrightMCPClient()
_mission_clients: dict[str, PlaywrightMCPClient] = {}
_mission_client_keys: dict[str, str] = {}
_mission_clients_lock = threading.Lock()


def _client_for_mission(parameters: dict, mission_id: str | None) -> tuple[str | None, PlaywrightMCPClient]:
    if not mission_id:
        return None, _client
    persistent_id = str(parameters.get("persistent_session_id", "")).strip()
    if persistent_id:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", persistent_id):
            raise PlaywrightMCPError(
                "Persistent browser session names must contain 1-48 letters, digits, '_' or '-'."
            )
        key = f"persistent:{persistent_id}"
    else:
        key = f"mission:{mission_id}"
    with _mission_clients_lock:
        client = _mission_clients.get(key)
        if client is None:
            client = PlaywrightMCPClient()
            _mission_clients[key] = client
        _mission_client_keys[mission_id] = key
    return key, client


def playwright_mcp_control(
    action: str,
    parameters: dict | None = None,
    mission_id: str | None = None,
    cancel_event: threading.Event | None = None,
    timeout_s: float = 90,
) -> str:
    if action == "mcp_status":
        return _client.status()
    values = dict(parameters or {})
    key, client = _client_for_mission(values, mission_id)
    try:
        return client.call_tool(
            action,
            values,
            cancel_event=cancel_event,
            timeout_s=timeout_s,
        )
    except PlaywrightMCPCancelled:
        if key and key.startswith("mission:"):
            with _mission_clients_lock:
                _mission_clients.pop(key, None)
                _mission_client_keys.pop(mission_id or "", None)
        raise


def cancel_playwright_mcp_action(mission_id: str) -> None:
    with _mission_clients_lock:
        key = _mission_client_keys.get(mission_id, f"mission:{mission_id}")
        client = _mission_clients.get(key)
    if client is not None:
        client.request_cancel()


def close_playwright_mcp_mission(mission_id: str) -> None:
    with _mission_clients_lock:
        key = _mission_client_keys.pop(mission_id, f"mission:{mission_id}")
        client = _mission_clients.get(key)
        if key.startswith("mission:"):
            client = _mission_clients.pop(key, None)
    if client is not None and key.startswith("mission:"):
        client.close()


def shutdown_playwright_mcp() -> None:
    _client.close()
    with _mission_clients_lock:
        clients = list(_mission_clients.values())
        _mission_clients.clear()
        _mission_client_keys.clear()
    for client in clients:
        client.close()

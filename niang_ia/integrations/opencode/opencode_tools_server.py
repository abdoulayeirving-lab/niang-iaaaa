from __future__ import annotations

import argparse
import asyncio
import mimetypes
import os
import re
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agent import workspace_tools


SERVER_NAME = "niang_workspace"
PREVIEW_TTL_SECONDS = 30 * 60
PREVIEW_MAX_BYTES = 10 * 1024 * 1024
ALLOWED_CHECKS = {
    "python-tests",
    "python-unittest",
    "python-compile",
    "npm-test",
    "npm-build",
    "npm-lint",
    "tsc-check",
    "git-status",
    "git-diff-check",
}
_PREVIEWABLE_SUFFIXES = {
    ".css", ".gif", ".htm", ".html", ".ico", ".jpeg", ".jpg",
    ".js", ".mjs", ".mp3", ".mp4", ".ogg", ".otf", ".png",
    ".svg", ".ttf", ".webm", ".webp", ".woff", ".woff2",
}
_preview_process: subprocess.Popen | None = None


def _validate_arguments(name: str, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ValueError("Tool arguments must be an object.")
    if name == "run_check":
        if set(arguments) - {"check", "timeout_seconds"}:
            raise ValueError("Unknown check arguments.")
        check = arguments.get("check")
        timeout = arguments.get("timeout_seconds", 60)
        if check not in ALLOWED_CHECKS:
            raise ValueError("This project check is not available to OpenCode.")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 180:
            raise ValueError("Check timeout must be between 1 and 180 seconds.")
        return {"check": check, "timeout_seconds": timeout}

    if name == "install_dependency":
        if set(arguments) != {"ecosystem", "package"}:
            raise ValueError("Dependency installation requires only ecosystem and package.")
        ecosystem = arguments.get("ecosystem")
        package = arguments.get("package")
        if ecosystem not in {"node", "python"}:
            raise ValueError("Only Node.js and Python dependencies can be installed.")
        if not isinstance(package, str) or not re.fullmatch(
            r"(?:[A-Za-z0-9][A-Za-z0-9._-]*|@[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)"
            r"(?:@[A-Za-z0-9.*<>=!~^+-]+)?",
            package,
        ):
            raise ValueError("The dependency name or version is invalid.")
        return {"ecosystem": ecosystem, "package": package}

    if name == "start_preview":
        if set(arguments) - {"path"}:
            raise ValueError("Unknown preview arguments.")
        path = arguments.get("path", ".")
        if not isinstance(path, str):
            raise ValueError("Preview path must be relative to the selected workspace.")
        return {"path": path}

    if name == "stop_preview":
        if arguments:
            raise ValueError("Stopping the preview accepts no arguments.")
        return {}

    raise ValueError("This OpenCode tool is not available.")


def execute_workspace_tool(
    name: str,
    arguments: Any,
    workspace_root: str | os.PathLike[str],
    *,
    cancel_flag=None,
) -> str:
    args = _validate_arguments(name, arguments)
    root = workspace_tools._workspace_root(workspace_root)
    if name == "run_check":
        return workspace_tools.run_check(
            args["check"],
            args["timeout_seconds"],
            workspace_root=root,
            cancel_flag=cancel_flag,
        )
    if name == "install_dependency":
        return workspace_tools.install_dependency(
            args["ecosystem"],
            args["package"],
            workspace_root=root,
            cancel_flag=cancel_flag,
        )
    if name == "start_preview":
        return _start_preview(root, args["path"])
    if name == "stop_preview":
        return _stop_preview()
    raise ValueError("This OpenCode tool is not available.")


def _resolve_preview_directory(workspace_root: Path, relative_path: str) -> Path:
    root = workspace_tools._workspace_root(workspace_root)
    directory = workspace_tools._resolve_workspace_path(
        relative_path, must_exist=True, workspace_root=root
    )
    if not directory.is_dir():
        raise workspace_tools.WorkspaceError("The preview path must be a project directory.")
    relative_parts = directory.relative_to(root).parts
    if any(part.startswith(".") or part.lower() in workspace_tools.IGNORED_DIRECTORIES for part in relative_parts):
        raise workspace_tools.WorkspaceError("Hidden and generated directories cannot be previewed.")
    if not any(
        (directory / name).is_file()
        for name in ("index.html", "index.htm")
    ):
        raise workspace_tools.WorkspaceError("The preview directory must contain index.html or index.htm.")
    return directory


def _start_preview(workspace_root: Path, relative_path: str) -> str:
    global _preview_process
    root = workspace_tools._workspace_root(workspace_root)
    directory = _resolve_preview_directory(root, relative_path)

    if _preview_process is not None and _preview_process.poll() is None:
        _stop_preview()

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = [
        sys.executable,
        "-u",
        str(Path(__file__).resolve()),
        "--preview-server",
        "--workspace",
        str(workspace_root),
        "--directory",
        directory.relative_to(workspace_root).as_posix(),
        "--port",
        str(port),
        "--ttl",
        str(PREVIEW_TTL_SECONDS),
    ]
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE",
            "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
            "HOMEDRIVE", "HOMEPATH",
        }
    }
    try:
        process = subprocess.Popen(
            command,
            cwd=str(_PROJECT_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            **(
                {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
                if os.name == "nt"
                else {}
            ),
        )
        ready = process.stdout.readline() if process.stdout else ""
        if process.stdout:
            process.stdout.close()
        if ready.strip() != "ready":
            process.terminate()
            process.wait(timeout=3)
            raise workspace_tools.WorkspaceError("The local project preview could not be started.")
    except (OSError, subprocess.SubprocessError) as exc:
        raise workspace_tools.WorkspaceError("The local project preview could not be started.") from exc

    _preview_process = process
    return (
        f"Static project preview is available at http://127.0.0.1:{port}/ "
        f"for up to {PREVIEW_TTL_SECONDS // 60} minutes. "
        "It serves files only and does not run a project server."
    )


def _stop_preview() -> str:
    global _preview_process
    process = _preview_process
    _preview_process = None
    if process is None or process.poll() is not None:
        return "No project preview is running."
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
    return "The local project preview has been stopped."


def _preview_server(workspace_root: Path, relative_directory: str, port: int, ttl: int) -> None:
    root = workspace_tools._workspace_root(workspace_root)
    directory = _resolve_preview_directory(root, relative_directory)

    class PreviewHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            self._serve(head_only=False)

        def do_HEAD(self):
            self._serve(head_only=True)

        def _serve(self, *, head_only: bool):
            raw_path = unquote(urlsplit(self.path).path)
            if "\x00" in raw_path or "\\" in raw_path:
                self.send_error(404)
                return
            parts = raw_path.lstrip("/").split("/") if raw_path != "/" else []
            if any(part in {"..", "."} or part.startswith(".") for part in parts):
                self.send_error(404)
                return
            if any(part.lower() in workspace_tools.IGNORED_DIRECTORIES for part in parts):
                self.send_error(404)
                return

            relative = "/".join(parts) if parts else "index.html"
            try:
                target = workspace_tools._resolve_workspace_path(
                    (directory / relative).relative_to(root).as_posix(),
                    must_exist=True,
                    workspace_root=root,
                )
                if not target.is_file() or target.suffix.lower() not in _PREVIEWABLE_SUFFIXES:
                    self.send_error(404)
                    return
                size = target.stat().st_size
                if size > PREVIEW_MAX_BYTES:
                    self.send_error(413)
                    return
                content = target.read_bytes()
            except (OSError, ValueError, workspace_tools.WorkspaceError):
                self.send_error(404)
                return

            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self' data: blob:; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
                "font-src 'self' data: https:; connect-src 'self' ws:; "
                "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
            )
            self.end_headers()
            if not head_only:
                self.wfile.write(content)

        def log_message(self, _format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), PreviewHandler)
    server.daemon_threads = True
    print("ready", flush=True)
    timer = threading.Timer(max(1, min(ttl, PREVIEW_TTL_SECONDS)), server.shutdown)
    timer.daemon = True
    timer.start()
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        timer.cancel()
        server.server_close()


async def _serve_mcp(workspace_root: Path) -> None:
    server = Server(SERVER_NAME, version="1.0.0")
    definitions = [
        Tool(
            name="run_check",
            description="Run one allow-listed project build, test, lint, or status check. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "check": {"type": "string", "enum": sorted(ALLOWED_CHECKS)},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 180},
                },
                "required": ["check"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="install_dependency",
            description="Install one Node.js or Python package with restricted install behavior. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ecosystem": {"type": "string", "enum": ["node", "python"]},
                    "package": {"type": "string", "minLength": 1, "maxLength": 200},
                },
                "required": ["ecosystem", "package"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="start_preview",
            description="Start a temporary, static-only preview bound to 127.0.0.1. Requires user approval.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Project directory relative to the workspace."},
                },
                "additionalProperties": False,
            },
        ),
        Tool(
            name="stop_preview",
            description="Stop the temporary static project preview. Requires user approval.",
            inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
    ]

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return definitions

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        return [
            TextContent(
                type="text",
                text=execute_workspace_tool(name, arguments, workspace_root),
            )
        ]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
            raise_exceptions=False,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--preview-server", action="store_true")
    parser.add_argument("--directory", default=".")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--ttl", type=int, default=PREVIEW_TTL_SECONDS)
    args = parser.parse_args()
    if args.preview_server:
        _preview_server(args.workspace, args.directory, args.port, args.ttl)
    else:
        asyncio.run(_serve_mcp(workspace_tools._workspace_root(args.workspace)))


if __name__ == "__main__":
    main()

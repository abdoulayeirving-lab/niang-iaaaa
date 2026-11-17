from __future__ import annotations

import importlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def workspace_mcp_status() -> tuple[bool, str | None]:
    try:
        importlib.import_module("mcp.server")
        importlib.import_module("mcp.server.stdio")
    except ImportError:
        return (
            False,
            "The NIANG IA Python environment is missing the MCP package. "
            "Run START_NIANG_IA.bat to repair the declared dependencies.",
        )
    return True, None


def find_opencode_binary() -> Path | None:
    for name in ("opencode.exe", "opencode"):
        located = shutil.which(name)
        if located:
            path = Path(located)
            if path.is_file() and path.suffix.lower() not in {".cmd", ".ps1", ".bat"}:
                return path.resolve()

    commands = [
        shutil.which("opencode.cmd"),
        shutil.which("opencode.ps1"),
    ]
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    commands.append(str(appdata / "npm" / "opencode.cmd"))
    for command in commands:
        if not command:
            continue
        candidate = Path(command)
        package_binary = (
            candidate.parent / "node_modules" / "@opencode" / "cli" / "bin" / "opencode.exe"
        )
        if package_binary.is_file():
            return package_binary.resolve()
    return None


def get_opencode_version(binary: Path | None = None) -> str | None:
    executable = binary or find_opencode_binary()
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        value = line.strip()
        if value:
            return value[:80]
    return None


def check_opencode_health() -> dict[str, Any]:
    workspace_tools_available, workspace_tools_error = workspace_mcp_status()
    binary = find_opencode_binary()
    version = get_opencode_version(binary)
    free_models: list[str] = []
    free_model_error = None
    if binary is not None and version is not None:
        from niang_ia.integrations.opencode.opencode_process import (
            OpenCodeProcess,
            OpenCodeProcessError,
        )

        try:
            free_models = OpenCodeProcess(binary=binary)._available_free_models(
                Path.cwd(),
                "assisted",
                (),
            )
        except OpenCodeProcessError as exc:
            free_model_error = str(exc)
    return {
        "cli_available": binary is not None,
        "binary_path": str(binary) if binary else None,
        "version": version,
        "acp_available": version is not None,
        "free_models": free_models,
        "free_models_available": bool(free_models),
        "free_model_error": free_model_error,
        "workspace_tools_available": workspace_tools_available,
        "workspace_tools_error": workspace_tools_error,
        "ready": (
            workspace_tools_available
            and binary is not None
            and version is not None
            and bool(free_models)
        ),
        "authentication": "OpenCode user configuration; checked when a mission starts",
    }

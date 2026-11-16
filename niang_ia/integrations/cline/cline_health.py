from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from niang_ia.integrations.cline.cline_config import DEFAULT_BASE_URL


def _cline_package_roots() -> list[Path]:
    candidates = []
    configured = os.environ.get("CLINE_BIN_PATH", "").strip()
    if configured:
        current = Path(configured).expanduser()
        for parent in (current, *current.parents):
            if parent.name.lower() == "cline" and (parent / "package.json").is_file():
                candidates.append(parent)
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    candidates.extend([
        appdata / "npm" / "node_modules" / "cline",
        Path.home() / "AppData" / "Roaming" / "npm" / "node_modules" / "cline",
    ])
    unique = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved not in unique and (resolved / "package.json").is_file():
            unique.append(resolved)
    return unique


def find_cline_binary() -> Path | None:
    configured = os.environ.get("CLINE_BIN_PATH", "").strip()
    if configured and Path(configured).is_file():
        return Path(configured).resolve()
    for name in ("cline.cmd", "cline.exe", "cline"):
        located = shutil.which(name)
        if located:
            path = Path(located)
            if path.suffix.lower() not in {".ps1", ".bat"}:
                return path
    roots = _cline_package_roots()
    return roots[0] / "bin" / "cline" if roots else None


def find_agent_sdk_entrypoint() -> Path | None:
    for root in _cline_package_roots():
        entry = root / "node_modules" / "@cline" / "agents" / "dist" / "index.js"
        if entry.is_file():
            return entry.resolve()
    return None


def get_cline_version(binary: Path | None = None) -> str | None:
    roots = _cline_package_roots()
    if not roots:
        return None
    node = shutil.which("node.exe") or shutil.which("node")
    if not node:
        return None
    script = roots[0] / "bin" / "cline"
    try:
        result = subprocess.run(
            [node, str(script), "--version"],
            capture_output=True,
            text=True,
            timeout=30,
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
        if value and value[0].isdigit():
            return value
    return None


def _probe_ollama(base_url: str = DEFAULT_BASE_URL) -> dict[str, Any]:
    request = urllib.request.Request(f"{base_url.rstrip('/')}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeDecodeError):
        return {"available": False, "models": [], "error": "Local Ollama did not respond."}
    models = payload.get("models", []) if isinstance(payload, dict) else []
    names = [str(item.get("name", "")) for item in models if isinstance(item, dict)]
    return {"available": True, "models": names, "error": None}


def check_cline_health(base_url: str = DEFAULT_BASE_URL) -> dict[str, Any]:
    binary = find_cline_binary()
    sdk = find_agent_sdk_entrypoint()
    version = get_cline_version(binary)
    ollama = _probe_ollama(base_url=base_url)
    return {
        "cli_available": binary is not None and version is not None,
        "binary_path": str(binary) if binary else None,
        "version": version,
        "sdk_available": sdk is not None,
        "sdk_entrypoint": str(sdk) if sdk else None,
        "provider": "ollama",
        "authentication": "not_required_for_local_ollama",
        "model_service": ollama,
        "ready": bool(binary and version and sdk and ollama["available"]),
    }

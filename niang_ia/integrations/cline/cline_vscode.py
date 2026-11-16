from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def find_vscode_executable() -> Path:
    candidates: list[Path] = []
    executable = shutil.which("Code.exe")
    if executable:
        candidates.append(Path(executable))

    cli = shutil.which("code")
    if cli:
        cli_path = Path(cli)
        candidates.append(cli_path.parent.parent / "Code.exe")

    local_app_data = os.environ.get("LOCALAPPDATA")
    program_files = os.environ.get("ProgramFiles")
    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    for root in (local_app_data, program_files, program_files_x86):
        if root:
            candidates.append(Path(root) / "Microsoft VS Code" / "Code.exe")

    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved not in seen and resolved.is_file():
            return resolved
        seen.add(resolved)
    raise FileNotFoundError(
        "Visual Studio Code was not found. Install VS Code or add Code.exe to PATH."
    )


def open_vscode_workspace(workspace_root: str | os.PathLike[str]) -> None:
    root = Path(workspace_root).expanduser()
    is_junction = getattr(root, "is_junction", None)
    if root.is_symlink() or (is_junction is not None and is_junction()):
        raise ValueError("The VS Code workspace cannot be a symbolic link or junction.")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("The VS Code workspace must be an existing directory.")

    executable = find_vscode_executable()
    try:
        subprocess.Popen(
            [str(executable), "--new-window", str(root)],
            cwd=str(root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            shell=False,
        )
    except OSError as exc:
        raise RuntimeError("Visual Studio Code could not be opened for this workspace.") from exc

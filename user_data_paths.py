"""Stable per-user storage paths for installed NIANG IA data."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def user_data_root() -> Path:
    if not _is_frozen():
        return _PROJECT_ROOT
    local_app_data = Path(
        os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
    )
    return local_app_data / "NIANG IA"


def _legacy_root(legacy_root: Path | None = None) -> Path:
    if legacy_root is not None:
        return Path(legacy_root)
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return _PROJECT_ROOT


def _relative_path(relative: str | Path) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("User data paths must be relative to the application data directory.")
    return path


def persistent_path(
    relative: str | Path,
    *,
    legacy_root: Path | None = None,
) -> Path:
    relative_path = _relative_path(relative)
    destination = user_data_root() / relative_path
    if not _is_frozen():
        return destination

    source = _legacy_root(legacy_root) / relative_path
    if source.is_file() and not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return destination


def persistent_directory(
    relative: str | Path,
    *,
    legacy_root: Path | None = None,
) -> Path:
    relative_path = _relative_path(relative)
    destination = user_data_root() / relative_path
    if not _is_frozen():
        return destination

    source_root = _legacy_root(legacy_root) / relative_path
    if source_root.is_dir():
        for source in source_root.rglob("*"):
            if not source.is_file() or source.is_symlink():
                continue
            target = destination / source.relative_to(source_root)
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return destination

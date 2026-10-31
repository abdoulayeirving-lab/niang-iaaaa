"""Create a clean Windows source archive and installer staging directory."""

from __future__ import annotations

import hashlib
import os
import shutil
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
VERSION = (ROOT / "VERSION.txt").read_text(encoding="ascii").strip()
STAGE = DIST / f"NIANG_IA_{VERSION}"
ARCHIVE = DIST / f"NIANG_IA_{VERSION}_windows.zip"
PYTHON_INSTALLER_NAME = "python-3.12.10-amd64.exe"
PYTHON_INSTALLER_URL = f"https://www.python.org/ftp/python/3.12.10/{PYTHON_INSTALLER_NAME}"
PYTHON_INSTALLER_SHA256 = "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb"
BUILD_CACHE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "NIANG_IA_BuildTools"

SOURCE_DIRS = (
    "actions",
    "agent",
    "android",
    "assets",
    "config",
    "core",
    "docs",
    "desktop",
    "memory",
    "models",
    "remote",
    "runtime",
    "tests",
    "vision",
)
ROOT_FILES = (
    ".env.example",
    "LICENSE",
    "readme.md",
    "requirements.txt",
    "setup.py",
    "START_NIANG_IA.bat",
    "install_screen_vision.ps1",
    "start_kaizumi.ps1",
    "start_remote.cmd",
    "api_keys.py",
    "google_oauth.py",
    "logger.py",
    "main.py",
    "safety.py",
    "telegram_bot.py",
    "ui.py",
    "app_update.py",
    "VERSION.txt",
)
EXCLUDED_DIRS = {
    ".git",
    ".gradle",
    ".idea",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "data",
    "dist",
    "logs",
    "out",
    "venv",
}
EXCLUDED_SUFFIXES = {".bak", ".log", ".pyc"}
SECRET_FILENAMES = {
    "api_keys.json",
    "bridge_token.txt",
    "guardian.json",
    "smart_home.json",
    "telegram_offset.txt",
}


def should_include(path: Path, source_root: Path) -> bool:
    relative = path.relative_to(source_root)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return False
    if path.name in SECRET_FILENAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    if path.name.startswith(".env"):
        return False
    if source_root.name == "config":
        return path.name.endswith(".example.json") or path.name == "__init__.py"
    if source_root.name == "memory":
        return path.suffix.lower() in {".py", ".md"}
    return path.is_file()


def collect_files() -> list[Path]:
    files = [ROOT / name for name in ROOT_FILES if (ROOT / name).is_file()]
    for directory in SOURCE_DIRS:
        source = ROOT / directory
        if source.is_dir():
            files.extend(
                path
                for path in source.rglob("*")
                if path.is_file() and should_include(path, source)
            )
    return sorted(set(files), key=lambda path: path.relative_to(ROOT).as_posix().lower())


def ensure_python_installer() -> Path:
    installer = BUILD_CACHE / PYTHON_INSTALLER_NAME
    BUILD_CACHE.mkdir(parents=True, exist_ok=True)

    if installer.is_file():
        digest = hashlib.sha256(installer.read_bytes()).hexdigest()
        if digest == PYTHON_INSTALLER_SHA256:
            return installer
        installer.unlink()

    temporary = installer.with_suffix(installer.suffix + ".download")
    try:
        with urllib.request.urlopen(PYTHON_INSTALLER_URL, timeout=60) as response:
            with temporary.open("wb") as downloaded:
                shutil.copyfileobj(response, downloaded)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        if digest != PYTHON_INSTALLER_SHA256:
            raise RuntimeError(
                f"Python installer SHA-256 mismatch: expected "
                f"{PYTHON_INSTALLER_SHA256}, got {digest}"
            )
        temporary.replace(installer)
    finally:
        temporary.unlink(missing_ok=True)
    return installer


def main() -> None:
    if STAGE.exists() or ARCHIVE.exists():
        raise FileExistsError(
            f"Release output already exists: {STAGE if STAGE.exists() else ARCHIVE}"
        )

    DIST.mkdir(exist_ok=True)
    files = collect_files()
    if not files:
        raise RuntimeError("No release files were found.")

    python_installer = ensure_python_installer()
    for source in files:
        relative = source.relative_to(ROOT)
        destination = STAGE / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    runtime_installer = STAGE / "runtime" / PYTHON_INSTALLER_NAME
    runtime_installer.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(python_installer, runtime_installer)

    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for staged in sorted(STAGE.rglob("*")):
            if staged.is_file():
                bundle.write(staged, Path(STAGE.name) / staged.relative_to(STAGE))

    print(f"Staged {len(files) + 1} files in {STAGE}, including Python 3.12.10")
    print(f"Created {ARCHIVE} ({ARCHIVE.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()

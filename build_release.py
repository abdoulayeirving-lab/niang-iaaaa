"""Create a clean Windows source archive and installer staging directory."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
VERSION = "1.0.0"
STAGE = DIST / f"NIANG_IA_{VERSION}"
ARCHIVE = DIST / f"NIANG_IA_{VERSION}_windows.zip"

SOURCE_DIRS = (
    "actions",
    "agent",
    "android",
    "assets",
    "config",
    "core",
    "docs",
    "memory",
    "models",
    "remote",
    "tests",
    "vision",
)
ROOT_FILES = (
    "LICENSE",
    "readme.md",
    "requirements.txt",
    "setup.py",
    "START_NIANG_IA.bat",
    "start_kaizumi.ps1",
    "start_remote.cmd",
    "api_keys.py",
    "google_oauth.py",
    "logger.py",
    "main.py",
    "safety.py",
    "telegram_bot.py",
    "ui.py",
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


def main() -> None:
    if STAGE.exists() or ARCHIVE.exists():
        raise FileExistsError(
            f"Release output already exists: {STAGE if STAGE.exists() else ARCHIVE}"
        )

    DIST.mkdir(exist_ok=True)
    files = collect_files()
    if not files:
        raise RuntimeError("No release files were found.")

    for source in files:
        relative = source.relative_to(ROOT)
        destination = STAGE / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for staged in sorted(STAGE.rglob("*")):
            if staged.is_file():
                bundle.write(staged, Path(STAGE.name) / staged.relative_to(STAGE))

    print(f"Staged {len(files)} files in {STAGE}")
    print(f"Created {ARCHIVE} ({ARCHIVE.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()

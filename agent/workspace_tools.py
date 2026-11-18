"""Workspace-scoped file operations and a small set of approved checks."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

MAX_TEXT_BYTES = 1_000_000
MAX_SEARCH_RESULTS = 100
MAX_SEARCH_FILES = 2_000
MAX_SEARCH_BYTES = 50_000_000
IGNORED_DIRECTORIES = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules",
    "__pycache__", "dist", "build", ".pytest_cache", ".aws", ".ssh",
    ".gnupg", ".npm", ".cache", ".niang-npm-cache",
}
SENSITIVE_NAMES = {
    "api_keys.json", "credentials.json", "token.json", "bridge_token.txt",
    "client_secret.json", "service_account.json", ".netrc", ".npmrc",
    "id_rsa", "id_ed25519",
}
APPROVED_CHECKS = {
    # Python
    "python-tests": [sys.executable, "-m", "pytest", "-q"],
    "python-unittest": [sys.executable, "-m", "unittest"],
    "python-compile": [sys.executable, "-m", "compileall", "-q", "."],
    # Node.js / JavaScript / TypeScript
    "npm-test": ["npm", "test"],
    "npm-build": ["npm", "run", "build"],
    "npm-lint": ["npm", "run", "lint"],
    "tsc-check": ["npx", "tsc", "--noEmit"],
    # Go
    "go-build": ["go", "build", "./..."],
    "go-test": ["go", "test", "./..."],
    "go-vet": ["go", "vet", "./..."],
    # Rust
    "cargo-check": ["cargo", "check"],
    "cargo-test": ["cargo", "test"],
    "cargo-build": ["cargo", "build"],
    # .NET / C#
    "dotnet-build": ["dotnet", "build"],
    "dotnet-test": ["dotnet", "test"],
    # Java
    "mvn-test": ["mvn", "test"],
    "mvn-compile": ["mvn", "compile"],
    "gradle-test": ["gradle", "test"],
    "gradle-build": ["gradle", "build"],
    # PHP
    "php-lint": ["php", "-l"],
    # Git (language-agnostic)
    "git-status": ["git", "status", "--short"],
    "git-diff-check": ["git", "diff", "--check"],
}


class WorkspaceError(ValueError):
    """Raised when an operation is not allowed in the configured workspace."""


def _is_link_or_junction(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or (is_junction is not None and is_junction())


def _workspace_root(workspace_root: str | os.PathLike[str] | None = None) -> Path:
    if workspace_root is not None:
        candidate = Path(workspace_root).expanduser()
        if _is_link_or_junction(candidate):
            raise WorkspaceError("The selected workspace root must not be a symbolic link or junction.")
        try:
            root = candidate.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceError(f"The selected workspace cannot be opened: {exc}") from exc
        if not root.is_dir():
            raise WorkspaceError("The selected workspace root must be a directory.")
        return root

    configured = os.environ.get("NIANG_IA_WORKSPACE_ROOT", "").strip()
    if not configured:
        # Default workspace: created automatically, still fully confined.
        # Override with NIANG_IA_WORKSPACE_ROOT for a specific project.
        default = Path.home() / "NIANG_IA_Workspace"
        if _is_link_or_junction(default):
            raise WorkspaceError("The default workspace root must not be a symbolic link or junction.")
        try:
            default.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceError(f"Cannot create the default workspace {default}: {exc}") from exc
        return default.resolve()
    try:
        candidate = Path(configured).expanduser()
        if _is_link_or_junction(candidate):
            raise WorkspaceError("NIANG_IA_WORKSPACE_ROOT must not be a symbolic link or junction.")
        root = candidate.resolve(strict=True)
    except OSError as exc:
        raise WorkspaceError(f"Configured workspace cannot be opened: {exc}") from exc
    if not root.is_dir():
        raise WorkspaceError("NIANG_IA_WORKSPACE_ROOT must point to a directory.")
    return root


def _resolve_workspace_path(
    path: str,
    *,
    must_exist: bool = False,
    workspace_root: str | os.PathLike[str] | None = None,
) -> Path:
    root = _workspace_root(workspace_root)
    if not isinstance(path, str) or "\x00" in path:
        raise WorkspaceError("Workspace paths must be strings.")
    relative = Path(path or ".")
    if relative.is_absolute() or any(part == ".." for part in relative.parts):
        raise WorkspaceError("Use a relative path inside the configured workspace.")

    candidate = root / relative
    current = root
    for part in relative.parts:
        if part in {"", "."}:
            continue
        current = current / part
        if _is_link_or_junction(current):
            raise WorkspaceError("Workspace operations do not follow symbolic links or junctions.")
    resolved = candidate.resolve(strict=must_exist)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise WorkspaceError("The requested path is outside the configured workspace.") from exc
    if any(part.lower() in IGNORED_DIRECTORIES for part in resolved.relative_to(root).parts):
        raise WorkspaceError("This generated or version-control directory is not accessible.")
    if any(part.lower() in SENSITIVE_NAMES for part in resolved.parts):
        raise WorkspaceError("Credential and token files are not accessible to workspace tools.")
    if any(part.startswith(".env") for part in resolved.relative_to(root).parts):
        raise WorkspaceError("Environment files are not accessible to workspace tools.")
    if resolved.is_file():
        try:
            if resolved.stat().st_nlink > 1:
                raise WorkspaceError("Files with multiple hard links are not accessible to workspace tools.")
        except OSError as exc:
            raise WorkspaceError("The file's workspace identity could not be verified.") from exc
    return resolved


def list_files(
    path: str = ".",
    max_entries: int = 200,
    *,
    workspace_root: str | os.PathLike[str] | None = None,
) -> str:
    target = _resolve_workspace_path(path, must_exist=True, workspace_root=workspace_root)
    if not target.is_dir():
        raise WorkspaceError("The requested workspace path is not a directory.")
    limit = max(1, min(int(max_entries), 500))
    root = _workspace_root(workspace_root)
    results = []
    for current, directories, filenames in os.walk(target, topdown=True, followlinks=False):
        current_path = Path(current)
        depth = len(current_path.relative_to(target).parts)
        directories[:] = [
            name for name in directories
            if name.lower() not in IGNORED_DIRECTORIES
            and name.lower() not in SENSITIVE_NAMES
            and not name.startswith(".env")
            and not _is_link_or_junction(current_path / name)
            and depth < 3
        ]
        for name in directories + filenames:
            candidate = current_path / name
            if _is_link_or_junction(candidate):
                continue
            relative = candidate.relative_to(root)
            if name.lower() in SENSITIVE_NAMES or name.startswith(".env"):
                continue
            results.append(f"{'DIR ' if candidate.is_dir() else 'FILE'} {relative.as_posix()}")
            if len(results) >= limit:
                break
        if len(results) >= limit:
            break
    return "\n".join(results) if results else "No accessible files found in that workspace folder."


def open_folder(
    path: str = ".",
    *,
    workspace_root: str | os.PathLike[str] | None = None,
) -> str:
    target = _resolve_workspace_path(
        path, must_exist=True, workspace_root=workspace_root
    )
    if not target.is_dir():
        raise WorkspaceError("The requested workspace path is not a directory.")
    if os.name != "nt":
        raise WorkspaceError("Opening folders in Explorer is supported only on Windows.")

    explorer = Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe"
    try:
        subprocess.Popen([str(explorer), str(target)], close_fds=True)
    except OSError as exc:
        raise WorkspaceError(f"Could not open the folder in Windows Explorer: {exc}") from exc
    return f"Opened folder in Windows Explorer: {target}"


def read_file(path: str, *, workspace_root: str | os.PathLike[str] | None = None) -> str:
    target = _resolve_workspace_path(path, must_exist=True, workspace_root=workspace_root)
    if not target.is_file():
        raise WorkspaceError("The requested workspace path is not a file.")
    if target.stat().st_size > MAX_TEXT_BYTES:
        raise WorkspaceError(f"Files larger than {MAX_TEXT_BYTES} bytes cannot be read.")
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceError("The requested file is not valid UTF-8 text.") from exc


def write_file(
    path: str,
    content: str,
    *,
    workspace_root: str | os.PathLike[str] | None = None,
) -> str:
    if not isinstance(content, str):
        raise WorkspaceError("File content must be text.")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_TEXT_BYTES:
        raise WorkspaceError(f"File content exceeds the {MAX_TEXT_BYTES}-byte limit.")
    target = _resolve_workspace_path(path, workspace_root=workspace_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _resolve_workspace_path(path, workspace_root=workspace_root)
    if target.exists() and not target.is_file():
        raise WorkspaceError("The destination exists and is not a regular file.")

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=".niang-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return f"Wrote {len(encoded)} bytes to {target.relative_to(_workspace_root(workspace_root)).as_posix()}."


def edit_file(
    path: str,
    find: str,
    replace: str,
    expected_occurrences: int = 1,
    *,
    workspace_root: str | os.PathLike[str] | None = None,
) -> str:
    if not isinstance(find, str) or not find:
        raise WorkspaceError("The exact text to find must not be empty.")
    if not isinstance(replace, str):
        raise WorkspaceError("Replacement content must be text.")
    try:
        expected = int(expected_occurrences)
    except (TypeError, ValueError) as exc:
        raise WorkspaceError("expected_occurrences must be an integer from 1 to 100.") from exc
    if expected < 1 or expected > 100:
        raise WorkspaceError("expected_occurrences must be an integer from 1 to 100.")
    if len(find.encode("utf-8")) > MAX_TEXT_BYTES or len(replace.encode("utf-8")) > MAX_TEXT_BYTES:
        raise WorkspaceError(f"Search and replacement text must not exceed {MAX_TEXT_BYTES} bytes.")

    target = _resolve_workspace_path(path, must_exist=True, workspace_root=workspace_root)
    if not target.is_file():
        raise WorkspaceError("The requested workspace path is not a file.")
    if target.stat().st_size > MAX_TEXT_BYTES:
        raise WorkspaceError(f"Files larger than {MAX_TEXT_BYTES} bytes cannot be edited.")
    try:
        contents = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceError("The requested file is not valid UTF-8 text.") from exc

    actual = contents.count(find)
    if actual != expected:
        raise WorkspaceError(
            f"Expected {expected} exact occurrence(s) in {path}, but found {actual}; "
            "the file was not changed."
        )
    updated = contents.replace(find, replace)
    encoded = updated.encode("utf-8")
    if len(encoded) > MAX_TEXT_BYTES:
        raise WorkspaceError(f"Edited content exceeds the {MAX_TEXT_BYTES}-byte limit.")

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=".niang-",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(encoded)
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return (
        f"Edited {actual} occurrence(s) in "
        f"{target.relative_to(_workspace_root(workspace_root)).as_posix()}."
    )


def _patch_path(raw_path: str) -> str:
    value = raw_path.split("\t", 1)[0].strip()
    if value.startswith(("a/", "b/")):
        value = value[2:]
    if not value or value == "/dev/null":
        raise WorkspaceError("Patch creation and deletion are not supported; use workspace_write_file for new files.")
    return value


def _parse_unified_patch(patch: str) -> list[tuple[str, list[tuple[int, int, list[str]]]]]:
    if not isinstance(patch, str) or not patch.strip():
        raise WorkspaceError("A non-empty unified diff patch is required.")
    if len(patch.encode("utf-8")) > MAX_TEXT_BYTES:
        raise WorkspaceError(f"Patch exceeds the {MAX_TEXT_BYTES}-byte limit.")

    lines = patch.splitlines(keepends=True)
    parsed = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise WorkspaceError("Each patch file must have matching --- and +++ headers.")
        old_path = _patch_path(lines[index][4:])
        new_path = _patch_path(lines[index + 1][4:])
        if old_path != new_path:
            raise WorkspaceError("Patch renames are not supported; old and new paths must match.")
        index += 2
        hunks = []
        while index < len(lines) and not lines[index].startswith(("--- ", "diff --git ")):
            header = lines[index]
            if not header.startswith("@@ "):
                if header.startswith(("index ", "+++ ")):
                    index += 1
                    continue
                if not header.strip():
                    index += 1
                    continue
                raise WorkspaceError(f"Unexpected unified diff content: {header[:120].rstrip()}")
            match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", header.rstrip("\r\n"))
            if match is None:
                raise WorkspaceError(f"Invalid unified diff hunk header: {header.rstrip()[:120]}")
            old_start = int(match.group(1))
            old_count = int(match.group(2) or 1)
            new_count = int(match.group(4) or 1)
            index += 1
            body = []
            consumed_old = consumed_new = 0
            while index < len(lines) and not lines[index].startswith(("@@ ", "--- ", "diff --git ")):
                line = lines[index]
                if line.startswith("\\ No newline at end of file"):
                    index += 1
                    continue
                if not line or line[0] not in " +-":
                    break
                marker, content = line[0], line[1:]
                body.append(line)
                if marker in " -":
                    consumed_old += 1
                if marker in " +":
                    consumed_new += 1
                index += 1
            if consumed_old != old_count or consumed_new != new_count:
                raise WorkspaceError(
                    f"Patch hunk counts do not match its header for {old_path}."
                )
            hunks.append((old_start, old_count, body))
        if not hunks:
            raise WorkspaceError(f"Patch contains no change hunks for {old_path}.")
        parsed.append((old_path, hunks))

    if not parsed:
        raise WorkspaceError("No unified diff file sections were found.")
    paths = [path for path, _ in parsed]
    if len(paths) != len(set(paths)):
        raise WorkspaceError("A patch must not contain duplicate sections for the same file.")
    return parsed


def _apply_file_hunks(contents: str, hunks: list[tuple[int, int, list[str]]], path: str) -> str:
    source = contents.splitlines(keepends=True)
    output = []
    cursor = 0
    for old_start, old_count, body in hunks:
        hunk_start = old_start - 1 if old_count else old_start
        if hunk_start < cursor or hunk_start > len(source):
            raise WorkspaceError(f"Patch hunk position is invalid for {path}; file was not changed.")
        output.extend(source[cursor:hunk_start])
        cursor = hunk_start
        for line in body:
            marker, content = line[0], line[1:]
            if marker == " ":
                if cursor >= len(source) or source[cursor] != content:
                    raise WorkspaceError(
                        f"Patch context does not match {path}; file was not changed."
                    )
                output.append(source[cursor])
                cursor += 1
            elif marker == "-":
                if cursor >= len(source) or source[cursor] != content:
                    raise WorkspaceError(
                        f"Patch context does not match {path}; file was not changed."
                    )
                cursor += 1
            elif marker == "+":
                output.append(content)
    output.extend(source[cursor:])
    return "".join(output)


def apply_patch(
    patch: str,
    *,
    workspace_root: str | os.PathLike[str] | None = None,
) -> str:
    """Apply a context-verified unified diff to existing workspace text files."""
    parsed = _parse_unified_patch(patch)
    root = _workspace_root(workspace_root)
    changes = []

    for relative_path, hunks in parsed:
        target = _resolve_workspace_path(
            relative_path, must_exist=True, workspace_root=workspace_root
        )
        if not target.is_file():
            raise WorkspaceError(f"Patch target is not a regular file: {relative_path}.")
        if target.stat().st_size > MAX_TEXT_BYTES:
            raise WorkspaceError(f"Patch target exceeds the {MAX_TEXT_BYTES}-byte limit: {relative_path}.")
        try:
            original = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceError(f"Patch target is not valid UTF-8 text: {relative_path}.") from exc
        updated = _apply_file_hunks(original, hunks, relative_path)
        if len(updated.encode("utf-8")) > MAX_TEXT_BYTES:
            raise WorkspaceError(f"Patched content exceeds the {MAX_TEXT_BYTES}-byte limit: {relative_path}.")
        changes.append((target, original, updated))

    staged = []
    replaced = []
    try:
        for target, original, updated in changes:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=target.parent,
                prefix=".niang-patch-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(updated)
                temporary_path = Path(temporary.name)
            staged.append((target, temporary_path, original))
        for target, temporary_path, original in staged:
            os.replace(temporary_path, target)
            replaced.append((target, original))
    except OSError as exc:
        for target, original in reversed(replaced):
            try:
                target.write_text(original, encoding="utf-8", newline="")
            except OSError as rollback_error:
                raise WorkspaceError(
                    f"Patch write failed ({exc}); rollback also failed for "
                    f"{target.name} ({rollback_error}). Inspect the workspace."
                ) from rollback_error
        raise WorkspaceError(f"Patch could not be applied: {exc}") from exc
    finally:
        for _, temporary_path, _ in staged:
            temporary_path.unlink(missing_ok=True)

    names = ", ".join(target.relative_to(root).as_posix() for target, _, _ in changes)
    return f"Applied verified patch to {len(changes)} file(s): {names}."


def search_text(
    query: str,
    path: str = ".",
    max_results: int = 50,
    *,
    workspace_root: str | os.PathLike[str] | None = None,
) -> str:
    if not isinstance(query, str) or not query.strip():
        raise WorkspaceError("A non-empty search query is required.")
    if len(query) > 500:
        raise WorkspaceError("Search queries must not exceed 500 characters.")
    target = _resolve_workspace_path(path, must_exist=True, workspace_root=workspace_root)
    root = _workspace_root(workspace_root)
    limit = max(1, min(int(max_results), MAX_SEARCH_RESULTS))
    candidates = [target] if target.is_file() else None
    results = []
    if candidates is None:
        candidates = []
        for current, directories, filenames in os.walk(target, topdown=True, followlinks=False):
            current_path = Path(current)
            depth = len(current_path.relative_to(target).parts)
            directories[:] = [
                name for name in directories
                if name.lower() not in IGNORED_DIRECTORIES
                and name.lower() not in SENSITIVE_NAMES
                and not name.startswith(".env")
                and not (current_path / name).is_symlink()
                and depth < 12
            ]
            for name in filenames:
                candidate = current_path / name
                if not candidate.is_symlink():
                    candidates.append(candidate)
                    if len(candidates) >= MAX_SEARCH_FILES:
                        break
            if len(candidates) >= MAX_SEARCH_FILES:
                break
    scanned_bytes = 0
    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            safe_path = _resolve_workspace_path(
                candidate.relative_to(root).as_posix(),
                must_exist=True,
                workspace_root=workspace_root,
            )
            size = safe_path.stat().st_size
            if size > MAX_TEXT_BYTES:
                continue
            scanned_bytes += size
            if scanned_bytes > MAX_SEARCH_BYTES:
                break
            contents = safe_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError, WorkspaceError):
            continue
        for line_number, line in enumerate(contents.splitlines(), start=1):
            if query.casefold() in line.casefold():
                results.append(
                    f"{safe_path.relative_to(root).as_posix()}:{line_number}: {line[:300]}"
                )
                if len(results) >= limit:
                    return "\n".join(results)
    return "\n".join(results) if results else "No matching text found in the workspace."


def run_check(
    check: str,
    timeout_seconds: int = 60,
    *,
    workspace_root: str | os.PathLike[str] | None = None,
    cancel_flag=None,
) -> str:
    root = _workspace_root(workspace_root)
    command = APPROVED_CHECKS.get(str(check).strip().lower())
    if command is None:
        raise WorkspaceError(
            f"Unsupported check '{check}'. Choose one of: {', '.join(APPROVED_CHECKS)}."
        )
    executable = shutil.which(command[0])
    if executable is None and command[0] != sys.executable:
        raise WorkspaceError(f"Required command is unavailable: {command[0]}")

    timeout = max(1, min(int(timeout_seconds), 180))
    command = [executable or command[0], *command[1:]]
    completed = _run_workspace_process(
        command, root=root, timeout=timeout, cancel_flag=cancel_flag
    )
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    output = output[-20000:]
    status = "passed" if completed.returncode == 0 else f"failed with exit code {completed.returncode}"
    return f"Check {check} {status}.\n{output}".strip()


def install_dependency(
    ecosystem: str,
    package: str,
    *,
    workspace_root: str | os.PathLike[str] | None = None,
    timeout_seconds: int = 180,
    cancel_flag=None,
) -> str:
    root = _workspace_root(workspace_root)
    if not isinstance(package, str) or not re.fullmatch(
        r"(?:[A-Za-z0-9][A-Za-z0-9._-]*|@[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)"
        r"(?:@[A-Za-z0-9.*<>=!~^+-]+)?",
        package,
    ):
        raise WorkspaceError("The dependency name or version is invalid.")

    if ecosystem == "python":
        python = next(
            (
                candidate
                for candidate in (
                    root / ".venv" / "Scripts" / "python.exe",
                    root / "venv" / "Scripts" / "python.exe",
                )
                if candidate.is_file()
            ),
            None,
        )
        if python is None:
            raise WorkspaceError(
                "Python dependency installation requires a project-local .venv or venv."
            )
        command = [
            str(python), "-m", "pip", "install", "--disable-pip-version-check",
            "--no-input", "--only-binary=:all:", "--no-cache-dir", package,
        ]
        env_overrides = {}
    elif ecosystem == "node":
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if npm is None:
            raise WorkspaceError("The npm command is unavailable.")
        command = [npm, "install", "--save", "--ignore-scripts", "--", package]
        env_overrides = {"npm_config_cache": str(root / ".niang-npm-cache")}
    elif ecosystem == "go":
        go = shutil.which("go.exe") or shutil.which("go")
        if go is None:
            raise WorkspaceError("The go command is unavailable.")
        command = [go, "get", package]
        env_overrides = {}
    elif ecosystem == "rust":
        cargo = shutil.which("cargo.exe") or shutil.which("cargo")
        if cargo is None:
            raise WorkspaceError("The cargo command is unavailable.")
        command = [cargo, "add", package]
        env_overrides = {}
    elif ecosystem == "dotnet":
        dotnet = shutil.which("dotnet.exe") or shutil.which("dotnet")
        if dotnet is None:
            raise WorkspaceError("The dotnet command is unavailable.")
        command = [dotnet, "add", "package", package]
        env_overrides = {}
    elif ecosystem == "php":
        composer = shutil.which("composer.cmd") or shutil.which("composer")
        if composer is None:
            raise WorkspaceError("The composer command is unavailable.")
        command = [composer, "require", "--no-interaction", package]
        env_overrides = {}
    elif ecosystem == "ruby":
        gem = shutil.which("gem.cmd") or shutil.which("gem")
        if gem is None:
            raise WorkspaceError("The gem command is unavailable.")
        command = [gem, "install", package]
        env_overrides = {}
    else:
        raise WorkspaceError(
            f"Unsupported dependency ecosystem '{ecosystem}'. "
            "Supported: python, node, go, rust, dotnet, php, ruby."
        )

    completed = _run_workspace_process(
        command,
        root=root,
        timeout=max(1, min(int(timeout_seconds), 180)),
        cancel_flag=cancel_flag,
        env_overrides=env_overrides,
    )
    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    output = output[-20000:]
    if completed.returncode != 0:
        raise WorkspaceError(
            f"Dependency installation failed with exit code {completed.returncode}.\n{output}"
        )
    return f"Installed {package} in the selected project.\n{output}".strip()


def _run_workspace_process(
    command: list[str],
    *,
    root: Path,
    timeout: int,
    cancel_flag=None,
    env_overrides: dict[str, str] | None = None,
):
    try:
        import psutil
    except ImportError as exc:
        raise WorkspaceError(
            "Cannot safely run project commands without process-tree tracking (psutil)."
        ) from exc

    executable = command[0]
    if os.name == "nt" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        command = [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d", "/s", "/c",
            subprocess.list2cmdline(command),
        ]
    allowed_env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
            "USERPROFILE", "APPDATA", "LOCALAPPDATA",
        }
    }
    allowed_env["PYTHONNOUSERSITE"] = "1"
    if env_overrides:
        allowed_env.update(env_overrides)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            command,
            cwd=root,
            env=allowed_env,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creation_flags,
        )
    except OSError as exc:
        raise WorkspaceError(f"Could not start the approved project operation: {exc}") from exc

    deadline = time.monotonic() + timeout
    while True:
        if cancel_flag is not None and cancel_flag.is_set():
            _terminate_workspace_process_tree(process, psutil)
            raise WorkspaceError("Project operation cancelled; its final state must be checked.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_workspace_process_tree(process, psutil)
            raise WorkspaceError(
                f"Project operation exceeded its {timeout}-second timeout; outcome is unknown."
            )
        try:
            stdout, stderr = process.communicate(timeout=min(0.25, remaining))
            if _workspace_process_descendants(process.pid, psutil):
                _terminate_workspace_process_tree(process, psutil)
                raise WorkspaceError(
                    "The project operation left child processes running; they were terminated."
                )
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            continue


def _workspace_process_descendants(root_pid: int, psutil_module) -> list:
    children_by_parent = {}
    for process in psutil_module.process_iter(["pid", "ppid"]):
        try:
            pid = process.info.get("pid")
            parent_pid = process.info.get("ppid")
        except psutil_module.Error:
            continue
        if isinstance(pid, int) and isinstance(parent_pid, int):
            children_by_parent.setdefault(parent_pid, []).append(process)

    descendants = []
    seen = {root_pid}
    frontier = [root_pid]
    while frontier:
        parent_pid = frontier.pop()
        for child in children_by_parent.get(parent_pid, ()):
            child_pid = child.pid
            if child_pid in seen:
                continue
            seen.add(child_pid)
            descendants.append(child)
            frontier.append(child_pid)
    return descendants


def _terminate_workspace_process_tree(process, psutil_module, grace_seconds: float = 3) -> None:
    root_pid = process.pid
    descendants = _workspace_process_descendants(root_pid, psutil_module)
    for child in reversed(descendants):
        try:
            child.terminate()
        except psutil_module.NoSuchProcess:
            continue

    try:
        process.terminate()
    except OSError:
        pass

    _, alive = psutil_module.wait_procs(descendants, timeout=grace_seconds)
    for child in reversed(alive):
        try:
            child.kill()
        except psutil_module.NoSuchProcess:
            continue
    if alive:
        _, alive = psutil_module.wait_procs(alive, timeout=2)
    if alive:
        raise WorkspaceError(
            "The approved project process tree could not be confirmed stopped."
        )

    if process.poll() is None:
        process.kill()
    try:
        process.communicate(timeout=2)
    except subprocess.TimeoutExpired as exc:
        raise WorkspaceError(
            "The approved project process tree could not be confirmed stopped."
        ) from exc

    descendants = _workspace_process_descendants(root_pid, psutil_module)
    for child in reversed(descendants):
        try:
            child.terminate()
        except psutil_module.NoSuchProcess:
            continue
    _, alive = psutil_module.wait_procs(descendants, timeout=1)
    for child in alive:
        try:
            child.kill()
        except psutil_module.NoSuchProcess:
            continue
    if alive:
        psutil_module.wait_procs(alive, timeout=2)

    remaining = []
    for child in _workspace_process_descendants(root_pid, psutil_module):
        try:
            if child.is_running() and child.status() != psutil_module.STATUS_ZOMBIE:
                remaining.append(child.pid)
        except psutil_module.NoSuchProcess:
            continue
    if process.poll() is None or remaining:
        raise WorkspaceError(
            "The approved project process tree could not be confirmed stopped."
        )


# ---------------------------------------------------------------------------
# Project detection — multilanguage support
# ---------------------------------------------------------------------------

_PROJECT_MARKERS = {
    "package.json": {"languages": ["javascript", "typescript"], "ecosystem": "node"},
    "tsconfig.json": {"languages": ["typescript"], "ecosystem": "node"},
    "vite.config.ts": {"languages": ["typescript"], "ecosystem": "node"},
    "vite.config.js": {"languages": ["javascript"], "ecosystem": "node"},
    "next.config.js": {"languages": ["javascript", "typescript"], "ecosystem": "node"},
    "next.config.mjs": {"languages": ["javascript", "typescript"], "ecosystem": "node"},
    "requirements.txt": {"languages": ["python"], "ecosystem": "python"},
    "pyproject.toml": {"languages": ["python"], "ecosystem": "python"},
    "setup.py": {"languages": ["python"], "ecosystem": "python"},
    "setup.cfg": {"languages": ["python"], "ecosystem": "python"},
    "go.mod": {"languages": ["go"], "ecosystem": "go"},
    "go.sum": {"languages": ["go"], "ecosystem": "go"},
    "Cargo.toml": {"languages": ["rust"], "ecosystem": "rust"},
    "Cargo.lock": {"languages": ["rust"], "ecosystem": "rust"},
    "pom.xml": {"languages": ["java"], "ecosystem": "java"},
    "build.gradle": {"languages": ["java", "kotlin"], "ecosystem": "java"},
    "build.gradle.kts": {"languages": ["java", "kotlin"], "ecosystem": "java"},
    "settings.gradle": {"languages": ["java", "kotlin"], "ecosystem": "java"},
    "composer.json": {"languages": ["php"], "ecosystem": "php"},
    "pubspec.yaml": {"languages": ["dart"], "ecosystem": "dart"},
    "Gemfile": {"languages": ["ruby"], "ecosystem": "ruby"},
    "CMakeLists.txt": {"languages": ["c", "cpp"], "ecosystem": "cpp"},
    "Makefile": {"languages": ["c", "cpp"], "ecosystem": "cpp"},
    "makefile": {"languages": ["c", "cpp"], "ecosystem": "cpp"},
    "*.csproj": {"languages": ["csharp"], "ecosystem": "dotnet"},
    "*.sln": {"languages": ["csharp"], "ecosystem": "dotnet"},
}


def detect_project_languages(workspace_root: str | os.PathLike[str]) -> dict[str, Any]:
    """Analyse un dossier de projet et retourne les langages, écosystèmes et frameworks détectés.

    Lecture seule : ne modifie aucun fichier. Identifie les marqueurs de configuration
    et les extensions de fichiers sources présents à la racine du projet.
    """
    root = Path(workspace_root)
    if not root.is_dir():
        return {
            "languages": [],
            "ecosystems": [],
            "frameworks": [],
            "markers": [],
            "source_extensions": [],
            "detected": False,
        }

    languages: set[str] = set()
    ecosystems: set[str] = set()
    markers_found: list[str] = []
    frameworks: set[str] = set()

    try:
        entries = [p.name for p in root.iterdir()]
    except OSError:
        entries = []

    for entry in entries:
        info = _PROJECT_MARKERS.get(entry)
        if info:
            languages.update(info["languages"])
            ecosystems.add(info["ecosystem"])
            markers_found.append(entry)
            continue
        for pattern, info in _PROJECT_MARKERS.items():
            if "*" in pattern:
                prefix, _, suffix = pattern.partition("*")
                if entry.startswith(prefix) and entry.endswith(suffix):
                    languages.update(info["languages"])
                    ecosystems.add(info["ecosystem"])
                    markers_found.append(entry)
                    break

    if "package.json" in entries:
        frameworks.add("node")
    if "tsconfig.json" in entries:
        frameworks.add("typescript")
    if "next.config.js" in entries or "next.config.mjs" in entries:
        frameworks.add("nextjs")
    if "vite.config.ts" in entries or "vite.config.js" in entries:
        frameworks.add("vite")
    if "pyproject.toml" in entries:
        frameworks.add("python-packaging")
    if "Cargo.toml" in entries:
        frameworks.add("cargo")
    if "composer.json" in entries:
        frameworks.add("composer")
    if "pubspec.yaml" in entries:
        frameworks.add("flutter")

    source_extensions: set[str] = set()
    ext_to_lang = {
        ".py": "python", ".js": "javascript", ".jsx": "jsx", ".ts": "typescript",
        ".tsx": "tsx", ".go": "go", ".rs": "rust", ".cs": "csharp", ".java": "java",
        ".kt": "kotlin", ".kts": "kotlin", ".dart": "dart", ".swift": "swift",
        ".c": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".h": "c",
        ".hpp": "cpp", ".php": "php", ".rb": "ruby", ".sql": "sql", ".html": "html",
        ".css": "css", ".json": "json", ".yaml": "yaml", ".yml": "yaml",
        ".toml": "toml", ".md": "markdown", ".xml": "xml", ".sh": "shell",
        ".ps1": "powershell",
    }
    try:
        for entry in root.iterdir():
            if entry.is_file():
                ext = entry.suffix.lower()
                if ext in ext_to_lang:
                    source_extensions.add(ext)
                    languages.add(ext_to_lang[ext])
    except OSError:
        pass

    return {
        "languages": sorted(languages),
        "ecosystems": sorted(ecosystems),
        "frameworks": sorted(frameworks),
        "markers": markers_found,
        "source_extensions": sorted(source_extensions),
        "detected": bool(markers_found or source_extensions),
    }

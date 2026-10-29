"""Workspace-scoped file operations and a small set of approved checks."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_TEXT_BYTES = 1_000_000
MAX_SEARCH_RESULTS = 100
IGNORED_DIRECTORIES = {
    ".git", ".hg", ".svn", ".venv", "venv", "node_modules",
    "__pycache__", "dist", "build", ".pytest_cache", ".aws", ".ssh",
    ".gnupg",
}
SENSITIVE_NAMES = {
    "api_keys.json", "credentials.json", "token.json", "bridge_token.txt",
    "client_secret.json", "service_account.json", ".netrc", ".npmrc",
    "id_rsa", "id_ed25519",
}
APPROVED_CHECKS = {
    "python-tests": [sys.executable, "-m", "pytest", "-q"],
    "python-unittest": [sys.executable, "-m", "unittest"],
    "python-compile": [sys.executable, "-m", "compileall", "-q", "."],
    "npm-test": ["npm", "test"],
    "npm-build": ["npm", "run", "build"],
    "npm-lint": ["npm", "run", "lint"],
    "git-status": ["git", "status", "--short"],
    "git-diff-check": ["git", "diff", "--check"],
}


class WorkspaceError(ValueError):
    """Raised when an operation is not allowed in the configured workspace."""


def _workspace_root() -> Path:
    configured = os.environ.get("NIANG_IA_WORKSPACE_ROOT", "").strip()
    if not configured:
        raise WorkspaceError(
            "Workspace tools are disabled. Set NIANG_IA_WORKSPACE_ROOT to the "
            "project folder you explicitly authorize, then restart NIANG IA."
        )
    try:
        root = Path(configured).expanduser().resolve(strict=True)
    except OSError as exc:
        raise WorkspaceError(f"Configured workspace cannot be opened: {exc}") from exc
    if not root.is_dir():
        raise WorkspaceError("NIANG_IA_WORKSPACE_ROOT must point to a directory.")
    return root


def _resolve_workspace_path(path: str, *, must_exist: bool = False) -> Path:
    root = _workspace_root()
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
        if current.is_symlink():
            raise WorkspaceError("Workspace operations do not follow symbolic links.")
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
    return resolved


def list_files(path: str = ".", max_entries: int = 200) -> str:
    target = _resolve_workspace_path(path, must_exist=True)
    if not target.is_dir():
        raise WorkspaceError("The requested workspace path is not a directory.")
    limit = max(1, min(int(max_entries), 500))
    root = _workspace_root()
    results = []
    for candidate in target.rglob("*"):
        relative = candidate.relative_to(root)
        if any(part.lower() in IGNORED_DIRECTORIES for part in relative.parts):
            continue
        if any(part.lower() in SENSITIVE_NAMES or part.startswith(".env") for part in relative.parts):
            continue
        if candidate.is_symlink():
            continue
        depth = len(candidate.relative_to(target).parts)
        if depth > 3 or not (candidate.is_file() or candidate.is_dir()):
            continue
        results.append(f"{'DIR ' if candidate.is_dir() else 'FILE'} {relative.as_posix()}")
        if len(results) >= limit:
            break
    return "\n".join(results) if results else "No accessible files found in that workspace folder."


def read_file(path: str) -> str:
    target = _resolve_workspace_path(path, must_exist=True)
    if not target.is_file():
        raise WorkspaceError("The requested workspace path is not a file.")
    if target.stat().st_size > MAX_TEXT_BYTES:
        raise WorkspaceError(f"Files larger than {MAX_TEXT_BYTES} bytes cannot be read.")
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise WorkspaceError("The requested file is not valid UTF-8 text.") from exc


def write_file(path: str, content: str) -> str:
    if not isinstance(content, str):
        raise WorkspaceError("File content must be text.")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_TEXT_BYTES:
        raise WorkspaceError(f"File content exceeds the {MAX_TEXT_BYTES}-byte limit.")
    target = _resolve_workspace_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target = _resolve_workspace_path(path)
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
    return f"Wrote {len(encoded)} bytes to {target.relative_to(_workspace_root()).as_posix()}."


def edit_file(
    path: str,
    find: str,
    replace: str,
    expected_occurrences: int = 1,
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

    target = _resolve_workspace_path(path, must_exist=True)
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
        f"{target.relative_to(_workspace_root()).as_posix()}."
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


def apply_patch(patch: str) -> str:
    """Apply a context-verified unified diff to existing workspace text files."""
    parsed = _parse_unified_patch(patch)
    root = _workspace_root()
    changes = []

    for relative_path, hunks in parsed:
        target = _resolve_workspace_path(relative_path, must_exist=True)
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


def search_text(query: str, path: str = ".", max_results: int = 50) -> str:
    if not isinstance(query, str) or not query.strip():
        raise WorkspaceError("A non-empty search query is required.")
    if len(query) > 500:
        raise WorkspaceError("Search queries must not exceed 500 characters.")
    target = _resolve_workspace_path(path, must_exist=True)
    root = _workspace_root()
    limit = max(1, min(int(max_results), MAX_SEARCH_RESULTS))
    candidates = [target] if target.is_file() else target.rglob("*")
    results = []
    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            safe_path = _resolve_workspace_path(candidate.relative_to(root).as_posix(), must_exist=True)
            if safe_path.stat().st_size > MAX_TEXT_BYTES:
                continue
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


def run_check(check: str, timeout_seconds: int = 60) -> str:
    root = _workspace_root()
    command = APPROVED_CHECKS.get(str(check).strip().lower())
    if command is None:
        raise WorkspaceError(
            f"Unsupported check '{check}'. Choose one of: {', '.join(APPROVED_CHECKS)}."
        )
    executable = shutil.which(command[0])
    if executable is None and command[0] != sys.executable:
        raise WorkspaceError(f"Required command is unavailable: {command[0]}")

    timeout = max(1, min(int(timeout_seconds), 120))
    command = [executable or command[0], *command[1:]]
    allowed_env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
            "USERPROFILE", "APPDATA", "LOCALAPPDATA",
        }
    }
    allowed_env["PYTHONNOUSERSITE"] = "1"
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=allowed_env,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise WorkspaceError(
            f"Check '{check}' exceeded its {timeout}-second timeout; outcome is unknown."
        ) from exc

    output = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
    output = output[-20000:]
    status = "passed" if completed.returncode == 0 else f"failed with exit code {completed.returncode}"
    return f"Check {check} {status}.\n{output}".strip()

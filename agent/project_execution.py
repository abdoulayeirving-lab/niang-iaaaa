"""Project inspection and supervised launch for workspace applications."""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shlex
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from agent.secrets import redact_if_sensitive
from agent.terminal_agent import TerminalAgent, _DEFAULT_TERMINAL_AGENT
from agent.workspace_tools import WorkspaceError, _resolve_workspace_path


_SCRIPT_NAME = re.compile(r"^[A-Za-z0-9:_-]{1,80}$")
_PORT_FLAG = re.compile(r"(?i)(?:--port(?:=|\s+)|\bport\s*=\s*|PORT=)(\d{2,5})")
_DEFAULT_PORTS = {
    "vite": (5173, 3000),
    "next": (3000,),
    "react": (3000,),
    "vue": (5173,),
    "angular": (4200,),
    "svelte": (5173, 3000),
    "astro": (4321,),
    "node": (3000, 5173, 8000, 8080),
    "flask": (5000,),
    "fastapi": (8000,),
    "django": (8000,),
}
_IGNORED = {".git", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}


class ProjectExecutionError(RuntimeError):
    """A project could not be inspected, launched, or verified safely."""


def _project_root(path: str) -> Path:
    try:
        target = _resolve_workspace_path(path or ".", must_exist=True)
    except (OSError, WorkspaceError) as exc:
        raise ProjectExecutionError(str(exc)) from exc
    if not target.is_dir():
        raise ProjectExecutionError("Project path must be a directory inside the authorized workspace.")
    return target


def _read_manifest(root: Path, name: str) -> str | None:
    path = root / name
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 1_000_000:
        return None
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None


def _package_manager(root: Path) -> str:
    for lock, manager in (
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
        ("bun.lock", "bun"),
        ("package-lock.json", "npm"),
    ):
        if (root / lock).is_file():
            return manager
    return "npm"


def _python_dependencies(root: Path) -> tuple[list[str], list[str]]:
    source = _read_manifest(root, "requirements.txt") or ""
    names = []
    for line in source.splitlines():
        value = line.split("#", 1)[0].strip()
        if not value or value.startswith(("-", ".")):
            continue
        name = re.split(r"[<=>!~;\[]", value, maxsplit=1)[0].strip()
        if name:
            names.append(name)
    pyproject = _read_manifest(root, "pyproject.toml")
    if pyproject:
        try:
            import tomllib
        except ImportError:
            return names, []
        try:
            metadata = tomllib.loads(pyproject)
        except tomllib.TOMLDecodeError as exc:
            raise ProjectExecutionError("pyproject.toml is invalid TOML.") from exc
        project = metadata.get("project", {})
        if isinstance(project, dict):
            project_dependencies = project.get("dependencies", [])
            if isinstance(project_dependencies, list):
                names.extend(
                    re.split(r"[<=>!~;\[]", item, maxsplit=1)[0].strip()
                    for item in project_dependencies
                    if isinstance(item, str) and item.strip()
                )
        poetry = metadata.get("tool", {}).get("poetry", {})
        poetry_dependencies = poetry.get("dependencies", {}) if isinstance(poetry, dict) else {}
        if isinstance(poetry_dependencies, dict):
            names.extend(name for name in poetry_dependencies if name.casefold() != "python")
    names = list(dict.fromkeys(names))
    installed = {dist.metadata["Name"].casefold() for dist in importlib.metadata.distributions()
                 if dist.metadata.get("Name")}
    missing = [
        name for name in names
        if re.sub(r"[-_.]+", "-", name).casefold() not in {
            re.sub(r"[-_.]+", "-", item).casefold() for item in installed
        }
    ]
    return names, missing


def inspect_project(path: str = ".") -> dict:
    root = _project_root(path)
    result: dict = {
        "root": path or ".",
        "framework": "unknown",
        "kind": "unknown",
        "package_manager": None,
        "scripts": {},
        "dependencies_installed": None,
        "missing_dependencies": [],
        "start_script": None,
        "recommended_action": "Inspect project files and select an explicit launch command.",
    }

    package_text = _read_manifest(root, "package.json")
    if package_text is not None:
        try:
            package = json.loads(package_text)
        except json.JSONDecodeError as exc:
            raise ProjectExecutionError("package.json is invalid JSON; no command was inferred.") from exc
        if not isinstance(package, dict):
            raise ProjectExecutionError("package.json must contain an object.")
        dependencies = {
            **(package.get("dependencies") if isinstance(package.get("dependencies"), dict) else {}),
            **(package.get("devDependencies") if isinstance(package.get("devDependencies"), dict) else {}),
        }
        scripts = package.get("scripts", {})
        scripts = scripts if isinstance(scripts, dict) else {}
        result.update(
            framework=_detect_js_framework(dependencies),
            kind="web",
            package_manager=_package_manager(root),
            scripts={str(name): redact_if_sensitive(str(command)[:500],
                                                     "[script redacted because it may contain a secret]")
                     for name, command in scripts.items()
                     if isinstance(name, str) and isinstance(command, str)},
            dependencies_installed=(root / "node_modules").is_dir(),
        )
        result["start_script"] = next(
            (name for name in ("dev", "start", "serve") if name in scripts),
            None,
        )
        if result["start_script"]:
            result["recommended_action"] = (
                f"Start the existing '{result['start_script']}' script after explicit approval."
            )
        else:
            result["recommended_action"] = "No dev/start/serve package script was found."
        return result

    pyproject = _read_manifest(root, "pyproject.toml")
    requirements = _read_manifest(root, "requirements.txt")
    if pyproject is not None or requirements is not None:
        main_text = _read_manifest(root, "main.py") or ""
        desktop_sources = main_text
        if re.search(r"(?m)^\s*(?:from\s+ui\s+import\b|import\s+ui(?:\s|$))", main_text):
            desktop_sources += "\n" + (_read_manifest(root, "ui.py") or "")
        is_tk = bool(re.search(r"\b(?:tkinter|TkinterDnD)\b", desktop_sources))
        framework = "python-tkinter" if is_tk else "python"
        deps, missing = _python_dependencies(root)
        lower_dependencies = {dependency.casefold().replace("_", "-") for dependency in deps}
        web_framework = next(
            (name for name in ("fastapi", "flask", "django") if name in lower_dependencies),
            None,
        )
        if web_framework:
            framework = web_framework
            kind = "web"
        else:
            kind = "desktop" if is_tk else "python"
        result.update(
            framework=framework,
            kind=kind,
            package_manager=_python_package_manager(root),
            dependencies_installed=not missing,
            missing_dependencies=missing,
            start_script="main.py" if (root / "main.py").is_file() else None,
            recommended_action=(
                "Launch main.py as a desktop application after explicit approval."
                if kind == "desktop" and (root / "main.py").is_file()
                else "Launch main.py as a web application after explicit approval."
                if kind == "web" and (root / "main.py").is_file()
                else "A Python manifest was found; no launch entry point was inferred."
            ),
        )
        if kind == "python" and (root / "main.py").is_file():
            result["recommended_action"] = "Launch main.py after explicit approval."
        return result

    for filename, framework, kind in (
        ("Cargo.toml", "rust", "cli"),
        ("go.mod", "go", "cli"),
        ("pubspec.yaml", "flutter", "mobile-or-web"),
    ):
        if (root / filename).is_file():
            result.update(
                framework=framework,
                kind=kind,
                package_manager={"rust": "cargo", "go": "go", "flutter": "flutter"}[framework],
                recommended_action=f"Manifest detected ({filename}); automatic launch is not configured.",
            )
            return result
    for project_file in root.glob("*.csproj"):
        if project_file.is_file():
            result.update(
                framework=".NET",
                kind="dotnet",
                package_manager="dotnet",
                recommended_action="A .NET project was detected; automatic launch is not configured.",
            )
            return result
    return result


def _detect_js_framework(dependencies: dict) -> str:
    keys = {str(name).casefold() for name in dependencies}
    for package, framework in (
        ("next", "next"),
        ("vite", "vite"),
        ("react", "react"),
        ("vue", "vue"),
        ("@angular/core", "angular"),
        ("svelte", "svelte"),
        ("astro", "astro"),
    ):
        if package in keys:
            return framework
    return "node"


def _python_package_manager(root: Path) -> str:
    if (root / "uv.lock").is_file():
        return "uv"
    if (root / "poetry.lock").is_file():
        return "poetry"
    if (root / "Pipfile.lock").is_file():
        return "pipenv"
    if (root / "pdm.lock").is_file():
        return "pdm"
    return "pip"


def _ports(profile: dict) -> list[int]:
    script = profile.get("scripts", {}).get(profile.get("start_script"), "")
    match = _PORT_FLAG.search(script)
    if match:
        value = int(match.group(1))
        return [value] if 1 <= value <= 65535 else []
    return list(_DEFAULT_PORTS.get(profile.get("framework"), ()))


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _health_check(port: int, timeout: float = 1.5) -> dict:
    url = f"http://127.0.0.1:{port}/"
    request = urllib.request.Request(url, headers={"User-Agent": "NIANG-IA-ProjectHealth/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"ok": 200 <= response.status < 500, "status_code": response.status, "url": url}
    except urllib.error.HTTPError as exc:
        return {"ok": 200 <= exc.code < 500, "status_code": exc.code, "url": url}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "url": url, "error": type(exc).__name__}


class ProjectExecutionManager:
    def __init__(self, terminal: TerminalAgent | None = None) -> None:
        self.terminal = terminal or _DEFAULT_TERMINAL_AGENT
        self._projects: dict[str, dict] = {}

    def inspect(self, path: str = ".") -> dict:
        return inspect_project(path)

    def start(
        self,
        path: str = ".",
        shell: str | None = None,
        cancel_event=None,
        health_timeout_seconds: int = 20,
    ) -> dict:
        profile = inspect_project(path)
        root = _project_root(path)
        timeout = _bounded_health_timeout(health_timeout_seconds)
        command, selected_shell = self._launch_command(root, profile, shell)
        project_key = str(root).casefold()

        existing_id = self.terminal.find_running(path, command)
        if existing_id:
            status = json.loads(self.terminal.status(existing_id))
            url = self._healthy_url(profile) if profile["kind"] == "web" else None
            healthy = profile["kind"] != "web" or url is not None
            if url:
                self._set_preview(project_key, existing_id, url)
            return {
                "status": "already_running" if healthy else "already_running_unverified",
                "process_id": existing_id,
                "process": status,
                "url": url,
                "verified": healthy,
            }

        external_pid = self._external_project_process(root)
        if external_pid is not None:
            return {
                "status": "already_running_external",
                "pid": external_pid,
                "url": self._healthy_url(profile) if profile["kind"] == "web" else None,
                "verified": False,
                "note": "The project appears to be running outside NIANG's process manager; it was not started again.",
            }

        candidate_ports = _ports(profile) if profile["kind"] == "web" else []
        occupied = [port for port in candidate_ports if _port_open(port)]
        if occupied:
            raise ProjectExecutionError(
                "A local service already occupies the expected port(s) "
                f"{', '.join(map(str, occupied))}; its project identity could not be verified, "
                "so no duplicate server was started."
            )

        if profile["kind"] == "desktop" and profile.get("start_script") == "main.py":
            script = (root / "main.py").resolve()
            started = json.loads(self.terminal.start_program(
                [sys.executable, "-u", str(script)],
                cwd=path or ".",
                process_identity=command,
                cancel_event=cancel_event,
            ))
        else:
            started = json.loads(self.terminal.start(
                selected_shell,
                command,
                cwd=path or ".",
                cancel_event=cancel_event,
            ))
        process_id = started["process_id"]
        self._projects[project_key] = {
            "process_id": process_id,
            "profile": profile,
            "command": command,
        }
        if cancel_event is not None and cancel_event.is_set():
            self.stop(process_id)
            raise ProjectExecutionError(
                "Project startup cancelled; the managed process was stopped if possible."
            )
        if profile["kind"] != "web":
            desktop = {"verified": False}
            if profile["kind"] == "desktop":
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if cancel_event is not None and cancel_event.is_set():
                        self.stop(process_id)
                        raise ProjectExecutionError(
                            "Project startup cancelled; the managed process was stopped if possible."
                        )
                    process_status = json.loads(self.terminal.status(process_id))
                    if process_status["state"] != "running":
                        break
                    try:
                        from agent.windows_desktop import WindowsDesktopAgent

                        windows = WindowsDesktopAgent().list_windows(
                            pid=started["pid"],
                            include_hidden=True,
                        )
                        candidates = [
                            window for window in windows
                            if window["visible"] and window["title"]
                        ]
                        desktop_window = max(
                            candidates,
                            key=lambda window: (
                                window["role"] == "main",
                                window["bounds"]["width"] * window["bounds"]["height"]
                                if window["bounds"] else 0,
                            ),
                            default=None,
                        )
                        if desktop_window:
                            desktop = {
                                "verified": True,
                                "window_title": desktop_window["title"][:160],
                                "hwnd": desktop_window["hwnd"],
                                "window_pid": desktop_window["pid"],
                                "window": desktop_window,
                            }
                            break
                    except (ImportError, OSError, RuntimeError, ValueError):
                        break
                    time.sleep(0.1)
            final_status = json.loads(self.terminal.status(process_id))
            logs = json.loads(self.terminal.logs(process_id))
            if final_status["state"] != "running":
                return {
                    "status": "failed",
                    "kind": profile["kind"],
                    "process_id": process_id,
                    "pid": started["pid"],
                    "exit_code": final_status["exit_code"],
                    "verified": False,
                    "logs": logs,
                    "note": "The application exited before a live desktop window could be verified.",
                }
            return {
                "status": "started" if desktop["verified"] else "started_unverified",
                "kind": profile["kind"],
                "process_id": process_id,
                "pid": started["pid"],
                "verified": desktop["verified"],
                "window_title": desktop.get("window_title"),
                "hwnd": desktop.get("hwnd"),
                "window_pid": desktop.get("window_pid"),
                "url": None,
                "logs": logs,
                "process_tree": self._process_tree(started["pid"]),
                "note": (
                    "Desktop window detected through native Windows APIs."
                    if desktop["verified"]
                    else "No accessible desktop window was verified; no browser URL was inferred."
                ),
            }

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                self.terminal.stop(process_id)
                raise ProjectExecutionError(
                    "Project startup cancelled; the managed process was stopped if possible."
                )
            status = json.loads(self.terminal.status(process_id))
            if status["state"] != "running":
                logs = json.loads(self.terminal.logs(process_id))
                raise ProjectExecutionError(
                    "The project process exited before becoming healthy. "
                    + json.dumps(logs, ensure_ascii=False)[:8000]
                )
            for port in candidate_ports:
                health = _health_check(port)
                if health["ok"]:
                    self._set_preview(project_key, process_id, health["url"])
                    return {
                        "status": "healthy",
                        "process_id": process_id,
                        "pid": started["pid"],
                        "url": health["url"],
                        "health": health,
                        "verified": True,
                    }
            time.sleep(0.25)
        return {
            "status": "started_unverified",
            "process_id": process_id,
            "pid": started["pid"],
            "url": None,
            "logs": json.loads(self.terminal.logs(process_id)),
            "verified": False,
        }

    def status(self, process_id: str) -> dict:
        return json.loads(self.terminal.status(process_id))

    def logs(self, process_id: str) -> dict:
        return json.loads(self.terminal.logs(process_id))

    @staticmethod
    def _process_tree(pid: int) -> list[dict]:
        try:
            from agent.windows_desktop import WindowsDesktopAgent

            return WindowsDesktopAgent().process_tree(pid)
        except (ImportError, OSError, RuntimeError, ValueError):
            return [{"pid": pid, "process_name": None, "state": "unavailable"}]

    def stop(self, process_id: str) -> dict:
        result = json.loads(self.terminal.stop(process_id))
        for project_key, project in tuple(self._projects.items()):
            if project.get("process_id") == process_id:
                project.pop("preview", None)
                if result.get("state") == "stopped":
                    self._projects.pop(project_key, None)
        return result

    @staticmethod
    def _launch_command(root: Path, profile: dict, shell: str | None) -> tuple[str, str]:
        kind = profile["kind"]
        selected_shell = shell or _default_shell()
        powershell = selected_shell.casefold() in {"powershell", "powershell.exe", "pwsh"}

        def quote(value: str) -> str:
            if powershell:
                return "'" + value.replace("'", "''") + "'"
            return shlex.quote(value)

        if kind in {"desktop", "python"} and profile.get("start_script") == "main.py":
            script = (root / "main.py").resolve()
            try:
                script.relative_to(root.resolve())
            except ValueError as exc:
                raise ProjectExecutionError("The launch script resolves outside the project.") from exc
            command = (
                f"& {quote(sys.executable)} {quote(str(script))}"
                if powershell
                else f"{quote(sys.executable)} {quote(str(script))}"
            )
            return command, selected_shell
        if kind == "web" and profile.get("package_manager") in {"pip", "uv", "poetry", "pipenv", "pdm"}:
            script = profile.get("start_script")
            if script != "main.py":
                raise ProjectExecutionError("No Python web application entry point was identified.")
            entry = (root / script).resolve()
            command = (
                f"& {quote(sys.executable)} {quote(str(entry))}"
                if powershell
                else f"{quote(sys.executable)} {quote(str(entry))}"
            )
            return command, selected_shell

        if kind == "web":
            manager = profile.get("package_manager")
            script = profile.get("start_script")
            if not script or not _SCRIPT_NAME.fullmatch(script):
                raise ProjectExecutionError("No safe dev/start/serve script was identified.")
            if manager not in {"npm", "pnpm", "yarn", "bun"}:
                raise ProjectExecutionError("The package manager is not supported for supervised startup.")
            executable = shutil.which(manager)
            if executable is None and not (os.name == "nt" and shutil.which(f"{manager}.cmd")):
                raise ProjectExecutionError(f"Package manager '{manager}' is not available on PATH.")
            if os.name == "nt":
                executable = shutil.which(f"{manager}.cmd") or executable
                command = (
                    f"& {quote(str(executable))} run {script}"
                    if powershell
                    else f"{quote(str(executable))} run {script}"
                )
            else:
                command = f"{manager} run {script}"
            return command, selected_shell

        raise ProjectExecutionError(
            f"No supported launch action for detected project kind '{kind}'."
        )

    @staticmethod
    def _healthy_url(profile: dict) -> str | None:
        for port in _ports(profile):
            health = _health_check(port)
            if health["ok"]:
                return health["url"]
        return None

    def _set_preview(self, project_key: str, process_id: str, url: str) -> None:
        parsed = urlsplit(url)
        self._projects[project_key]["preview"] = {
            "process_id": process_id,
            "host": parsed.hostname,
            "port": parsed.port,
        }

    def is_authorized_preview(self, host: str, port: int) -> bool:
        normalized_host = str(host or "").casefold().rstrip(".")
        if normalized_host != "127.0.0.1":
            return False
        for project in self._projects.values():
            preview = project.get("preview") or {}
            if preview.get("host") != normalized_host or preview.get("port") != port:
                continue
            try:
                status = json.loads(self.terminal.status(preview["process_id"]))
            except (TerminalAgentError, KeyError, json.JSONDecodeError):
                continue
            if (
                status.get("state") == "running"
                and self.terminal.owns_listening_port(
                    preview["process_id"],
                    port,
                )
            ):
                return True
        return False

    def is_authorized_preview_url(self, url: str) -> bool:
        try:
            parsed = urlsplit(url)
            port = parsed.port or (443 if parsed.scheme.casefold() == "https" else 80)
        except ValueError:
            return False
        return (
            parsed.scheme.casefold() in {"http", "https"}
            and parsed.hostname is not None
            and self.is_authorized_preview(parsed.hostname, port)
        )

    @staticmethod
    def _external_project_process(root: Path) -> int | None:
        try:
            import psutil
        except ImportError:
            return None
        normalized_root = os.path.normcase(str(root.resolve()))
        for process in psutil.process_iter(("pid", "cwd", "cmdline")):
            try:
                if process.info["pid"] == os.getpid():
                    continue
                cwd = process.info.get("cwd")
                argv = process.info.get("cmdline") or []
                if not cwd or not argv:
                    continue
                if os.path.normcase(str(Path(cwd).resolve())) != normalized_root:
                    continue
                if any(Path(argument.strip('"')).name.casefold() == "main.py" for argument in argv):
                    return int(process.info["pid"])
            except (OSError, RuntimeError, TypeError, ValueError):
                continue
        return None

def _default_shell() -> str:
    return "powershell" if os.name == "nt" else "bash"


def _bounded_health_timeout(value: int) -> int:
    if type(value) is not int or not 1 <= value <= 120:
        raise ProjectExecutionError("health_timeout_seconds must be an integer from 1 to 120.")
    return value


_DEFAULT_PROJECT_MANAGER = ProjectExecutionManager()


def is_authorized_local_preview_target(host: str, port: int) -> bool:
    return _DEFAULT_PROJECT_MANAGER.is_authorized_preview(host, port)


def is_authorized_local_preview_url(url: str) -> bool:
    return _DEFAULT_PROJECT_MANAGER.is_authorized_preview_url(url)


def project_execution(
    parameters: dict,
    cancel_event=None,
) -> str:
    args = dict(parameters or {})
    action = str(args.get("action", "")).strip().lower()
    if action == "inspect":
        result = _DEFAULT_PROJECT_MANAGER.inspect(args.get("path", "."))
    elif action == "start":
        result = _DEFAULT_PROJECT_MANAGER.start(
            path=args.get("path", "."),
            shell=args.get("shell"),
            cancel_event=cancel_event,
            health_timeout_seconds=args.get("health_timeout_seconds", 20),
        )
    elif action == "status":
        result = _DEFAULT_PROJECT_MANAGER.status(args.get("process_id", ""))
    elif action == "logs":
        result = _DEFAULT_PROJECT_MANAGER.logs(args.get("process_id", ""))
    elif action == "stop":
        result = _DEFAULT_PROJECT_MANAGER.stop(args.get("process_id", ""))
    else:
        raise ProjectExecutionError("Unsupported project action. Use inspect, start, status, logs, or stop.")
    return json.dumps(result, ensure_ascii=False)

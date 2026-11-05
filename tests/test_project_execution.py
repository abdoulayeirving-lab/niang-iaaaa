import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.project_execution import (
    ProjectExecutionError,
    ProjectExecutionManager,
    _ports,
    inspect_project,
)
from agent.terminal_agent import TerminalAgent


class ProjectExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = patch.dict(
            os.environ,
            {"NIANG_IA_WORKSPACE_ROOT": str(self.root)},
            clear=False,
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.addCleanup(self.temp.cleanup)

    def test_detects_javascript_framework_scripts_manager_and_dependencies(self):
        (self.root / "package.json").write_text(json.dumps({
            "dependencies": {"vite": "^6.0.0"},
            "scripts": {"dev": "vite --host 127.0.0.1 --port 5174", "test": "vitest"},
        }))
        (self.root / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'")

        profile = inspect_project()

        self.assertEqual(profile["framework"], "vite")
        self.assertEqual(profile["kind"], "web")
        self.assertEqual(profile["package_manager"], "pnpm")
        self.assertEqual(profile["start_script"], "dev")
        self.assertFalse(profile["dependencies_installed"])
        self.assertEqual(_ports(profile), [5174])

    def test_detects_tkinter_as_desktop_not_web(self):
        (self.root / "requirements.txt").write_text("requests>=2\n")
        (self.root / "main.py").write_text("import tkinter as tk\n")

        profile = inspect_project()

        self.assertEqual(profile["framework"], "python-tkinter")
        self.assertEqual(profile["kind"], "desktop")
        self.assertEqual(profile["start_script"], "main.py")
        self.assertIn("desktop application", profile["recommended_action"])

    def test_detects_tkinter_in_ui_module_imported_by_entrypoint(self):
        (self.root / "requirements.txt").write_text("requests>=2\n")
        (self.root / "main.py").write_text("from ui import Application\n")
        (self.root / "ui.py").write_text("import tkinter as tk\n")

        profile = inspect_project()

        self.assertEqual(profile["framework"], "python-tkinter")
        self.assertEqual(profile["kind"], "desktop")

    def test_reads_utf8_bom_requirements_without_corrupting_dependency_names(self):
        (self.root / "requirements.txt").write_text("\ufeffrequests>=2\n", encoding="utf-8")
        (self.root / "main.py").write_text("print('hello')\n")
        distribution = type("Distribution", (), {"metadata": {"Name": "example"}})()

        with patch(
            "agent.project_execution.importlib.metadata.distributions",
            return_value=[distribution],
        ):
            profile = inspect_project()

        self.assertIn("requests", profile["missing_dependencies"])
        self.assertNotIn("\ufeffrequests", profile["missing_dependencies"])

    def test_invalid_package_manifest_fails_closed(self):
        (self.root / "package.json").write_text("{")

        with self.assertRaisesRegex(ProjectExecutionError, "invalid JSON"):
            inspect_project()

    def test_project_path_cannot_escape_authorized_root(self):
        with self.assertRaises(ProjectExecutionError):
            inspect_project("..")

    def test_reports_occupied_port_without_launching_duplicate_process(self):
        (self.root / "package.json").write_text(json.dumps({
            "dependencies": {"vite": "^6"},
            "scripts": {"dev": "vite --port 5173"},
        }))
        manager = ProjectExecutionManager(TerminalAgent())
        with (
            patch.object(manager, "_external_project_process", return_value=None),
            patch("agent.project_execution._port_open", return_value=True),
            patch.object(manager.terminal, "start") as start,
        ):
            with self.assertRaisesRegex(ProjectExecutionError, "occupies the expected port"):
                manager.start(health_timeout_seconds=2)
        start.assert_not_called()

    def test_refuses_to_guess_start_script(self):
        (self.root / "package.json").write_text(json.dumps({
            "dependencies": {"vite": "^6"},
            "scripts": {"test": "vitest"},
        }))

        with self.assertRaisesRegex(ProjectExecutionError, "No safe dev/start/serve script"):
            ProjectExecutionManager._launch_command(
                self.root,
                inspect_project(),
                "powershell",
            )

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell launch test")
    def test_supervises_real_local_node_dev_server_without_duplicate_start(self):
        import shutil
        if not shutil.which("node") or not shutil.which("npm.cmd") or not shutil.which("powershell.exe"):
            self.skipTest("Node.js, npm.cmd, and PowerShell are required.")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        (self.root / "package.json").write_text(json.dumps({
            "name": "niang-project-execution-fixture",
            "scripts": {"dev": f"node server.js --port {port}"},
        }))
        (self.root / "server.js").write_text(
            "const http = require('http');\n"
            "const port = Number(process.argv[process.argv.indexOf('--port') + 1]);\n"
            "http.createServer((_req, res) => { res.end('fixture-ok'); })"
            ".listen(port, '127.0.0.1');\n"
        )
        manager = ProjectExecutionManager(TerminalAgent())
        try:
            with patch.object(manager, "_external_project_process", return_value=None):
                result = manager.start(health_timeout_seconds=10)
                duplicate = manager.start(health_timeout_seconds=10)
            self.assertEqual(result["status"], "healthy")
            self.assertEqual(duplicate["status"], "already_running")
            self.assertEqual(result["process_id"], duplicate["process_id"])
            self.assertEqual(result["url"], f"http://127.0.0.1:{port}/")
            self.assertTrue(manager.is_authorized_preview_url(result["url"]))
            self.assertFalse(
                manager.is_authorized_preview_url(f"http://127.0.0.1:{port + 1}/")
            )
            manager.stop(result["process_id"])
            self.assertEqual(
                json.loads(manager.terminal.status(result["process_id"]))["state"],
                "exited",
            )
            self.assertFalse(manager.is_authorized_preview_url(result["url"]))
        finally:
            for entry in manager._projects.values():
                manager.terminal.stop(entry["process_id"])


if __name__ == "__main__":
    unittest.main()

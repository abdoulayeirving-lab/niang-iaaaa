import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import workspace_tools


class WorkspaceToolTests(unittest.TestCase):
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

    def test_workspace_defaults_to_home_workspace_when_not_configured(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.dict(os.environ, {"NIANG_IA_WORKSPACE_ROOT": ""}, clear=False):
                with patch.object(Path, "home", return_value=Path(home)):
                    workspace_tools.list_files()
                    self.assertTrue((Path(home) / "NIANG_IA_Workspace").is_dir())

    def test_read_write_search_and_listing_stay_within_workspace(self):
        workspace_tools.write_file("src/hello.py", "print('hello')\n")
        self.assertEqual(workspace_tools.read_file("src/hello.py"), "print('hello')\n")
        self.assertIn("src/hello.py:1: print('hello')", workspace_tools.search_text("hello"))
        self.assertIn("src/hello.py", workspace_tools.list_files())

    def test_edit_replaces_only_the_expected_number_of_exact_matches(self):
        workspace_tools.write_file("src/hello.py", "value = 1\nvalue = 1\n")

        result = workspace_tools.edit_file(
            "src/hello.py",
            "value = 1",
            "value = 2",
            expected_occurrences=2,
        )

        self.assertIn("Edited 2 occurrence(s)", result)
        self.assertEqual(
            workspace_tools.read_file("src/hello.py"),
            "value = 2\nvalue = 2\n",
        )

    def test_edit_refuses_unexpected_match_count_without_changing_file(self):
        workspace_tools.write_file("src/hello.py", "value = 1\nvalue = 1\n")

        with self.assertRaisesRegex(workspace_tools.WorkspaceError, "file was not changed"):
            workspace_tools.edit_file("src/hello.py", "value = 1", "value = 3")

        self.assertEqual(
            workspace_tools.read_file("src/hello.py"),
            "value = 1\nvalue = 1\n",
        )

    def test_edit_rejects_empty_match_and_out_of_scope_paths(self):
        workspace_tools.write_file("src/hello.py", "value = 1\n")
        for path, find in (("src/hello.py", ""), ("..\\outside.py", "value = 1")):
            with self.subTest(path=path), self.assertRaises(workspace_tools.WorkspaceError):
                workspace_tools.edit_file(path, find, "value = 2")

    def test_apply_patch_updates_multiple_files_after_context_validation(self):
        workspace_tools.write_file("src/app.py", "def answer():\n    return 41\n")
        workspace_tools.write_file("tests/test_app.py", "assert answer() == 41\n")
        patch = (
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1,2 +1,2 @@\n"
            " def answer():\n"
            "-    return 41\n"
            "+    return 42\n"
            "--- a/tests/test_app.py\n"
            "+++ b/tests/test_app.py\n"
            "@@ -1 +1 @@\n"
            "-assert answer() == 41\n"
            "+assert answer() == 42\n"
        )

        result = workspace_tools.apply_patch(patch)

        self.assertIn("Applied verified patch to 2 file(s)", result)
        self.assertIn("return 42", workspace_tools.read_file("src/app.py"))
        self.assertIn("== 42", workspace_tools.read_file("tests/test_app.py"))

    def test_apply_patch_validates_all_files_before_writing_any(self):
        workspace_tools.write_file("src/app.py", "value = 1\n")
        workspace_tools.write_file("src/test.py", "value = 9\n")
        patch = (
            "--- a/src/app.py\n"
            "+++ b/src/app.py\n"
            "@@ -1 +1 @@\n"
            "-value = 1\n"
            "+value = 2\n"
            "--- a/src/test.py\n"
            "+++ b/src/test.py\n"
            "@@ -1 +1 @@\n"
            "-value = 3\n"
            "+value = 4\n"
        )

        with self.assertRaisesRegex(workspace_tools.WorkspaceError, "context does not match"):
            workspace_tools.apply_patch(patch)

        self.assertEqual(workspace_tools.read_file("src/app.py"), "value = 1\n")
        self.assertEqual(workspace_tools.read_file("src/test.py"), "value = 9\n")

    def test_apply_patch_rejects_unsafe_paths_and_file_deletions(self):
        for old_path, new_path in (
            ("../outside.py", "../outside.py"),
            ("src/app.py", "src/renamed.py"),
            ("/dev/null", "src/new.py"),
        ):
            patch = (
                f"--- a/{old_path}\n"
                f"+++ b/{new_path}\n"
                "@@ -1 +1 @@\n-old\n+new\n"
            )
            with self.subTest(old_path=old_path, new_path=new_path), self.assertRaises(
                workspace_tools.WorkspaceError
            ):
                workspace_tools.apply_patch(patch)

    def test_rejects_absolute_traversal_and_credential_paths(self):
        outside = self.root.parent / "outside.txt"
        for path in (str(outside), "..\\outside.txt", "config/api_keys.json", ".env"):
            with self.subTest(path=path), self.assertRaises(workspace_tools.WorkspaceError):
                workspace_tools.write_file(path, "not allowed")

    def test_rejects_symbolic_links_and_windows_junctions(self):
        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir()
        (outside / "fictional.txt").write_text("fictional", encoding="utf-8")
        link = self.root / "symbolic-link.txt"
        junction = self.root / "junction"
        try:
            try:
                os.symlink(outside / "fictional.txt", link)
            except OSError as exc:
                self.skipTest(f"Symbolic links are unavailable in this Windows environment: {exc}")

            with self.assertRaises(workspace_tools.WorkspaceError):
                workspace_tools.read_file("symbolic-link.txt", workspace_root=self.root)

            result = subprocess.run(
                [
                    os.environ.get("COMSPEC", "cmd.exe"),
                    "/d",
                    "/c",
                    "mklink",
                    "/J",
                    str(junction),
                    str(outside),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(junction.is_junction())
            with self.assertRaises(workspace_tools.WorkspaceError):
                workspace_tools._workspace_root(junction)
            from niang_ia.integrations.cline.cline_config import ClineConfig
            with self.assertRaises(ValueError):
                ClineConfig(junction)
            for operation in (
                lambda: workspace_tools.read_file("junction/fictional.txt", workspace_root=self.root),
                lambda: workspace_tools.write_file("junction/new.txt", "fictional", workspace_root=self.root),
                lambda: workspace_tools.list_files("junction", workspace_root=self.root),
            ):
                with self.assertRaises(workspace_tools.WorkspaceError):
                    operation()
        finally:
            if junction.exists():
                os.rmdir(junction)
            if outside.exists():
                import shutil
                shutil.rmtree(outside)

    def test_rejects_hardlinked_file_aliases(self):
        outside = self.root.parent / f"{self.root.name}-outside.txt"
        outside.write_text("fictional", encoding="utf-8")
        alias = self.root / "hardlink.txt"
        try:
            os.link(outside, alias)
            with self.assertRaisesRegex(workspace_tools.WorkspaceError, "hard links"):
                workspace_tools.read_file("hardlink.txt", workspace_root=self.root)
        finally:
            alias.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)

    def test_skips_credentials_and_environment_files_from_listing(self):
        (self.root / "api_keys.json").write_text('{"api_key":"not for the model"}')
        (self.root / ".env.local").write_text("TOKEN=private")
        (self.root / "safe.txt").write_text("safe")

        listing = workspace_tools.list_files()

        self.assertIn("safe.txt", listing)
        self.assertNotIn("api_keys.json", listing)
        self.assertNotIn(".env.local", listing)

    def test_rejects_binary_and_oversized_files(self):
        binary = self.root / "binary.dat"
        binary.write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(workspace_tools.WorkspaceError, "UTF-8"):
            workspace_tools.read_file("binary.dat")

        oversized = self.root / "large.txt"
        oversized.write_bytes(b"x" * (workspace_tools.MAX_TEXT_BYTES + 1))
        with self.assertRaisesRegex(workspace_tools.WorkspaceError, "larger"):
            workspace_tools.read_file("large.txt")

    def test_run_check_uses_only_fixed_commands_without_a_shell(self):
        with patch.object(workspace_tools.shutil, "which", return_value="C:\\tools\\git.exe"):
            with patch.object(
                workspace_tools.subprocess,
                "Popen",
                return_value=type("Process", (), {
                    "returncode": 0,
                    "pid": 99999999,
                    "communicate": lambda self, timeout=None: ("clean", ""),
                })(),
            ) as popen:
                result = workspace_tools.run_check("git-status")

        self.assertIn("Check git-status passed", result)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["C:\\tools\\git.exe", "status", "--short"])
        self.assertFalse(kwargs["shell"])
        self.assertEqual(Path(kwargs["cwd"]), self.root)

        with self.assertRaisesRegex(workspace_tools.WorkspaceError, "Unsupported check"):
            workspace_tools.run_check("python -c import os")

    def test_check_environment_does_not_forward_api_keys(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "secret-value"}):
            with patch.object(workspace_tools.shutil, "which", return_value="C:\\tools\\git.exe"):
                with patch.object(
                    workspace_tools.subprocess,
                    "Popen",
                    return_value=type("Process", (), {
                        "returncode": 0,
                        "pid": 99999999,
                        "communicate": lambda self, timeout=None: ("", ""),
                    })(),
                ) as popen:
                    workspace_tools.run_check("git-status")

        self.assertNotIn("GEMINI_API_KEY", popen.call_args.kwargs["env"])

    def test_cancelled_check_terminates_its_child_process_tree(self):
        pid_file = self.root / "child.pid"
        marker = self.root.parent / f"{self.root.name}-child-marker.txt"
        child_code = (
            "import os,time; from pathlib import Path; "
            f"Path({str(pid_file)!r}).write_text(str(os.getpid()), encoding='utf-8'); "
            "time.sleep(20); "
            f"Path({str(marker)!r}).write_text('fictional child ran', encoding='utf-8')"
        )
        parent_code = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
            "time.sleep(20)"
        )
        cancel_flag = threading.Event()
        timer = threading.Timer(0.5, cancel_flag.set)
        timer.start()
        child_pid = None
        try:
            with self.assertRaisesRegex(workspace_tools.WorkspaceError, "cancelled"):
                workspace_tools._run_workspace_process(
                    [sys.executable, "-c", parent_code],
                    root=self.root,
                    timeout=30,
                    cancel_flag=cancel_flag,
                )
            self.assertTrue(pid_file.exists(), "The fixture child did not start.")
            child_pid = int(pid_file.read_text(encoding="utf-8"))
            self.assertFalse(marker.exists(), "A child process continued after cancellation.")
            import psutil
            with self.assertRaises(psutil.NoSuchProcess):
                psutil.Process(child_pid).status()
        finally:
            timer.cancel()
            if child_pid is not None:
                try:
                    import psutil
                    psutil.Process(child_pid).kill()
                except ImportError:
                    pass
                except psutil.NoSuchProcess:
                    pass
            marker.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()

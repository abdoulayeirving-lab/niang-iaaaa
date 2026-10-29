import os
import tempfile
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

    def test_workspace_must_be_explicitly_configured(self):
        with patch.dict(os.environ, {"NIANG_IA_WORKSPACE_ROOT": ""}):
            with self.assertRaisesRegex(workspace_tools.WorkspaceError, "disabled"):
                workspace_tools.list_files()

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
                "run",
                return_value=type("Completed", (), {
                    "returncode": 0, "stdout": "clean", "stderr": "",
                })(),
            ) as run:
                result = workspace_tools.run_check("git-status")

        self.assertIn("Check git-status passed", result)
        args, kwargs = run.call_args
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
                    "run",
                    return_value=type("Completed", (), {
                        "returncode": 0, "stdout": "", "stderr": "",
                    })(),
                ) as run:
                    workspace_tools.run_check("git-status")

        self.assertNotIn("GEMINI_API_KEY", run.call_args.kwargs["env"])


if __name__ == "__main__":
    unittest.main()

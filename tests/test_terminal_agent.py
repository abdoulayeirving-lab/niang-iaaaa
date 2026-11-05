import json
import os
import shutil
import tempfile
import threading
import time
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent.terminal_agent import TerminalAgent, TerminalAgentError, command_risk


class TerminalAgentTests(unittest.TestCase):
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
        self.agent = TerminalAgent()

    def _stop_process_if_running(self, process_id):
        try:
            if json.loads(self.agent.status(process_id))["state"] == "running":
                self.agent.stop(process_id, grace_seconds=0.1)
        except TerminalAgentError:
            pass

    def test_command_risk_distinguishes_project_install_and_destructive_commands(self):
        self.assertEqual(command_risk("python -m pytest"), "project-code-execution")
        self.assertEqual(command_risk("npm install"), "dependency-or-system-change")
        self.assertEqual(command_risk("Remove-Item important.txt"), "destructive-or-external")

    def test_rejects_unknown_shell_and_out_of_workspace_cwd_before_starting_process(self):
        with patch("agent.terminal_agent.subprocess.Popen") as popen:
            with self.assertRaisesRegex(TerminalAgentError, "Shell must"):
                self.agent.start("cmd", "echo unsafe")
            with self.assertRaisesRegex(TerminalAgentError, "relative path"):
                self.agent.start("powershell", "Write-Output unsafe", cwd="..")
        popen.assert_not_called()

    def test_builds_bash_argv_without_using_subprocess_shell(self):
        with patch("agent.terminal_agent.shutil.which", return_value="C:\\tools\\bash.exe"):
            argv = self.agent._command_argv("bash", "printf ready")

        self.assertEqual(
            argv,
            ["C:\\tools\\bash.exe", "--noprofile", "--norc", "-lc", "printf ready"],
        )

    def test_executes_available_shell_and_captures_stdout_and_stderr(self):
        if os.name == "nt" and shutil.which("powershell.exe"):
            shell = "powershell"
            command = "[Console]::Out.WriteLine('stdout marker'); [Console]::Error.WriteLine('stderr marker')"
        elif shutil.which("bash"):
            shell = "bash"
            command = "printf 'stdout marker\\n'; printf 'stderr marker\\n' >&2"
        else:
            self.skipTest("Neither supported shell is installed.")

        result = json.loads(self.agent.run(shell, command, timeout_seconds=10))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("stdout marker", result["stdout"])
        self.assertIn("stderr marker", result["stderr"])

    def test_managed_process_status_logs_and_stop_target_only_its_process(self):
        if os.name == "nt" and shutil.which("powershell.exe"):
            shell, command = "powershell", "Write-Output ready; Start-Sleep -Seconds 30"
        elif shutil.which("bash"):
            shell, command = "bash", "printf 'ready\\n'; sleep 30"
        else:
            self.skipTest("Neither supported shell is installed.")

        started = json.loads(self.agent.start(shell, command))
        process_id = started["process_id"]
        self.addCleanup(self._stop_process_if_running, process_id)
        self.assertEqual(json.loads(self.agent.status(process_id))["state"], "running")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if "ready" in json.loads(self.agent.logs(process_id))["stdout"]:
                break
            time.sleep(0.02)
        self.assertIn("ready", json.loads(self.agent.logs(process_id))["stdout"])

        stopped = json.loads(self.agent.stop(process_id, grace_seconds=0.1))

        self.assertEqual(stopped["state"], "stopped")
        self.assertEqual(json.loads(self.agent.status(process_id))["state"], "exited")
        self.assertEqual(json.loads(self.agent.logs(process_id))["process_id"], process_id)

    def test_foreground_command_timeout_stops_the_process_and_is_explicit(self):
        if os.name == "nt" and shutil.which("powershell.exe"):
            shell, command = "powershell", "Start-Sleep -Seconds 30"
        elif shutil.which("bash"):
            shell, command = "bash", "sleep 30"
        else:
            self.skipTest("Neither supported shell is installed.")

        with self.assertRaisesRegex(TerminalAgentError, "timeout"):
            self.agent.run(shell, command, timeout_seconds=1)

    def test_cancellation_before_process_start_does_not_dispatch(self):
        cancel = threading.Event()
        cancel.set()
        with patch("agent.terminal_agent.subprocess.Popen") as popen:
            with self.assertRaisesRegex(TerminalAgentError, "cancelled before it started"):
                self.agent.run(
                    "powershell",
                    "Write-Output should-not-run",
                    cancel_event=cancel,
                )
        popen.assert_not_called()

    def test_direct_managed_program_keeps_the_application_pid_and_streams(self):
        started = json.loads(self.agent.start_program(
            [sys.executable, "-u", "-c", "print('direct-ready')"],
            cwd=".",
            process_identity="direct-program-fixture",
        ))
        process_id = started["process_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status = json.loads(self.agent.status(process_id))
            if status["state"] == "exited":
                break
            time.sleep(0.02)

        self.assertEqual(status["pid"], started["pid"])
        self.assertEqual(status["state"], "exited")
        self.assertEqual(status["exit_code"], 0)
        self.assertIn("direct-ready", json.loads(self.agent.logs(process_id))["stdout"])
        self.assertIsNone(self.agent.find_running(".", "different-program"))

    def test_stop_tolerates_process_exit_during_descendant_enumeration(self):
        import psutil

        process = Mock(pid=12345)
        process.poll.side_effect = [None, 0]
        process.send_signal.side_effect = ProcessLookupError()
        process.terminate.side_effect = ProcessLookupError()
        record = SimpleNamespace(process=process, readers=[])
        with patch("psutil.Process", side_effect=psutil.NoSuchProcess(12345)):
            self.assertTrue(self.agent._stop_record(record))

    def test_nonzero_command_exit_is_returned_as_failure_with_both_streams(self):
        if os.name == "nt" and shutil.which("powershell.exe"):
            shell, command = "powershell", "[Console]::Error.WriteLine('failed'); exit 7"
        elif shutil.which("bash"):
            shell, command = "bash", "printf 'failed\\n' >&2; exit 7"
        else:
            self.skipTest("Neither supported shell is installed.")

        result = json.loads(self.agent.run(shell, command, timeout_seconds=10))

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 7)
        self.assertIn("failed", result["stderr"])

    def test_obvious_secret_output_is_redacted(self):
        if os.name == "nt" and shutil.which("powershell.exe"):
            shell, command = "powershell", "Write-Output 'API_KEY=abcdefghijk123456'"
        elif shutil.which("bash"):
            shell, command = "bash", "printf 'API_KEY=abcdefghijk123456\\n'"
        else:
            self.skipTest("Neither supported shell is installed.")

        result = json.loads(self.agent.run(shell, command, timeout_seconds=10))

        self.assertNotIn("abcdefghijk123456", result["stdout"])
        self.assertIn("[output redacted", result["stdout"])


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from actions import windows_process


class _FakeProcess:
    def __init__(self):
        self.returncode = None
        self.stdout = None
        self.stderr = None
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def communicate(self, timeout=None):
        return "", ""


class _CancelOnCheck:
    def __init__(self):
        self.checks = 0

    def is_set(self):
        self.checks += 1
        return self.checks > 1


class WindowsProcessTests(unittest.TestCase):
    def test_cancellation_terminates_only_the_started_child_process(self):
        process = _FakeProcess()
        with patch.object(windows_process.subprocess, "Popen", return_value=process) as popen:
            with self.assertRaises(windows_process.WindowsProcessCancelled):
                windows_process.run_windows_process(
                    ["C:\\Windows\\System32\\example.exe", "/readonly"],
                    30,
                    _CancelOnCheck(),
                )
        self.assertTrue(process.killed)
        popen.assert_called_once()
        self.assertEqual(popen.call_args.args[0], [
            "C:\\Windows\\System32\\example.exe",
            "/readonly",
        ])
        self.assertNotIn("shell", popen.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()

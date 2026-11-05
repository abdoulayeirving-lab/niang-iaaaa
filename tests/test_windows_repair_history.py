import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import windows_repair_history


class WindowsRepairHistoryTests(unittest.TestCase):
    def test_history_is_saved_without_personal_output(self):
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "repair-history.json"
            with patch.object(windows_repair_history, "_history_path", return_value=history_path):
                entry = windows_repair_history.record_repair_event(
                    action="flush_dns",
                    mission_id="mission-test-123",
                    diagnostic_associated="2026-11-02T00:00:00+00:00",
                    problem="DNS resolver cache issue",
                    authorization="approved",
                    command="ipconfig.exe /flushdns",
                    permission_detected="elevated",
                    result={
                        "status": "completed",
                        "return_code": 0,
                        "permission_detected": "elevated",
                        "verification": {"status": "verified", "verified": True},
                    },
                )
                history = windows_repair_history.read_repair_history()
        self.assertEqual(history[-1]["proposed_repair"], "flush_dns")
        self.assertEqual(entry["result_status"], "completed")
        self.assertEqual(entry["mission_id"], "mission-test-123")
        self.assertEqual(entry["command_fixed"], "ipconfig.exe /flushdns")
        self.assertEqual(entry["permission_detected"], "elevated")
        self.assertEqual(entry["return_code"], 0)
        self.assertEqual(entry["final_status"], "success")
        self.assertNotIn("password", str(history).casefold())

    def test_history_preserves_interruption_and_no_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            history_path = Path(directory) / "repair-history.json"
            with patch.object(windows_repair_history, "_history_path", return_value=history_path):
                windows_repair_history.record_repair_event(
                    action="sfc_scannow",
                    authorization="approved",
                    result={"status": "cancelled"},
                    interrupted=True,
                    rollback_performed=False,
                )
                history = windows_repair_history.read_repair_history()
        self.assertTrue(history[-1]["interrupted"])
        self.assertFalse(history[-1]["rollback_performed"])

    def test_history_handles_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                windows_repair_history,
                "_history_path",
                return_value=Path(directory) / "missing.json",
            ):
                self.assertEqual(windows_repair_history.read_repair_history(), [])

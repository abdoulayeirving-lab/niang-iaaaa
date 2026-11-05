import threading
import unittest
from unittest.mock import patch

from actions import windows_repair


class WindowsRepairTests(unittest.TestCase):
    def test_explicit_approval_is_required_before_any_command(self):
        with patch.object(windows_repair, "_run") as run:
            result = windows_repair.perform_repair("flush_dns")
        self.assertEqual(result["status"], "blocked")
        run.assert_not_called()

    def test_unlisted_operation_is_rejected(self):
        with patch.object(windows_repair, "_run") as run:
            with self.assertRaises(ValueError):
                windows_repair.perform_repair("powershell Remove-Item", approved=True)
        run.assert_not_called()

    def test_cancelled_repair_does_not_start_a_command(self):
        cancel_event = threading.Event()
        cancel_event.set()
        with (
            patch.object(windows_repair.platform, "system", return_value="Windows"),
            patch.object(windows_repair, "_run") as run,
        ):
            with self.assertRaises(windows_repair.RepairCancelled):
                windows_repair.perform_repair(
                    "flush_dns",
                    approved=True,
                    cancel_event=cancel_event,
                )
        run.assert_not_called()

    def test_system_repair_refuses_to_request_elevation(self):
        with (
            patch.object(windows_repair.platform, "system", return_value="Windows"),
            patch.object(windows_repair, "_is_elevated", return_value=False),
            patch.object(windows_repair, "_create_restore_point") as restore,
            patch.object(windows_repair, "_run") as run,
        ):
            result = windows_repair.perform_repair("sfc_scannow", approved=True)
        self.assertEqual(result["status"], "blocked_by_permissions")
        restore.assert_not_called()
        run.assert_not_called()

    def test_dns_repair_refuses_without_elevation_before_process_creation(self):
        with (
            patch.object(windows_repair.platform, "system", return_value="Windows"),
            patch.object(windows_repair, "_is_elevated", return_value=False),
            patch.object(windows_repair, "_run") as run,
        ):
            result = windows_repair.perform_repair("flush_dns", approved=True)
        self.assertEqual(result["status"], "blocked_by_permissions")
        self.assertIn("Run as administrator", result["instruction"])
        run.assert_not_called()

    def test_system_repair_does_not_run_if_restore_point_cannot_be_verified(self):
        with (
            patch.object(windows_repair.platform, "system", return_value="Windows"),
            patch.object(windows_repair, "_is_elevated", return_value=True),
            patch.object(windows_repair, "_create_restore_point", return_value={
                "created": False,
                "detail": "System protection unavailable",
            }),
            patch.object(windows_repair, "_run") as run,
        ):
            result = windows_repair.perform_repair("dism_restore_health", approved=True)
        self.assertEqual(result["status"], "blocked")
        run.assert_not_called()

    def test_dns_repair_uses_fixed_command_and_reports_verification(self):
        completed = windows_repair.subprocess.CompletedProcess(
            ["ipconfig.exe", "/flushdns"],
            0,
            "Successfully flushed the DNS Resolver Cache.",
            "",
        )
        with (
            patch.object(windows_repair.platform, "system", return_value="Windows"),
            patch.object(windows_repair, "_is_elevated", return_value=True),
            patch.object(windows_repair, "_dns_baseline", return_value={
                "resolution_successful": True,
                "connectivity_successful": True,
            }),
            patch.object(windows_repair, "_verification", return_value={
                "verified": True,
                "status": "verified",
                "external_resolution": True,
            }),
            patch.object(windows_repair, "_run", return_value=completed) as run,
        ):
            result = windows_repair.perform_repair("flush_dns", approved=True)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["verification"]["verified"])
        run.assert_called_once_with(
            ["ipconfig.exe", "/flushdns"],
            30,
            None,
        )

    def test_dns_verification_unavailable_when_both_cache_tools_fail(self):
        with (
            patch.object(windows_repair.socket, "getaddrinfo", return_value=[1]),
            patch.object(
                windows_repair,
                "_run",
                side_effect=RuntimeError("DNS cache tool unavailable"),
            ),
        ):
            verification = windows_repair._verification("flush_dns")
        self.assertFalse(verification["verified"])
        self.assertEqual(verification["status"], "verification_unavailable")

    def test_dns_nonzero_return_code_is_an_error(self):
        completed = windows_repair.subprocess.CompletedProcess(
            ["ipconfig.exe", "/flushdns"], 1, "", "Operation requires elevation."
        )
        with (
            patch.object(windows_repair.platform, "system", return_value="Windows"),
            patch.object(windows_repair, "_is_elevated", return_value=True),
            patch.object(windows_repair, "_dns_baseline", return_value={"resolution_successful": True}),
            patch.object(windows_repair, "_run", return_value=completed),
        ):
            result = windows_repair.perform_repair("flush_dns", approved=True)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["return_code"], 1)

    def test_dns_timeout_is_reported_without_success(self):
        with (
            patch.object(windows_repair.platform, "system", return_value="Windows"),
            patch.object(windows_repair, "_is_elevated", return_value=True),
            patch.object(windows_repair, "_dns_baseline", return_value={"resolution_successful": True}),
            patch.object(
                windows_repair,
                "_run",
                side_effect=windows_repair.subprocess.TimeoutExpired("ipconfig.exe", 30),
            ),
        ):
            result = windows_repair.perform_repair("flush_dns", approved=True)
        self.assertEqual(result["status"], "timeout")

    def test_system_repair_creates_restore_point_and_verifies_sfc(self):
        results = [
            windows_repair.subprocess.CompletedProcess(
                ["sfc.exe", "/scannow"], 0, "Repair completed.", ""
            ),
            windows_repair.subprocess.CompletedProcess(
                ["sfc.exe", "/verifyonly"],
                0,
                "Windows Resource Protection did not find any integrity violations.",
                "",
            ),
        ]
        with (
            patch.object(windows_repair.platform, "system", return_value="Windows"),
            patch.object(windows_repair, "_is_elevated", return_value=True),
            patch.object(windows_repair, "_create_restore_point", return_value={
                "created": True,
                "sequence_number": 1,
            }),
            patch.object(windows_repair, "_run", side_effect=results) as run,
        ):
            result = windows_repair.perform_repair("sfc_scannow", approved=True)
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["verification"]["verified"])
        self.assertEqual(run.call_count, 2)

    def test_sfc_verification_recognizes_french_healthy_output(self):
        completed = windows_repair.subprocess.CompletedProcess(
            ["sfc.exe", "/verifyonly"],
            0,
            "La Protection des ressources Windows n’a détecté aucune violation d’intégrité.",
            "",
        )
        with patch.object(windows_repair, "_run", return_value=completed):
            verification = windows_repair._verification("sfc_scannow")
        self.assertTrue(verification["verified"])
        self.assertEqual(verification["status"], "healthy")

    def test_dism_verification_recognizes_french_healthy_output(self):
        completed = windows_repair.subprocess.CompletedProcess(
            ["DISM.exe", "/Online", "/Cleanup-Image", "/CheckHealth"],
            0,
            "Aucune corruption du magasin de composants n’a été détectée.",
            "",
        )
        with patch.object(windows_repair, "_run", return_value=completed):
            verification = windows_repair._verification("dism_restore_health")
        self.assertTrue(verification["verified"])
        self.assertEqual(verification["status"], "healthy")


if __name__ == "__main__":
    unittest.main()

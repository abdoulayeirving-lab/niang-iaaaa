import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import windows_diagnostics


class WindowsDiagnosticsTests(unittest.TestCase):
    def test_performance_monitor_requires_imported_time_source(self):
        import time

        self.assertIs(windows_diagnostics.time, time)

    def test_performance_monitor_cancellation_is_immediate(self):
        cancel_event = threading.Event()
        cancel_event.set()
        details, findings, interrupted = windows_diagnostics._monitor_performance(
            duration_seconds=10,
            sample_interval_seconds=1,
            cancel_event=cancel_event,
        )
        self.assertTrue(interrupted)
        self.assertEqual(details["samples"], [])
        self.assertEqual(findings, [])

    def test_unknown_category_is_rejected_before_collection(self):
        with patch.object(windows_diagnostics, "_read_powershell_category") as powershell:
            with self.assertRaises(ValueError):
                windows_diagnostics.run_diagnostic("arbitrary_command", record_history=False)
        powershell.assert_not_called()

    def test_cancelled_overview_does_not_start_a_check(self):
        cancel_event = threading.Event()
        cancel_event.set()
        with patch.object(windows_diagnostics, "_collect_performance") as collect:
            with self.assertRaises(windows_diagnostics.DiagnosticCancelled):
                windows_diagnostics.run_diagnostic(
                    "overview",
                    record_history=False,
                    cancel_event=cancel_event,
                )
        collect.assert_not_called()

    def test_cancellation_during_performance_collection_is_not_reported_as_partial(self):
        cancel_event = threading.Event()
        with patch.object(
            windows_diagnostics,
            "_collect_performance",
            side_effect=windows_diagnostics.DiagnosticCancelled("cancelled"),
        ):
            with self.assertRaises(windows_diagnostics.DiagnosticCancelled):
                windows_diagnostics.run_diagnostic(
                    "performance",
                    record_history=False,
                    cancel_event=cancel_event,
                )

    def test_driver_report_flags_problem_devices_without_serial_numbers(self):
        payload = {
            "GPUs": [{"Name": "Example GPU", "DriverVersion": "1.2", "Status": "OK"}],
            "ProblemDevices": [{
                "FriendlyName": "Example device",
                "Status": "Error",
                "Problem": 10,
            }],
            "PhysicalDisks": [{
                "Name": "Example disk",
                "HealthStatus": "Warning",
                "OperationalStatus": "OK",
                "SizeBytes": 1024,
                "TemperatureC": None,
            }],
        }
        with (
            patch.object(windows_diagnostics, "platform") as platform_info,
            patch.object(windows_diagnostics, "_powershell", return_value=payload),
            patch.object(windows_diagnostics, "_store_history"),
        ):
            platform_info.platform.return_value = "Windows-Test"
            platform_info.system.return_value = "Windows"
            report = windows_diagnostics.run_diagnostic("drivers")

        self.assertEqual(report["category"], "drivers")
        self.assertTrue(any("Example device" in item["problem"] for item in report["findings"]))
        self.assertTrue(any("Warning" in item["problem"] for item in report["findings"]))
        serialized = json.dumps(report)
        self.assertNotIn("SerialNumber", serialized)
        self.assertNotIn("PNPDeviceID", serialized)

    def test_system_file_checks_are_read_only(self):
        commands = []

        def fake_run(command, timeout, cancel_event=None):
            commands.append(command)
            output = (
                "No component store corruption detected."
                if Path(command[0]).name.casefold() == "dism.exe"
                else "Windows Resource Protection did not find any integrity violations."
            )
            return windows_diagnostics.subprocess.CompletedProcess(
                command,
                0,
                output,
                "",
            )

        with (
            patch.object(windows_diagnostics, "platform") as platform_info,
            patch.object(windows_diagnostics, "_run_process", side_effect=fake_run),
        ):
            platform_info.system.return_value = "Windows"
            checks, findings = windows_diagnostics._run_integrity_checks()

        self.assertEqual(len(checks), 2)
        self.assertEqual(findings, [])
        self.assertEqual(
            [[Path(command[0]).name, *command[1:]] for command in commands],
            [
                ["DISM.exe", "/Online", "/Cleanup-Image", "/ScanHealth"],
                ["sfc.exe", "/verifyonly"],
            ],
        )
        self.assertNotIn("/RestoreHealth", str(commands))
        self.assertNotIn("/scannow", str(commands))

    def test_system_file_findings_are_reported_without_repair(self):
        def fake_run(command, timeout, cancel_event=None):
            output = (
                "The component store is repairable."
                if Path(command[0]).name.casefold() == "dism.exe"
                else "Windows Resource Protection found integrity violations."
            )
            return windows_diagnostics.subprocess.CompletedProcess(command, 0, output, "")

        with (
            patch.object(windows_diagnostics, "platform") as platform_info,
            patch.object(windows_diagnostics, "_run_process", side_effect=fake_run),
        ):
            platform_info.system.return_value = "Windows"
            checks, findings = windows_diagnostics._run_integrity_checks()

        self.assertEqual([item["status"] for item in checks], ["issues_found", "issues_found"])
        self.assertEqual(len(findings), 2)
        self.assertTrue(all(item["authorization_required"] for item in findings))

    def test_cancellation_during_performance_temperature_probe_propagates(self):
        with (
            patch.object(windows_diagnostics, "psutil") as psutil_module,
            patch.object(windows_diagnostics.platform, "system", return_value="Windows"),
            patch.object(
                windows_diagnostics,
                "_powershell",
                side_effect=windows_diagnostics.DiagnosticCancelled("cancelled"),
            ),
        ):
            psutil_module.cpu_percent.return_value = 10
            psutil_module.sensors_temperatures.return_value = {}
            with self.assertRaises(windows_diagnostics.DiagnosticCancelled):
                windows_diagnostics._collect_performance(threading.Event())

    def test_overview_keeps_running_each_category_and_records_only_report_summary(self):
        def category_result(category, _cancel_event=None):
            return [windows_diagnostics._check(category, "ok", {}, "test")], []

        with (
            patch.object(windows_diagnostics, "_collect_performance", return_value=(
                [windows_diagnostics._check("Performance", "ok", {}, "test")],
                [],
            )),
            patch.object(windows_diagnostics, "_read_powershell_category", side_effect=category_result) as ps,
            patch.object(windows_diagnostics, "_run_integrity_checks", return_value=(
                [windows_diagnostics._check("System files", "ok", "verified", "test")],
                [],
            )),
            patch.object(windows_diagnostics, "_store_history") as store,
        ):
            report = windows_diagnostics.run_diagnostic("overview")

        self.assertEqual(len(report["checks"]), 7)
        self.assertEqual(ps.call_count, 5)
        store.assert_called_once_with(report)

    def test_history_contains_only_bounded_summary_fields(self):
        report = {
            "timestamp_utc": "2026-01-01T00:00:00+00:00",
            "category": "overview",
            "status": "ok",
            "findings": [{
                "severity": "medium",
                "problem": "A test issue",
                "likely_cause": "private cause",
            }],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "history.json"
            with patch.object(windows_diagnostics, "_history_path", return_value=path):
                windows_diagnostics._store_history(report)
            saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved[0]["finding_count"], 1)
        self.assertNotIn("likely_cause", saved[0]["findings"][0])

    def test_event_log_uses_24_hours_critical_error_and_100_limit(self):
            captured = {}

            def fake_powershell(script, timeout_seconds=None, cancel_event=None):
                captured["script"] = script
                captured["timeout"] = timeout_seconds
                return {
                    "Events": [],
                    "WindowDays": 1,
                    "PageDays": 1,
                    "PageSize": 100,
                    "MaximumResults": 100,
                    "Truncated": False,
                    "QueryError": None,
                    "QueryStatus": "ok",
                }

            with patch.object(windows_diagnostics, "_powershell", side_effect=fake_powershell):
                result = windows_diagnostics._read_event_log("System")

            self.assertEqual(result["status"], "ok")
            self.assertIn("AddHours(-$windowHours)", captured["script"])
            self.assertIn("Level=1,2", captured["script"])
            self.assertIn("-MaxEvents $maxResults", captured["script"])
            self.assertLessEqual(captured["timeout"], 600)


if __name__ == "__main__":
    unittest.main()

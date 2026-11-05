import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import windows_repair_analysis


class WindowsRepairAnalysisTests(unittest.TestCase):
    def test_dns_finding_is_mapped_to_flush_dns(self):
        report = {
            "category": "network",
            "findings": [{
                "problem": "DNS resolver cache may be stale.",
                "severity": "medium",
                "likely_cause": "Resolver cache state.",
                "recommended_solution": "Flush DNS cache.",
            }],
        }
        proposals = windows_repair_analysis.analyze_report(report)
        self.assertEqual(len(proposals), 1)
        self.assertEqual(proposals[0]["proposed_repair"], "flush_dns")
        self.assertIn("confidence", proposals[0])

    def test_isolated_suspicion_is_not_confirmed(self):
        report = {
            "findings": [{
                "problem": "DNS resolver cache may be stale.",
                "severity": "low",
            }],
        }
        with patch.object(windows_repair_analysis, "_read_reports", return_value=[]):
            proposals = windows_repair_analysis.analyze_report(report)
        self.assertEqual(proposals[0]["confidence"], "suspicion")
        self.assertFalse(proposals[0]["confidence"] == "confirmed")

    def test_recurring_integrity_finding_is_probable(self):
        report = {
            "findings": [{
                "problem": "SFC integrity violation detected.",
                "severity": "high",
            }],
        }
        repeated = {
            "findings": [{
                "problem": "SFC integrity violation detected.",
                "severity": "high",
            }],
        }
        with patch.object(
            windows_repair_analysis,
            "_read_reports",
            return_value=[report, repeated],
        ):
            proposals = windows_repair_analysis.analyze_report(report)
        self.assertEqual(proposals[0]["proposed_repair"], "sfc_scannow")
        self.assertGreaterEqual(proposals[0]["recurrence_count"], 2)

    def test_unrelated_event_has_no_forced_repair(self):
        report = {
            "findings": [{
                "problem": "A Bluetooth driver logged a historical error.",
                "severity": "medium",
            }],
        }
        with patch.object(windows_repair_analysis, "_read_reports", return_value=[]):
            proposals = windows_repair_analysis.analyze_report(report)
        self.assertEqual(proposals, [])

    def test_analysis_reads_real_report_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "windows-diagnostic-example.json"
            path.write_text(json.dumps({
                "category": "network",
                "findings": [{"problem": "DNS resolver issue."}],
            }), encoding="utf-8")
            with patch.object(windows_repair_analysis, "_reports_directory", return_value=Path(directory)):
                proposals = windows_repair_analysis.analyze_report({
                    "category": "network",
                    "findings": [{"problem": "DNS resolver issue."}],
                })
        self.assertEqual(proposals[0]["proposed_repair"], "flush_dns")


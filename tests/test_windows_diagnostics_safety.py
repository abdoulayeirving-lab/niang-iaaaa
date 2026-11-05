import io
import unittest
from unittest.mock import patch

import logger
import safety
from agent import executor


class WindowsDiagnosticsSafetyTests(unittest.TestCase):
    def test_diagnostics_and_repairs_require_action_bound_confirmation(self):
        for tool, args in (
            ("windows_diagnostics", {"action": "overview"}),
            ("windows_repair", {"action": "sfc_scannow"}),
        ):
            with self.subTest(tool=tool):
                self.assertEqual(safety.classify(tool, args), safety.Risk.HIGH)
                self.assertTrue(safety.needs_confirmation(tool, args))
                token = safety.issue_confirmation_token(tool, args)
                self.assertFalse(safety.needs_confirmation(
                    tool,
                    args,
                    confirm=True,
                    confirm_token=token,
                ))

    def test_repair_approval_description_names_fixed_operation(self):
        description = safety.describe("windows_repair", {"action": "sfc_scannow"})
        self.assertIn("sfc.exe /scannow", description)
        self.assertIn("restore point", description)
        self.assertIn("already be elevated", description)

    def test_executor_does_not_dispatch_diagnostics_without_approval(self):
        approval = lambda tool, parameters, description: False
        with patch("actions.windows_diagnostics.windows_diagnostics") as diagnostics:
            result = executor._call_tool(
                "windows_diagnostics",
                {"action": "overview"},
                None,
                approval_callback=approval,
            )
        self.assertIn("approval was denied", result)
        diagnostics.assert_not_called()

    def test_executor_does_not_dispatch_repair_without_approval(self):
        approval = lambda tool, parameters, description: False
        with patch("actions.windows_repair.windows_repair") as repair:
            result = executor._call_tool(
                "windows_repair",
                {"action": "sfc_scannow"},
                None,
                approval_callback=approval,
            )
        self.assertIn("approval was denied", result)
        repair.assert_not_called()

    def test_diagnostic_data_is_omitted_from_logs(self):
        output = io.StringIO()
        with patch.object(logger, "log", side_effect=lambda line, level="INFO": output.write(line)):
            logger.log_tool(
                "windows_diagnostics",
                {"action": "overview", "details": "private hardware data"},
                result="private diagnostic result",
            )
            logger.log_tool(
                "windows_repair",
                {"action": "sfc_scannow"},
                result="private repair output",
            )
        self.assertNotIn("private hardware data", output.getvalue())
        self.assertNotIn("private diagnostic result", output.getvalue())
        self.assertNotIn("private repair output", output.getvalue())
        self.assertIn("details=[omitted]", output.getvalue())


if __name__ == "__main__":
    unittest.main()

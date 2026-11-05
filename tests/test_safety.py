"""Tests for safety.py — risk classification, confirmation gate, sanitization.

Run: python -m unittest tests.test_safety -v
"""

import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import safety


class RiskClassificationTest(unittest.TestCase):

    def test_low_risk_read_only(self):
        self.assertEqual(safety.classify("web_search", {}), safety.Risk.LOW)
        self.assertEqual(safety.classify("system_status", {}), safety.Risk.LOW)
        self.assertEqual(safety.classify("set_live_translation", {"action": "enable"}), safety.Risk.LOW)
        self.assertEqual(safety.classify("proactive_suggestions", {"action": "enable"}), safety.Risk.LOW)

    def test_file_delete_is_high(self):
        self.assertEqual(
            safety.classify("file_controller", {"action": "delete", "name": "x.txt"}),
            safety.Risk.HIGH,
        )

    def test_file_read_not_high(self):
        self.assertNotEqual(
            safety.classify("file_controller", {"action": "read", "name": "x.txt"}),
            safety.Risk.HIGH,
        )

    def test_overwriting_files_requires_confirmation(self):
        for action in ("write", "create_file"):
            with self.subTest(action=action):
                args = {"action": action, "path": "documents", "name": "report.txt"}
                self.assertEqual(safety.classify("file_controller", args), safety.Risk.HIGH)
                self.assertTrue(safety.needs_confirmation("file_controller", args))

    def test_sensitive_file_access_requires_confirmation(self):
        for tool, args in (
            ("file_controller", {"action": "read", "path": "home", "name": ".env"}),
            ("file_controller", {"action": "write", "path": r"C:\Users\pc", "name": "api_keys.json"}),
            ("read_document", {"path": "documents/client_secret.json"}),
            ("pdf_qa", {"file_path": "private/signing-key.pem"}),
        ):
            with self.subTest(tool=tool, args=args):
                self.assertEqual(safety.classify(tool, args), safety.Risk.HIGH)
                self.assertTrue(safety.needs_confirmation(tool, args))

    def test_browser_download_links_require_confirmation_when_clicked(self):
        for target in ("Download report", "installer.exe", "archive.zip"):
            with self.subTest(target=target):
                args = {"action": "click", "description": target}
                self.assertEqual(safety.classify("browser_control", args), safety.Risk.HIGH)
                self.assertTrue(safety.needs_confirmation("browser_control", args))

    def test_persistent_browser_session_requires_confirmation(self):
        args = {
            "action": "state",
            "persistent_session_id": "work-profile",
        }
        self.assertEqual(safety.classify("browser_control", args), safety.Risk.HIGH)
        self.assertTrue(safety.needs_confirmation("browser_control", args))

    def test_terminal_is_high(self):
        self.assertEqual(safety.classify("cmd_control", {"command": "dir"}), safety.Risk.HIGH)

    def test_workspace_terminal_commands_and_project_start_require_confirmation(self):
        for tool, args in (
            ("terminal_control", {"action": "run", "command": "python -m pytest"}),
            ("terminal_control", {"action": "start", "command": "npm run dev"}),
            ("project_execution", {"action": "start", "path": "."}),
        ):
            with self.subTest(tool=tool, args=args):
                self.assertEqual(safety.classify(tool, args), safety.Risk.HIGH)
                self.assertTrue(safety.needs_confirmation(tool, args))

        self.assertEqual(
            safety.classify("terminal_control", {"action": "logs", "process_id": "id"}),
            safety.Risk.LOW,
        )
        self.assertEqual(
            safety.classify("project_execution", {"action": "stop", "process_id": "id"}),
            safety.Risk.MEDIUM,
        )

    def test_terminal_confirmation_describes_command_but_audit_sanitization_omits_it(self):
        command = "python -m pytest tests"

        self.assertIn(command, safety.describe(
            "terminal_control",
            {"action": "run", "command": command},
        ))
        self.assertNotIn(
            command,
            str(safety.sanitize("terminal_control", {"action": "run", "command": command})),
        )

    def test_gmail_send_high_read_low(self):
        self.assertEqual(safety.classify("gmail", {"action": "send"}), safety.Risk.HIGH)
        self.assertEqual(safety.classify("gmail", {"action": "read"}), safety.Risk.LOW)

    def test_task_manager_kill_high(self):
        self.assertEqual(safety.classify("task_manager", {"action": "kill"}), safety.Risk.HIGH)

    def test_open_app_medium(self):
        self.assertEqual(safety.classify("open_app", {"app_name": "Chrome"}), safety.Risk.MEDIUM)

    def test_live_camera_requires_confirmation_to_stream(self):
        start = {"action": "start"}
        self.assertEqual(safety.classify("live_camera", start), safety.Risk.HIGH)
        self.assertTrue(safety.needs_confirmation("live_camera", start))
        self.assertIn("webcam frames", safety.describe("live_camera", start))
        self.assertFalse(safety.needs_confirmation("live_camera", {"action": "stop"}))

    def test_smart_lock_unlock_requires_confirmation(self):
        args = {"action": "unlock", "device": "front door"}
        self.assertEqual(safety.classify("smart_home_control", args), safety.Risk.HIGH)
        self.assertTrue(safety.needs_confirmation("smart_home_control", args))
        self.assertFalse(safety.needs_confirmation(
            "smart_home_control", {"action": "lock", "device": "front door"}
        ))

    def test_browser_form_submission_is_high_risk(self):
        args = {"action": "submit_form", "text": "Enregistrer"}
        self.assertEqual(safety.classify("browser_control", args), safety.Risk.HIGH)
        self.assertTrue(safety.needs_confirmation("browser_control", args))
        self.assertIn("save or change website data", safety.describe("browser_control", args))

    def test_browser_navigation_and_form_fill_remain_medium_risk(self):
        self.assertEqual(
            safety.classify("browser_control", {"action": "go_to"}),
            safety.Risk.MEDIUM,
        )
        self.assertEqual(
            safety.classify("browser_control", {"action": "fill_form"}),
            safety.Risk.MEDIUM,
        )

    def test_external_messages_and_enter_to_submit_require_confirmation(self):
        message = {
            "receiver": "Ada",
            "message_text": "Please review the attached report.",
        }
        self.assertEqual(safety.classify("send_message", message), safety.Risk.HIGH)
        self.assertTrue(safety.needs_confirmation("send_message", message))
        self.assertIn("Ada", safety.describe("send_message", message))
        self.assertIn("attached report", safety.describe("send_message", message))

        enter = {"action": "press", "key": "Enter"}
        self.assertEqual(safety.classify("browser_control", enter), safety.Risk.HIGH)
        self.assertTrue(safety.needs_confirmation("browser_control", enter))

    def test_workspace_reads_are_low_risk_and_writes_or_checks_require_confirmation(self):
        for name in ("workspace_list_files", "workspace_read_file", "workspace_search"):
            with self.subTest(name=name):
                self.assertEqual(safety.classify(name, {}), safety.Risk.LOW)
                self.assertFalse(safety.needs_confirmation(name, {}))

        for name in (
            "workspace_write_file", "workspace_edit_file",
            "workspace_apply_patch", "workspace_run_check",
        ):
            with self.subTest(name=name):
                self.assertEqual(safety.classify(name, {}), safety.Risk.HIGH)
                self.assertTrue(safety.needs_confirmation(name, {}))

    def test_video_studio_status_is_read_only_but_analysis_is_medium(self):
        self.assertEqual(
            safety.classify("video_studio", {"action": "status"}),
            safety.Risk.LOW,
        )
        self.assertEqual(
            safety.classify("video_studio", {"action": "analyze"}),
            safety.Risk.MEDIUM,
        )

    def test_computer_control_requires_confirmation_except_stop_and_screen_info(self):
        self.assertEqual(
            safety.classify("computer_control", {"action": "click", "x": 20, "y": 30}),
            safety.Risk.HIGH,
        )
        self.assertTrue(safety.needs_confirmation(
            "computer_control", {"action": "click", "x": 20, "y": 30}
        ))
        self.assertEqual(
            safety.classify("computer_control", {"action": "screen_describe"}),
            safety.Risk.HIGH,
        )
        self.assertIn("disabled", safety.describe(
            "computer_control", {"action": "screen_describe"}
        ))
        self.assertEqual(
            safety.classify("computer_control", {"action": "screen_info"}),
            safety.Risk.LOW,
        )
        self.assertEqual(
            safety.classify("computer_control", {"action": "stop"}),
            safety.Risk.LOW,
        )
        self.assertEqual(
            safety.classify("computer_control", {"action": "screen_monitor_start"}),
            safety.Risk.HIGH,
        )
        self.assertTrue(safety.needs_confirmation(
            "computer_control", {"action": "screen_monitor_start"}
        ))
        for action in ("screen_monitor_status", "screen_monitor_stop"):
            with self.subTest(action=action):
                self.assertEqual(
                    safety.classify("computer_control", {"action": action}),
                    safety.Risk.LOW,
                )

    def test_screen_ocr_requires_one_confirmation_per_session(self):
        safety.reset_screen_ocr_consent()
        screen_args = {"angle": "screen", "text": "read the window"}
        self.assertEqual(safety.classify("screen_process", screen_args), safety.Risk.HIGH)
        self.assertTrue(safety.needs_confirmation("screen_process", screen_args))
        screen_description = safety.describe("screen_process", screen_args)
        self.assertIn("send only that text to Gemini", screen_description)
        self.assertIn("never send the screenshot", screen_description)
        self.assertIn("private information", screen_description)

        token = safety.issue_confirmation_token("screen_process", screen_args)
        self.assertFalse(safety.needs_confirmation(
            "screen_process", screen_args, confirm=True, confirm_token=token
        ))
        self.assertFalse(safety.needs_confirmation("screen_process", screen_args))
        safety.reset_screen_ocr_consent()
        self.assertTrue(safety.needs_confirmation("screen_process", screen_args))

    def test_screen_ocr_consent_does_not_authorize_camera(self):
        safety.reset_screen_ocr_consent()
        screen_args = {"angle": "screen", "text": "read the window"}
        token = safety.issue_confirmation_token("screen_process", screen_args)
        self.assertFalse(safety.needs_confirmation(
            "screen_process", screen_args, confirm=True, confirm_token=token
        ))
        camera_args = {"angle": "camera", "text": "describe the camera"}
        self.assertTrue(safety.needs_confirmation("screen_process", camera_args))
        self.assertIn("send that image", safety.describe("screen_process", camera_args))
        safety.reset_screen_ocr_consent()
        self.assertEqual(
            safety.classify("computer_settings", {"action": "type_text", "value": "private text"}),
            safety.Risk.HIGH,
        )
        self.assertEqual(
            safety.classify("computer_settings", {"description": "type a message"}),
            safety.Risk.HIGH,
        )

    def test_local_screen_vision_is_read_only_and_never_prompts_for_remote_consent(self):
        args = {"angle": "local_vision", "text": "Describe what is on screen."}

        self.assertEqual(safety.classify("screen_process", args), safety.Risk.LOW)
        self.assertFalse(safety.needs_confirmation("screen_process", args))
        description = safety.describe("screen_process", args)
        self.assertIn("local Ollama", description)
        self.assertIn("not sent to Gemini", description)

    def test_unknown_tool_defaults_to_medium(self):
        self.assertEqual(safety.classify("totally_unknown_tool", {}), safety.Risk.MEDIUM)


class ConfirmationTest(unittest.TestCase):

    def test_high_needs_confirmation(self):
        self.assertTrue(safety.needs_confirmation("cmd_control", {"command": "dir"}))

    def test_low_does_not_need_confirmation(self):
        self.assertFalse(safety.needs_confirmation("web_search", {"query": "x"}))

    def test_confirm_flag_alone_does_not_bypass(self):
        # confirm=true with no valid token no longer bypasses the gate.
        self.assertTrue(
            safety.needs_confirmation("cmd_control", {"command": "dir"}, confirm=True)
        )


class ConfirmationTokenTest(unittest.TestCase):
    """Technical enforcement: confirm=true alone is not enough; a one-time
    token issued for the exact blocked call is required."""

    def test_confirm_without_token_is_blocked(self):
        # confirm=true with no token must NOT bypass the gate.
        self.assertTrue(
            safety.needs_confirmation("cmd_control", {"command": "dir"},
                                      confirm=True, confirm_token="")
        )
        self.assertTrue(
            safety.needs_confirmation("cmd_control", {"command": "dir"},
                                      confirm=True, confirm_token="garbage")
        )

    def test_issued_token_works_once(self):
        tok = safety.issue_confirmation_token("cmd_control", {"command": "dir"})
        # First redeem succeeds (and consumes the token).
        self.assertFalse(
            safety.needs_confirmation("cmd_control", {"command": "dir"},
                                      confirm=True, confirm_token=tok)
        )
        # Second use fails — token is single-use.
        self.assertTrue(
            safety.needs_confirmation("cmd_control", {"command": "dir"},
                                      confirm=True, confirm_token=tok)
        )

    def test_token_bound_to_exact_call(self):
        tok = safety.issue_confirmation_token("cmd_control", {"command": "dir"})
        # Different args -> blocked.
        self.assertTrue(
            safety.needs_confirmation("cmd_control", {"command": "format c:"},
                                      confirm=True, confirm_token=tok)
        )
        # Different tool -> blocked.
        self.assertTrue(
            safety.needs_confirmation("desktop_control", {"action": "reset"},
                                      confirm=True, confirm_token=tok)
        )
        workspace_token = safety.issue_confirmation_token(
            "workspace_edit_file",
            {"path": "safe.txt", "find": "alpha", "replace": "beta"},
        )
        self.assertTrue(safety.redeem_confirmation_token(
            "workspace_edit_file",
            {"path": "safe.txt", "find": "other", "replace": "beta"},
            workspace_token,
        ) is False)

    def test_confirmation_token_expires_after_ttl(self):
        with mock.patch.object(safety.time, "monotonic", side_effect=[1000.0, 1600.0]):
            token = safety.issue_confirmation_token(
                "cmd_control", {"command": "dir"}
            )
            redeemed = safety.redeem_confirmation_token(
                "cmd_control", {"command": "dir"}, token
            )
        self.assertFalse(redeemed)

    def test_low_risk_never_asks_for_token(self):
        self.assertFalse(
            safety.needs_confirmation("web_search", {"query": "x"},
                                      confirm=True, confirm_token="nope")
        )


class DescribeTest(unittest.TestCase):

    def test_delete_description(self):
        desc = safety.describe("file_controller", {"action": "delete", "name": "notes.txt"})
        self.assertIn("delete notes.txt", desc)

    def test_command_description(self):
        desc = safety.describe("cmd_control", {"command": "dir"})
        self.assertIn("dir", desc)


class SanitizeTest(unittest.TestCase):

    def test_api_key_masked(self):
        out = safety.sanitize("api_add_key", {"key": "AIzaSyB-...", "note": "hi"})
        self.assertEqual(out["key"], "***")
        self.assertEqual(out["note"], "hi")

    def test_token_masked(self):
        out = safety.sanitize("any", {"access_token": "abc123", "path": "C:/x"})
        self.assertEqual(out["access_token"], "***")
        self.assertEqual(out["path"], "C:/x")

    def test_workspace_source_content_is_redacted_from_logs(self):
        for tool, field in (
            ("workspace_write_file", "content"),
            ("workspace_edit_file", "replace"),
            ("workspace_apply_patch", "patch"),
        ):
            with self.subTest(tool=tool):
                result = safety.sanitize(tool, {field: "private project source"})
                self.assertEqual(result[field], "[source content redacted]")

    def test_browser_page_data_is_not_written_to_logs(self):
        import logger

        output = StringIO()
        with redirect_stdout(output):
            logger.log_tool(
                "browser_control",
                {"action": "inspect", "text": "student name"},
                result="Student Name: Private Student; Grade: 93841",
            )
        self.assertNotIn("student name", output.getvalue())
        self.assertNotIn("Private Student", output.getvalue())
        self.assertNotIn("93841", output.getvalue())

    def test_file_contents_and_private_results_are_not_written_to_logs(self):
        import logger

        output = StringIO()
        with redirect_stdout(output):
            logger.log_tool(
                "file_controller",
                {
                    "action": "write",
                    "path": r"C:\Users\pc\Documents\private.txt",
                    "content": "synthetic-private-marker",
                },
                result="synthetic-private-marker",
            )
            logger.log_tool(
                "read_document",
                {"path": "notes.txt"},
                result="synthetic-document-marker",
            )

        logged = output.getvalue()
        for marker in (
            "synthetic-private-marker",
            "synthetic-document-marker",
            "private.txt",
            "Documents",
        ):
            self.assertNotIn(marker, logged)
        self.assertIn("details=[omitted]", logged)

    def test_computer_use_content_is_redacted_from_logs(self):
        computer_args = safety.sanitize("computer_control", {
            "action": "type",
            "text": "private text",
            "title": "Private document - Word",
            "x": 20,
        })
        self.assertEqual(computer_args["text"], "[private]")
        self.assertEqual(computer_args["title"], "[private]")
        self.assertEqual(computer_args["x"], 20)
        screen_args = safety.sanitize("screen_process", {
            "angle": "screen",
            "text": "read confidential page",
        })
        self.assertEqual(screen_args["text"], "[private]")


if __name__ == "__main__":
    unittest.main()
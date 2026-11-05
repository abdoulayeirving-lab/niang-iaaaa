"""Opt-in live tests for browser and Windows desktop automation."""

import os
import platform
import re
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit


_RUN_MANUAL_TESTS = os.environ.get("NIANG_IA_RUN_MANUAL_AGENT_TESTS") == "1"


@unittest.skipUnless(
    _RUN_MANUAL_TESTS,
    "Set NIANG_IA_RUN_MANUAL_AGENT_TESTS=1 to run live browser/desktop tests.",
)
class AutonomousAgentManualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from actions.playwright_mcp import playwright_mcp_control

        cls.browser = staticmethod(playwright_mcp_control)
        cls.browser("state", {})

    @classmethod
    def tearDownClass(cls):
        from actions.playwright_mcp import shutdown_playwright_mcp

        shutdown_playwright_mcp()

    def test_01_google_search_loads_results_or_reports_rate_limiting(self):
        result = self.browser(
            "search",
            {"engine": "google", "query": "NIANG IA autonomous agent"},
        )
        state = self.browser("state", {})
        self.assertIn("google.com/search", state)
        if "HTTP status: 429" in result or re.search(r"captcha|unusual traffic", state, re.I):
            self.skipTest("Google challenged this network; the navigation was detected.")
        self.assertRegex(state, r"(?i)search|result|NIANG")

    def test_02_visits_three_sites_and_compares_their_titles(self):
        pages = (
            ("https://example.com", "Example Domain"),
            ("https://www.iana.org/domains/reserved", "IANA"),
            ("https://www.selenium.dev/selenium/web/web-form.html", "Web form"),
        )
        observed = []
        for url, expected_title in pages:
            self.browser("go_to", {"url": url})
            state = self.browser("state", {})
            self.assertIn(expected_title, state)
            observed.append((urlsplit(url).hostname, expected_title))
        self.assertEqual(len({title for _, title in observed}), 3)
        self.assertIn("example.com", observed[0][0])

    def test_03_fills_demo_form_without_submitting(self):
        self.browser(
            "go_to",
            {"url": "https://www.selenium.dev/selenium/web/web-form.html"},
        )
        snapshot = self.browser("state", {})
        text_ref = re.search(r'textbox "Text input" \[ref=([\w-]+)\]', snapshot)
        area_ref = re.search(r'textbox "Textarea" \[ref=([\w-]+)\]', snapshot)
        self.assertIsNotNone(text_ref)
        self.assertIsNotNone(area_ref)
        self.browser("type", {"ref": text_ref.group(1), "text": "NIANG manual test"})
        self.browser(
            "fill_form",
            {"fields": [{"selector": area_ref.group(1), "value": "Not submitted"}]},
        )
        verified = self.browser("state", {})
        self.assertIn("NIANG manual test", verified)
        self.assertIn("Not submitted", verified)
        self.assertIn("/web-form.html", verified)

    def test_04_opens_notepad_and_types_with_ui_automation(self):
        if platform.system() != "Windows":
            self.skipTest("Notepad UI Automation is Windows-only.")
        import psutil
        from pywinauto import Desktop
        from actions.computer_control import _uia_type

        if any(
            (process.info.get("name") or "").casefold() in {"notepad.exe", "notepad"}
            for process in psutil.process_iter(["name"])
        ):
            self.skipTest("Notepad is already running; leaving existing documents untouched.")

        with tempfile.TemporaryDirectory(prefix="niang-notepad-") as directory:
            path = Path(directory) / f"NIANG_Agent_{uuid.uuid4().hex[:8]}.txt"
            path.write_text("", encoding="utf-8")
            process = subprocess.Popen(["notepad.exe", str(path)])
            window = None
            try:
                deadline = time.monotonic() + 15
                desktop = Desktop(backend="uia")
                while time.monotonic() < deadline:
                    window = next(
                        (
                            candidate for candidate in desktop.windows()
                            if path.name.casefold() in candidate.window_text().casefold()
                        ),
                        None,
                    )
                    if window:
                        break
                    time.sleep(0.25)
                self.assertIsNotNone(window, "Notepad did not open the unique test document.")
                window.set_focus()
                candidates = [
                    control
                    for control in window.descendants()
                    if (control.element_info.control_type or "") in {"Edit", "Document"}
                    and control.window_text().strip()
                ]
                self.assertTrue(candidates, "Notepad exposed no named editable UIA control.")
                outcome = _uia_type(candidates[0].window_text(), "NIANG UI Automation test")
                self.assertTrue(outcome["verified"])
                window.type_keys("^s")
                self.assertEqual(path.read_text(encoding="utf-8"), "NIANG UI Automation test")
            finally:
                if window is not None:
                    try:
                        window.set_focus()
                        window.type_keys("^s")
                        window.type_keys("^w")
                    except Exception as exc:
                        print(f"Notepad test cleanup could not close its scratch tab: {exc}")
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)

    def test_05_creates_and_cleans_a_temporary_desktop_folder(self):
        if platform.system() != "Windows":
            self.skipTest("The Desktop folder test is Windows-only.")
        from actions.file_controller import file_controller

        desktop = Path.home() / "Desktop"
        if not desktop.is_dir():
            self.skipTest("The standard Desktop directory does not exist.")
        name = f"NIANG_Agent_Test_{uuid.uuid4().hex[:8]}"
        result = file_controller(
            {"action": "create_folder", "path": "desktop", "name": name}
        )
        folder = desktop / name
        try:
            self.assertTrue(folder.is_dir(), result)
        finally:
            if folder.is_dir():
                folder.rmdir()

    def test_06_opens_and_reads_a_file_through_file_controller(self):
        from actions.file_controller import file_controller

        with tempfile.TemporaryDirectory(prefix="niang-agent-") as directory:
            path = Path(directory) / "read-me.txt"
            path.write_text("NIANG file-read verification", encoding="utf-8")
            result = file_controller({
                "action": "read",
                "path": str(path.parent),
                "name": path.name,
            })
        self.assertIn("NIANG file-read verification", result)

    def test_07_replans_after_navigation_error(self):
        from agent.error_handler import ErrorDecision
        from agent.executor import AgentExecutor

        failed_plan = {
            "steps": [{
                "step": 1,
                "tool": "browser_control",
                "description": "Navigate to a page with a transient server error",
                "parameters": {"action": "go_to", "url": "https://example.com"},
            }]
        }
        recovered_plan = {
            "steps": [{
                "step": 2,
                "tool": "browser_control",
                "description": "Open a public verification page",
                "parameters": {"action": "go_to", "url": "https://example.com"},
            }]
        }
        with (
            patch("agent.executor.create_plan", return_value=failed_plan),
            patch("agent.executor.replan", return_value=recovered_plan) as replan,
            patch(
                "agent.executor._call_tool_with_timeout",
                side_effect=[
                    "HTTP status: 503",
                    "Opened: https://example.com (title: Example)",
                ],
            ),
            patch(
                "agent.executor.analyze_error",
                return_value={
                    "decision": ErrorDecision.REPLAN,
                    "reason": "The navigation returned a transient server error.",
                    "fix_suggestion": "",
                    "user_message": "",
                },
            ) as analyze_error,
            patch.object(
                AgentExecutor,
                "_summarize",
                return_value="Recovered after the blocked navigation.",
            ),
        ):
            result = AgentExecutor().execute("Recover from a navigation server error.")
        self.assertEqual(result, "Recovered after the blocked navigation.")
        replan.assert_called_once()
        analyze_error.assert_called_once()


if __name__ == "__main__":
    unittest.main()

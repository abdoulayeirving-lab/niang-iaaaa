import unittest
import tempfile
from pathlib import Path

from actions.playwright_mcp import (
    PlaywrightMCPClient,
    _redact_accessibility_text,
    _saved_download_path,
    _saved_screenshot_path,
    _cleanup_transient_artifacts,
)


class PlaywrightMCPTests(unittest.TestCase):
    def test_browser_navigation_and_tab_actions_map_to_mcp_schema(self):
        navigation = PlaywrightMCPClient._tool_arguments(
            "go_to",
            {"url": "https://example.com"},
            {"properties": {"url": {"type": "string"}}},
        )
        tabs = PlaywrightMCPClient._tool_arguments(
            "switch_tab",
            {"tab_id": "tab-3"},
            {
                "properties": {
                    "action": {"type": "string"},
                    "index": {"type": "integer"},
                }
            },
        )
        indexed_tab = PlaywrightMCPClient._tool_arguments(
            "switch_tab",
            {"tab_id": "1", "index": 1},
            {
                "properties": {
                    "action": {"type": "string"},
                    "index": {"type": "integer"},
                }
            },
        )

        self.assertEqual(navigation, {"url": "https://example.com"})
        self.assertEqual(tabs, {"action": "select", "index": 2})
        self.assertEqual(indexed_tab, {"action": "select", "index": 1})

    def test_form_values_are_converted_to_mcp_fill_schema(self):
        schema = {
            "properties": {
                "fields": {
                    "items": {
                        "properties": {
                            "target": {"type": "string"},
                            "name": {"type": "string"},
                            "type": {"type": "string"},
                            "value": {"type": "string"},
                        }
                    }
                }
            }
        }

        arguments = PlaywrightMCPClient._tool_arguments(
            "fill_form",
            {"fields": [{"selector": "Email", "value": "ada@example.com"}]},
            schema,
        )

        self.assertEqual(arguments["fields"], [{
            "target": "Email",
            "name": "Email",
            "type": "textbox",
            "value": "ada@example.com",
        }])

    def test_interaction_targets_and_screenshot_required_fields_match_server_schema(self):
        click = PlaywrightMCPClient._tool_arguments(
            "click",
            {"ref": "e12", "description": "Search button"},
            {"properties": {"element": {}, "target": {}}},
        )
        typing = PlaywrightMCPClient._tool_arguments(
            "type",
            {"selector": "#query", "text": "cats"},
            {"properties": {"element": {}, "target": {}, "text": {}}},
        )
        screenshot = PlaywrightMCPClient._tool_arguments(
            "screenshot",
            {},
            {"properties": {"fullPage": {}, "scale": {}}},
        )

        self.assertEqual(click, {"element": "Search button", "target": "e12"})
        self.assertEqual(
            typing,
            {"target": "#query", "text": "cats"},
        )
        self.assertEqual(screenshot, {"fullPage": True, "scale": "css"})

    def test_download_uses_a_specific_accessibility_target(self):
        arguments = PlaywrightMCPClient._tool_arguments(
            "download",
            {"ref": "e29", "description": "ExampleFile.txt"},
            {"properties": {"element": {}, "target": {}}},
        )

        self.assertEqual(
            arguments,
            {"element": "ExampleFile.txt", "target": "e29"},
        )

    def test_accessibility_output_redacts_secret_labels(self):
        text = 'textbox "Password": hunter2\nbutton "Continue"'

        self.assertEqual(
            _redact_accessibility_text(text),
            'textbox "Password": [REDACTED]\nbutton "Continue"',
        )

    def test_screenshot_path_is_resolved_inside_the_mcp_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            screenshot = output_dir / "page-123.png"
            screenshot.touch()

            resolved = _saved_screenshot_path(
                "### Result\n- [Screenshot](..\\\\..\\\\NIANG_IA_Agent\\\\page-123.png)",
                output_dir,
            )

        self.assertEqual(resolved, screenshot)
        self.assertIsNone(_saved_screenshot_path(
            "### Result\n- [Screenshot](..\\\\..\\\\secrets.png)",
            output_dir,
        ))

    def test_download_path_is_resolved_inside_the_mcp_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            download = output_dir / "ExampleFile.txt"
            download.write_text("test data", encoding="utf-8")

            resolved = _saved_download_path(
                'Downloaded file ExampleFile.txt to "..\\\\..\\\\NIANG_IA_Agent\\\\ExampleFile.txt"',
                output_dir,
            )
            server_result = _saved_download_path(
                "### Events\n- Downloading file ExampleFile.txt ...",
                output_dir,
            )
            outside = _saved_download_path(
                'Downloaded file ExampleFile.txt to "..\\\\..\\\\secrets.txt"',
                output_dir,
            )

        self.assertEqual(resolved, download)
        self.assertEqual(server_result, download)
        self.assertIsNone(outside)

    def test_temporary_page_and_console_files_are_removed_but_outputs_are_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            page = output_dir / "page-2026-11-02T15-53-33-747Z.yml"
            console = output_dir / "console-2026-11-02T15-53-30-396Z.log"
            previous = output_dir / "page-2026-11-02T15-53-32-834Z.yml"
            screenshot = output_dir / "page-2026-11-02T15-53-33-747Z.png"
            for path in (page, console, previous, screenshot):
                path.touch()

            failed = _cleanup_transient_artifacts(
                output_dir,
                {previous.name},
            )

            self.assertFalse(failed)
            self.assertFalse(page.exists())
            self.assertFalse(console.exists())
            self.assertTrue(previous.exists())
            self.assertTrue(screenshot.exists())

    def test_fill_form_uses_accessibility_role_for_non_text_inputs(self):
        client = PlaywrightMCPClient()
        client._last_snapshot = (
            '- checkbox "Accept terms" [ref=e31]\n'
            '- combobox "Region" [ref=e32]'
        )

        self.assertEqual(client._field_type("e31"), "checkbox")
        self.assertEqual(client._field_type("Region"), "combobox")
        self.assertEqual(client._field_type("missing"), "textbox")

if __name__ == "__main__":
    unittest.main()

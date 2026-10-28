"""Tests for guarded Windows UI automation primitives."""

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions import computer_control


class _FakeMouse:
    def __init__(self):
        self.position_value = (1, 1)
        self.calls = []
        self.PAUSE = 0.05

    def size(self):
        return (100, 80)

    def position(self):
        return self.position_value

    def moveTo(self, x, y, duration=0):
        self.position_value = (x, y)
        self.calls.append(("move", x, y))

    def click(self, *args, **kwargs):
        self.calls.append(("click", args, kwargs))

    def mouseDown(self, button="left"):
        self.calls.append(("down", button))

    def mouseUp(self, button="left"):
        self.calls.append(("up", button))

    def screenshot(self):
        from PIL import Image
        return Image.new("RGB", (4, 4), "black")

    def write(self, text, interval=0):
        self.calls.append(("write", text))


class ComputerControlTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_home = Path(self.temp_dir.name)
        self.fake = _FakeMouse()
        self.pg_patch = patch.object(computer_control, "_PG_MOD", self.fake)
        self.pg_patch.start()
        self.print_patch = patch("builtins.print")
        self.print_patch.start()
        computer_control._STOP_REQUESTED.clear()
        computer_control._HELD_BUTTONS.clear()

    def tearDown(self):
        computer_control._STOP_REQUESTED.clear()
        computer_control._HELD_BUTTONS.clear()
        self.print_patch.stop()
        self.pg_patch.stop()
        self.temp_dir.cleanup()

    def test_action_result_has_execution_and_verification_fields(self):
        result = json.loads(computer_control._action_result(
            "click", executed=True, result={"x": 4}, verified=False
        ))
        self.assertEqual(
            result,
            {
                "action": "click",
                "executed": True,
                "verified": False,
                "result": {"x": 4},
                "error": None,
            },
        )

    def test_click_rejects_out_of_bounds_coordinates_without_clicking(self):
        result = json.loads(computer_control.computer_control({
            "action": "click", "x": 100, "y": 2,
        }))
        self.assertFalse(result["executed"])
        self.assertIn("within the 100x80 screen", result["error"])
        self.assertFalse(any(call[0] == "click" for call in self.fake.calls))

    def test_drag_moves_to_start_and_releases_button(self):
        result = computer_control._drag(10, 20, 30, 40, duration=0)
        self.assertEqual(result, "Dragged from (10,20) to (30,40)")
        self.assertEqual(self.fake.calls[0], ("move", 10, 20))
        self.assertIn(("down", "left"), self.fake.calls)
        self.assertIn(("move", 30, 40), self.fake.calls)
        self.assertEqual(self.fake.calls[-1], ("up", "left"))
        self.assertNotIn("left", computer_control._HELD_BUTTONS)

    def test_drag_rejects_invalid_coordinates(self):
        with self.assertRaisesRegex(ValueError, "within the 100x80 screen"):
            computer_control._drag(-1, 0, 10, 10)
        self.assertEqual(self.fake.calls, [])

    def test_move_is_interruptible_by_stop_event(self):
        def move_and_stop(x, y, duration=0):
            self.fake.position_value = (x, y)
            self.fake.calls.append(("move", x, y))
            computer_control._STOP_REQUESTED.set()

        self.fake.moveTo = move_and_stop
        result = computer_control._move_mouse(90, 70, duration=1)
        self.assertEqual(result, "Mouse movement stopped by user.")
        self.assertEqual(len(self.fake.calls), 1)

    def test_typing_stops_between_keystrokes(self):
        def write_and_stop(text, interval=0):
            self.fake.calls.append(("write", text))
            computer_control._STOP_REQUESTED.set()

        self.fake.write = write_and_stop
        result = computer_control._type_text("hello", interval=0)
        self.assertEqual(result, "Typing stopped by user.")
        self.assertEqual(self.fake.calls, [("write", "h")])

    def test_drag_releases_button_when_interrupted(self):
        original_move = self.fake.moveTo
        moves = 0

        def move_and_stop(x, y, duration=0):
            nonlocal moves
            original_move(x, y, duration)
            moves += 1
            if moves == 2:
                computer_control._STOP_REQUESTED.set()

        self.fake.moveTo = move_and_stop
        result = computer_control._drag(10, 10, 80, 60, duration=1)
        self.assertEqual(result, "Drag stopped by user.")
        self.assertEqual(self.fake.calls[-1], ("up", "left"))
        self.assertNotIn("left", computer_control._HELD_BUTTONS)

    def test_stop_releases_all_held_mouse_buttons(self):
        computer_control._HELD_BUTTONS.update({"left", "right"})
        result = computer_control.computer_control({"action": "stop"})
        parsed = json.loads(result)
        self.assertTrue(parsed["verified"])
        self.assertTrue(computer_control._STOP_REQUESTED.is_set())
        self.assertIn(("up", "left"), self.fake.calls)
        self.assertIn(("up", "right"), self.fake.calls)
        self.assertFalse(computer_control._HELD_BUTTONS)

    def test_screen_size_result_is_structured_and_read_only(self):
        result = json.loads(computer_control.computer_control({"action": "screen_info"}))
        self.assertTrue(result["executed"])
        self.assertTrue(result["verified"])
        self.assertEqual(result["result"]["width"], 100)
        self.assertEqual(result["result"]["height"], 80)

    def test_screenshot_is_restricted_to_user_home_and_saved_verifiably(self):
        from PIL import Image
        with (
            patch.object(computer_control.Path, "home", return_value=self.temp_home),
            patch.object(computer_control, "_capture_screen_image", return_value=Image.new("RGB", (4, 4))),
        ):
            with self.assertRaisesRegex(ValueError, "inside the current user's home"):
                computer_control._screenshot(str(self.temp_home.parent / "outside.png"))
            destination = computer_control._screenshot(
                str(self.temp_home / "Pictures" / "screen.png")
            )
        self.assertTrue(os.path.isfile(destination))

    def test_visual_target_parser_requires_valid_confidence_and_screen_coordinates(self):
        parsed = computer_control._parse_visual_target(
            '{"x":10,"y":20,"confidence":0.93}', 100, 80
        )
        self.assertEqual(parsed, {"x": 10, "y": 20, "confidence": 0.93})
        self.assertIsNone(computer_control._parse_visual_target("NOT_FOUND", 100, 80))
        with self.assertRaisesRegex(RuntimeError, "confidence"):
            computer_control._parse_visual_target('{"x":10,"y":20}', 100, 80)
        with self.assertRaisesRegex(RuntimeError, "out-of-screen"):
            computer_control._parse_visual_target(
                '{"x":100,"y":20,"confidence":0.93}', 100, 80
            )

    def test_visual_click_is_blocked_below_confidence_threshold(self):
        target = {"x": 20, "y": 30, "confidence": 0.79}
        with (
            patch.object(computer_control, "_analyze_screen_for_element", return_value=target),
            patch.object(computer_control, "_click") as click,
        ):
            result = json.loads(computer_control.computer_control({
                "action": "screen_click",
                "description": "Save button",
            }))
        self.assertFalse(result["executed"])
        self.assertIn("0.8 click threshold", result["error"])
        click.assert_not_called()

    def test_visual_click_runs_only_for_confident_target_and_requires_followup(self):
        target = {"x": 20, "y": 30, "confidence": 0.94}
        with (
            patch.object(computer_control, "_analyze_screen_for_element", return_value=target),
            patch.object(computer_control, "_click") as click,
        ):
            result = json.loads(computer_control.computer_control({
                "action": "screen_click",
                "description": "Save button",
            }))
        click.assert_called_once_with(x=20, y=30)
        self.assertTrue(result["executed"])
        self.assertFalse(result["verified"])
        self.assertTrue(result["result"]["follow_up_verification_required"])

    def test_active_window_controls_are_reported_with_accessible_roles(self):
        class FakeBounds:
            left, top = 10, 20

            @staticmethod
            def width():
                return 100

            @staticmethod
            def height():
                return 30

        class FakeControl:
            def window_text(self):
                return "Save"

            class element_info:
                control_type = "Button"

            @staticmethod
            def rectangle():
                return FakeBounds()

        class FakeWindow:
            @staticmethod
            def descendants():
                return [FakeControl()]

        class FakeDesktop:
            def __init__(self, backend):
                self.backend = backend

            @staticmethod
            def window(handle):
                return FakeWindow()

        fake_pywinauto = types.ModuleType("pywinauto")
        fake_pywinauto.Desktop = FakeDesktop
        with (
            patch.object(computer_control.platform, "system", return_value="Windows"),
            patch.object(computer_control, "_active_window", return_value={"handle": 123}),
            patch.dict(sys.modules, {"pywinauto": fake_pywinauto}),
        ):
            elements = computer_control._find_ui_elements()
        self.assertEqual(elements[0]["name"], "Save")
        self.assertEqual(elements[0]["role"], "Button")

    def test_missing_user_profile_values_are_not_replaced_with_random_data(self):
        with patch.object(computer_control, "_load_user_profile", return_value={}):
            result = json.loads(computer_control.computer_control({
                "action": "user_data",
                "field": "email",
            }))
        self.assertFalse(result["executed"])
        self.assertIn("no substitute was generated", result["error"])

    def test_emergency_hotkey_is_opt_in_and_registered(self):
        fake_keyboard = types.ModuleType("keyboard")
        fake_keyboard.add_hotkey = Mock(return_value="hook")
        fake_keyboard.remove_hotkey = Mock()
        with patch.dict(sys.modules, {"keyboard": fake_keyboard}):
            enabled = computer_control._set_emergency_hotkey(True)
            fake_keyboard.add_hotkey.assert_called_once()
            self.assertEqual(fake_keyboard.add_hotkey.call_args.args[0], "ctrl+alt+pause")
            self.assertTrue(enabled["enabled"])
            disabled = computer_control._set_emergency_hotkey(False)
            fake_keyboard.remove_hotkey.assert_called_once_with("hook")
            self.assertFalse(disabled["enabled"])

    def test_verification_matches_accessible_label_case_insensitively(self):
        with patch.object(computer_control, "_find_ui_elements", return_value=[
            {"name": "Save project", "role": "Button", "bounds": {}},
        ]):
            result = computer_control._verify_action("save")
        self.assertTrue(result["verified"])
        self.assertEqual(result["matches"][0]["role"], "Button")


if __name__ == "__main__":
    unittest.main()

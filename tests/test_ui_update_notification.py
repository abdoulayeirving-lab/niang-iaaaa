import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from i18n import tr
from ui import KaizumiUI


class FakeRoot:
    def __init__(self):
        self.callbacks = {}
        self.next_id = 0

    def after(self, delay, callback, *args):
        self.next_id += 1
        callback_id = f"after-{self.next_id}"
        self.callbacks[callback_id] = (delay, callback, args)
        return callback_id

    def after_cancel(self, callback_id):
        self.callbacks.pop(callback_id, None)


class FakeUpdateButton:
    def __init__(self):
        self.text = ""
        self.state = "normal"
        self.offset = 0

    def configure(self, **kwargs):
        self.text = kwargs.get("text", self.text)
        self.state = kwargs.get("state", self.state)

    def set_bounce(self, offset):
        self.offset = offset

    def winfo_exists(self):
        return True


class UpdateNotificationTests(unittest.TestCase):
    def make_ui(self):
        ui = KaizumiUI.__new__(KaizumiUI)
        ui.root = FakeRoot()
        ui._update_button = FakeUpdateButton()
        ui._update_check_in_progress = False
        ui._available_update = None
        ui._update_button_bounce_after = None
        ui._update_check_after = None
        ui.logs = []
        ui.write_log = ui.logs.append
        return ui

    def test_silent_update_detection_marks_and_bounces_button_without_prompt(self):
        ui = self.make_ui()
        update = SimpleNamespace(version="1.0.45")
        with patch("ui.messagebox.askyesno") as ask:
            ui._finish_update_check(update, None, silent=True)

        self.assertIs(ui._available_update, update)
        self.assertEqual(ui._update_button.text, tr("VERSION ") + update.version)
        self.assertIn("1.0.45", ui.logs[-1])
        self.assertIsNotNone(ui._update_button_bounce_after)
        ask.assert_not_called()

    def test_bounce_animation_moves_button_then_schedules_next_cycle(self):
        ui = self.make_ui()
        ui._update_button_bounce_step(0)
        self.assertEqual(ui._update_button.offset, 0)
        first_id = ui._update_button_bounce_after
        delay, callback, args = ui.root.callbacks[first_id]
        self.assertEqual(delay, 110)

        ui._update_button_bounce_after = None
        callback(*args)
        self.assertEqual(ui._update_button.offset, -5)
        self.assertIsNotNone(ui._update_button_bounce_after)

    def test_clicking_available_update_offers_cached_release_without_rechecking(self):
        ui = self.make_ui()
        update = SimpleNamespace(version="1.0.45")
        ui._available_update = update
        offers = []
        ui._offer_update_download = offers.append
        ui._start_update_check = lambda **_kwargs: self.fail(
            "The cached release should be offered without another request."
        )

        ui._check_for_updates()

        self.assertEqual(offers, [update])

    def test_silent_no_update_stops_bounce_without_changing_button_text(self):
        ui = self.make_ui()
        normal_label = tr("↻ MISE À JOUR")
        ui._update_button.set_bounce(-5)
        ui._update_button_bounce_after = ui.root.after(500, lambda: None)
        ui._finish_update_check(None, None, silent=True)

        self.assertEqual(ui._update_button.text, normal_label)
        self.assertEqual(ui._update_button.offset, 0)
        self.assertIsNone(ui._update_button_bounce_after)


if __name__ == "__main__":
    unittest.main()

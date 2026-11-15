import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from assistant_visibility import (
    FAREWELL_DELAY_MS,
    AssistantVisibility,
    CLOSING_ANIMATION_PATH,
)


class ClosingAnimationTests(unittest.TestCase):
    def test_animation_asset_is_included_and_decodable(self):
        self.assertTrue(CLOSING_ANIMATION_PATH.is_file())

        capture = cv2.VideoCapture(str(CLOSING_ANIMATION_PATH))
        try:
            self.assertTrue(capture.isOpened())
            ok, frame = capture.read()
            self.assertTrue(ok)
            self.assertGreater(frame.shape[0], 0)
            self.assertGreater(frame.shape[1], 0)
        finally:
            capture.release()

    def test_release_file_collection_includes_animation_asset(self):
        import build_release

        self.assertIn(CLOSING_ANIMATION_PATH, build_release.collect_files())

    def test_shutdown_plays_animation_after_preparing_services(self):
        ui = Mock()
        ui._safe_ui.side_effect = lambda callback, *args: callback(*args)
        ui._voiceover_path = None
        ui.on_farewell = None
        visibility = AssistantVisibility(ui)

        with (
            patch.object(visibility, "_play_closing_animation", return_value=True) as play,
            patch.object(visibility, "_shutdown_destroy") as destroy,
        ):
            visibility.shutdown()

        ui.on_application_close.assert_called_once_with()
        ui._stop_voiceover.assert_called_once_with()
        play.assert_called_once_with()
        destroy.assert_not_called()

    def test_shutdown_says_farewell_before_cleanup(self):
        ui = Mock()
        ui._safe_ui.side_effect = lambda callback, *args: callback(*args)
        ui.on_farewell.return_value = True
        visibility = AssistantVisibility(ui)
        visibility._continue_shutdown = Mock()

        visibility.shutdown()

        ui.on_farewell.assert_called_once_with()
        ui.root.after.assert_called_once()
        self.assertEqual(ui.root.after.call_args.args[0], FAREWELL_DELAY_MS)
        visibility._continue_shutdown.assert_not_called()
        ui.root.after.call_args.args[1]()
        visibility._continue_shutdown.assert_called_once_with(True)

    def test_animation_uses_the_main_window_instead_of_opening_another(self):
        frame = np.zeros((100, 160, 3), dtype=np.uint8)
        capture = Mock()
        capture.isOpened.return_value = True
        capture.read.return_value = (True, frame)
        capture.get.return_value = 30
        root = Mock()
        root.geometry.return_value = "600x400+40+40"
        root.overrideredirect.return_value = False
        attributes = {"-topmost": False, "-alpha": 1.0}

        def set_attribute(name, *values):
            if values:
                attributes[name] = values[0]
            return attributes[name]

        root.attributes.side_effect = set_attribute
        root.cget.return_value = "#ffffff"
        root.winfo_screenwidth.return_value = 800
        root.winfo_screenheight.return_value = 600
        label = Mock()
        ui = Mock()
        ui.root = root
        visibility = AssistantVisibility(ui)

        with (
            patch("cv2.VideoCapture", return_value=capture),
            patch("tkinter.Toplevel") as toplevel,
            patch("tkinter.Label", return_value=label),
            patch("PIL.ImageTk.PhotoImage", return_value=object()),
        ):
            self.assertTrue(visibility._play_closing_animation())

        toplevel.assert_not_called()
        self.assertIs(visibility._closing_window, root)
        visibility._finish_closing_animation_resources()
        label.destroy.assert_called_once_with()
        root.destroy.assert_not_called()
        capture.release.assert_called_once_with()

    def test_voice_stop_uses_the_animated_shutdown_path(self):
        ui = Mock()
        visibility = AssistantVisibility(ui)
        visibility._shutdown_on_ui = Mock()

        visibility._stop_now_on_ui("", delay_ms=3000)
        finish = ui.root.after.call_args.args[1]
        finish()

        visibility._shutdown_on_ui.assert_called_once_with(
            animate=True, announce_farewell=False
        )


if __name__ == "__main__":
    unittest.main()

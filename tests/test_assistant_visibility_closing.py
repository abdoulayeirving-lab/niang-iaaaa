import unittest
from unittest.mock import Mock, patch

import cv2

from assistant_visibility import AssistantVisibility, CLOSING_ANIMATION_PATH


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

    def test_voice_stop_uses_the_animated_shutdown_path(self):
        ui = Mock()
        visibility = AssistantVisibility(ui)
        visibility._shutdown_on_ui = Mock()

        visibility._stop_now_on_ui("", delay_ms=0)
        finish = ui.root.after.call_args.args[1]
        finish()

        visibility._shutdown_on_ui.assert_called_once_with(animate=True)


if __name__ == "__main__":
    unittest.main()

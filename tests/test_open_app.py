import unittest
from unittest.mock import patch

from actions import open_app


class WindowsAppLaunchTests(unittest.TestCase):
    @patch("actions.open_app.subprocess.Popen")
    def test_youtube_opens_fixed_url_through_hidden_cmd(self, popen):
        self.assertTrue(open_app._launch_windows("YouTube"))

        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["cmd.exe", "/c", "start", "", "https://www.youtube.com"])
        self.assertIn("creationflags", kwargs)
        self.assertIs(kwargs["stdout"], open_app.subprocess.DEVNULL)

    @patch("actions.open_app.subprocess.Popen")
    def test_recognized_app_uses_cmd_start_without_waiting(self, popen):
        self.assertTrue(open_app._launch_windows("chrome"))

        args, _ = popen.call_args
        self.assertEqual(args[0], ["cmd.exe", "/c", "start", "", "chrome"])

    @patch("actions.open_app.subprocess.Popen")
    def test_application_names_with_spaces_are_passed_as_single_argument(self, popen):
        self.assertTrue(open_app._launch_windows("Adobe Premiere Pro"))

        args, _ = popen.call_args
        self.assertEqual(args[0][-1], "Adobe Premiere Pro")

    @patch("actions.open_app.subprocess.Popen")
    def test_shell_metacharacters_are_rejected(self, popen):
        self.assertFalse(open_app._launch_windows("chrome & calc"))
        popen.assert_not_called()

    @patch("actions.open_app.subprocess.Popen")
    @patch("actions.open_app.platform.system", return_value="Windows")
    def test_shell_metacharacters_are_rejected_before_alias_normalization(self, _system, popen):
        result = open_app.open_app({"app_name": "chrome & calc"})

        self.assertIn("safely", result)
        popen.assert_not_called()

    @patch("actions.open_app.subprocess.Popen")
    def test_windows_settings_protocol_remains_supported(self, popen):
        self.assertTrue(open_app._launch_windows("ms-settings:"))
        popen.assert_called_once()


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from actions import open_app


class WindowsAppLaunchTests(unittest.TestCase):
    @patch("actions.open_app._open_chrome_app", return_value=True)
    def test_youtube_opens_as_chrome_app_window(self, chrome_app):
        self.assertTrue(open_app._launch_windows("YouTube"))

        chrome_app.assert_called_once_with("https://www.youtube.com")

    @patch("actions.open_app.subprocess.Popen")
    @patch("actions.open_app._app_paths_exists", return_value=True)
    @patch("actions.open_app.shutil.which", return_value=None)
    @patch("actions.open_app._find_registry_exe", return_value=None)
    @patch("actions.open_app._launch_start_menu", return_value=False)
    def test_recognized_app_uses_cmd_start_without_waiting(self, _menu, _reg, _which, _paths, popen):
        self.assertTrue(open_app._launch_windows("chrome"))

        args, _ = popen.call_args
        self.assertEqual(args[0], ["cmd.exe", "/c", "start", "", "chrome"])

    @patch("actions.open_app.subprocess.Popen")
    @patch("actions.open_app._app_paths_exists", return_value=True)
    @patch("actions.open_app.shutil.which", return_value=None)
    @patch("actions.open_app._find_registry_exe", return_value=None)
    @patch("actions.open_app._launch_start_menu", return_value=False)
    def test_application_names_with_spaces_are_passed_as_single_argument(self, _menu, _reg, _which, _paths, popen):
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

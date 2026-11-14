import unittest
from pathlib import Path
from unittest.mock import patch

from actions import autostart


class AutostartLauncherTests(unittest.TestCase):
    def test_autostart_uses_hidden_vbs_entrypoint_and_preserves_flags(self):
        base = Path("C:/NIANG IA")
        with patch.object(autostart, "get_base_dir", return_value=base):
            command = autostart._launch_command(remote=True, background=True)

        self.assertEqual(
            command,
            f'wscript.exe "{base / "START_NIANG_IA.vbs"}" --remote --background',
        )

    def test_voice_autostart_uses_hidden_vbs_entrypoint(self):
        base = Path("C:/NIANG IA")
        with patch.object(autostart, "get_base_dir", return_value=base):
            command = autostart._launcher_command()

        self.assertEqual(command, f'wscript.exe "{base / "START_NIANG_IA.vbs"}" --voice')


if __name__ == "__main__":
    unittest.main()

import unittest
from pathlib import Path
from unittest.mock import patch

from actions import autostart

ROOT = Path(__file__).resolve().parents[1]


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

    def test_remote_cmd_uses_windowless_python(self):
        source = (ROOT / "start_remote.cmd").read_text(encoding="utf-8")

        self.assertIn(".venv\\Scripts\\pythonw.exe", source)
        self.assertIn('start ""', source)
        self.assertIn("--remote", source)
        self.assertNotIn('python.exe" -u', source)
        self.assertNotIn("python -u", source)


if __name__ == "__main__":
    unittest.main()

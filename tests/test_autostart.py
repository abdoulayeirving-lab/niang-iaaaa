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

    def test_remote_cmd_uses_local_python_or_visible_repair(self):
        source = (ROOT / "start_remote.cmd").read_text(encoding="utf-8")

        self.assertIn(".venv\\Scripts\\pythonw.exe", source)
        self.assertIn('start ""', source)
        self.assertIn("--remote", source)
        self.assertIn('call "%~dp0START_NIANG_IA.bat" --remote', source)
        self.assertNotIn("where pythonw.exe", source)
        self.assertNotIn('start "" pythonw.exe', source)

    def test_repair_launcher_preserves_remote_flag_without_global_python_fallback(self):
        source = (ROOT / "START_NIANG_IA.bat").read_text(encoding="utf-8")

        self.assertIn('"%~dp0.venv\\Scripts\\pythonw.exe" -u "%~dp0main.py" %*', source)
        self.assertIn('"%PYTHON_EXE%" -u "%~dp0main.py" %*', source)
        self.assertNotIn("where pythonw.exe", source)


if __name__ == "__main__":
    unittest.main()

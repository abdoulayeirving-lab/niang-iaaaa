import unittest
from pathlib import Path

from PIL import Image

from build_release import collect_files, should_include


ROOT = Path(__file__).resolve().parents[1]


class InstallerPersonalizationTests(unittest.TestCase):
    def test_installer_asks_only_for_preferred_name_and_default_language(self):
        source = (ROOT / "NIANG_IA.iss").read_text(encoding="utf-8")

        self.assertIn("CreateCustomPage(wpSelectDir, '', '')", source)
        self.assertIn("Comment veux-tu que NIANG IA t''appelle ?", source)
        self.assertIn("Langue par défaut de NIANG IA", source)
        self.assertIn("UserNameEdit.Text", source)
        self.assertIn("LanguageCombo.Text", source)
        self.assertIn("LanguageCombo.ItemIndex := 0", source)
        self.assertIn("LanguageCombo.Items.Add('Français')", source)
        self.assertNotIn("PersonalizationPage.Add(", source)

    def test_prompt_uses_saved_name_and_language_as_defaults(self):
        prompt = (ROOT / "core" / "prompt.txt").read_text(encoding="utf-8")

        self.assertIn("saved Language as the default response language", prompt)
        self.assertIn("saved Name naturally", prompt)

    def test_installer_opens_official_key_page_and_saves_key_separately(self):
        source = (ROOT / "NIANG_IA.iss").read_text(encoding="utf-8")

        self.assertIn("https://aistudio.google.com/apikey", source)
        self.assertIn("Obtenir une clé Gemini", source)
        self.assertIn("GetApiKeyButton.OnClick := @OpenGeminiApiKeyPage", source)
        self.assertIn("url.dll,FileProtocolHandler", source)
        self.assertIn("Si le navigateur ne s''ouvre pas", source)
        self.assertIn("GeminiKeyEdit.Text", source)
        self.assertIn("installer_gemini_key.txt", source)
        self.assertIn("GeminiKeyEdit.PasswordChar := '*'", source)
        self.assertNotIn("Copy(KeyValue, 1, 4)", source)

    def test_updates_skip_saved_profile_and_api_key_pages_without_overwriting_data(self):
        source = (ROOT / "NIANG_IA.iss").read_text(encoding="utf-8")

        version = (ROOT / "VERSION.txt").read_text(encoding="ascii").strip()
        self.assertIn(f'#define AppVersion "{version}"', source)
        self.assertIn("memory\\long_term.json", source)
        self.assertIn("memory\\installer_profile.json", source)
        self.assertIn("config\\installer_gemini_key.txt", source)
        self.assertIn("config\\api_keys.json", source)
        self.assertIn("function ShouldSkipPage(PageID: Integer): Boolean;", source)
        self.assertIn("(PageID = PersonalizationPage.ID) and ExistingProfile", source)
        self.assertIn("(PageID = ApiKeyPage.ID) and ExistingApiConfig", source)
        self.assertIn("if not ExistingProfile then", source)
        self.assertIn("(not ExistingApiConfig) and (Trim(GeminiKeyEdit.Text) <> '')", source)

    def test_installer_configures_local_screen_vision_before_launch(self):
        installer = (ROOT / "NIANG_IA.iss").read_text(encoding="utf-8")
        build = (ROOT / "build_release.py").read_text(encoding="utf-8")
        setup_script = (ROOT / "install_screen_vision.ps1").read_text(encoding="utf-8")

        run_section = installer.split("[Run]", 1)[1].split("[Code]", 1)[0]
        self.assertIn(r'\install_screen_vision.ps1', run_section)
        self.assertLess(run_section.index("install_screen_vision.ps1"), run_section.index("START_NIANG_IA.bat"))
        self.assertIn("install_screen_vision.ps1", build)
        self.assertIn("qwen3-vl:2b", setup_script)
        self.assertIn('[version]"0.12.7"', setup_script)
        self.assertIn("Get-FileHash", setup_script)
        self.assertIn("127.0.0.1:11434", setup_script)
        self.assertIn("MessageBox]::Show", setup_script)

    def test_release_excludes_backup_files(self):
        test_backups = (
            ROOT / "tests" / "test_safety.py.audit_backup_20261103_010410.py",
            ROOT / "actions" / "calendar.py.backup_20261016_132605",
            ROOT / "actions" / "autostart.py.avant_niang_suite.bak",
        )

        for backup in test_backups:
            with self.subTest(backup=backup.name):
                self.assertFalse(should_include(backup, backup.parent))

    def test_release_includes_cline_integration(self):
        release_files = {
            path.relative_to(ROOT).as_posix()
            for path in collect_files()
        }

        self.assertIn("write_cline.py", release_files)
        self.assertIn("niang_ia/integrations/cline/cline_manager.py", release_files)

    def test_windows_icon_fills_canvas_and_has_transparent_rounded_corners(self):
        with Image.open(ROOT / "assets" / "niang_ia.ico") as source:
            sizes = source.info["sizes"]
            icon = source.convert("RGBA")

        self.assertIn((256, 256), sizes)
        self.assertEqual(icon.getpixel((0, 0))[3], 0)
        self.assertEqual(icon.getpixel((128, 128))[3], 255)
        self.assertEqual(icon.getchannel("A").getbbox(), (0, 0, 256, 256))


if __name__ == "__main__":
    unittest.main()

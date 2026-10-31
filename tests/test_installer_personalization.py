import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


class InstallerPersonalizationTests(unittest.TestCase):
    def test_installer_asks_only_for_preferred_name_and_default_language(self):
        source = (ROOT / "NIANG_IA.iss").read_text(encoding="utf-8")

        self.assertIn("CreateCustomPage(wpWelcome, '', '')", source)
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
        self.assertIn("GeminiKeyEdit.Text", source)
        self.assertIn("installer_gemini_key.txt", source)
        self.assertIn("GeminiKeyEdit.PasswordChar := '*'", source)
        self.assertNotIn("Copy(KeyValue, 1, 4)", source)

    def test_updates_skip_saved_profile_and_api_key_pages_without_overwriting_data(self):
        source = (ROOT / "NIANG_IA.iss").read_text(encoding="utf-8")

        self.assertIn('#define AppVersion "1.0.21"', source)
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

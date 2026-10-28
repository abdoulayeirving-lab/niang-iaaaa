import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CreatorIdentityPromptTests(unittest.TestCase):
    def test_windows_prompt_names_the_unique_creator_and_background(self):
        prompt = (ROOT / "core" / "prompt.txt").read_text(encoding="utf-8")

        self.assertIn("son unique créateur", prompt)
        self.assertIn("Sénégalais, étudiant et passionné par l’intelligence artificielle", prompt)
        self.assertIn("dans toutes les langues prises en charge", prompt)
        self.assertIn("Ne prétends pas qu'Abdoulaye Niang a créé le modèle", prompt)

    def test_android_prompt_matches_creator_identity(self):
        prompt = (
            ROOT
            / "android"
            / "app"
            / "src"
            / "main"
            / "java"
            / "com"
            / "kaizumi"
            / "remote"
            / "GeminiClient.kt"
        ).read_text(encoding="utf-8")

        self.assertIn("est l'unique créateur et développeur de NIANG IA", prompt)
        self.assertIn("dans la langue de la question", prompt)
        self.assertIn("Ne prétends pas qu'il a créé le modèle", prompt)

    def test_windows_fallback_prompt_preserves_creator_identity(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("its sole creator", source)
        self.assertIn("He is Senegalese, a student", source)
        self.assertIn("Do not claim he created", source)

    def test_windows_prompt_includes_truth_and_transparency_rules(self):
        prompt = (ROOT / "core" / "prompt.txt").read_text(encoding="utf-8")

        self.assertIn("HONNÊTETÉ ET VÉRITÉ", prompt)
        self.assertIn("Ne fabrique aucun fait", prompt)
        self.assertIn("Ne simule jamais une recherche", prompt)
        self.assertIn("code proposé, modifié, exécuté et réellement testé", prompt)
        self.assertIn("reconnais-le clairement", prompt)
        self.assertIn(
            "Je ne connais pas la réponse avec suffisamment de certitude.", prompt
        )

    def test_fallback_and_android_prompts_include_truth_rules(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        android_prompt = (
            ROOT
            / "android"
            / "app"
            / "src"
            / "main"
            / "java"
            / "com"
            / "kaizumi"
            / "remote"
            / "GeminiClient.kt"
        ).read_text(encoding="utf-8")

        self.assertIn("Never invent facts, sources, links, or results", source)
        self.assertIn("unless they ran", source)
        self.assertIn("Ne fabrique jamais de faits", android_prompt)
        self.assertIn("ne simule jamais une recherche", android_prompt)
        self.assertIn("Je ne connais pas la réponse avec suffisamment de certitude.", android_prompt)


if __name__ == "__main__":
    unittest.main()

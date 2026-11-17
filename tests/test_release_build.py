import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_release
from niang_ia.skills.catalog import ALL_SKILL_IDS, discover_skills


class ReleaseBuildTests(unittest.TestCase):
    def test_release_includes_opencode_and_curated_skills(self):
        release_files = {
            path.relative_to(build_release.ROOT).as_posix()
            for path in build_release.collect_files()
        }

        self.assertIn("actions/code_helper.py", release_files)
        self.assertIn(
            "niang_ia/integrations/opencode/opencode_engine.py",
            release_files,
        )
        self.assertIn(
            "niang_ia/integrations/opencode/opencode_health.py",
            release_files,
        )
        self.assertIn(
            "niang_ia/visual_assets/service.py",
            release_files,
        )
        self.assertIn(
            "niang_ia/integrations/opencode/opencode_tools_server.py",
            release_files,
        )
        self.assertIn(
            "niang_ia/integrations/cline/cline_worker.mjs",
            release_files,
        )
        self.assertIn(
            "web_design_skills/visual-asset-intelligence/SKILL.md",
            release_files,
        )
        self.assertIn(
            "web_design_skills/elite/clean-code-engineering/SKILL.md",
            release_files,
        )
        self.assertIn(
            "web_design_skills/elite/awwwards-level-web-design/SKILL.md",
            release_files,
        )
        self.assertNotIn(
            "web_design_skills/.legacy/README.md",
            release_files,
        )

    def test_release_excludes_local_secrets(self):
        release_files = {
            path.relative_to(build_release.ROOT).as_posix()
            for path in build_release.collect_files()
        }

        self.assertNotIn("config/api_keys.json", release_files)
        self.assertNotIn(".env", release_files)
        self.assertNotIn("config/guardian.json", release_files)

    def test_release_includes_every_registered_skill(self):
        release_files = {
            path.relative_to(build_release.ROOT).as_posix()
            for path in build_release.collect_files()
        }
        skills = discover_skills()

        self.assertEqual(set(skills), set(ALL_SKILL_IDS))
        for skill_id, skill in skills.items():
            relative_path = skill.source.relative_to(build_release.ROOT).as_posix()
            with self.subTest(skill=skill_id):
                self.assertIn(relative_path, release_files)


if __name__ == "__main__":
    unittest.main()

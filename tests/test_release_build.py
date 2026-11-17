import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import build_release


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


if __name__ == "__main__":
    unittest.main()

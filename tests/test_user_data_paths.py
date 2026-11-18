import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import user_data_paths


class UserDataPathsTests(unittest.TestCase):
    def test_migrates_legacy_directory_without_overwriting_user_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir) / "local"
            legacy_root = Path(temp_dir) / "install"
            legacy_memory = legacy_root / "memory"
            legacy_memory.mkdir(parents=True)
            (legacy_memory / "long_term.json").write_text(
                '{"identity":{"name":{"value":"Awa"}}}',
                encoding="utf-8",
            )

            target_memory = local_app_data / "NIANG IA" / "memory"
            target_memory.mkdir(parents=True)
            (target_memory / "long_term.json").write_text(
                '{"identity":{"name":{"value":"Aminata"}}}',
                encoding="utf-8",
            )
            (legacy_memory / "installer_profile.json").write_text(
                '{"identity":{"language":{"value":"Wolof"}}}',
                encoding="utf-8",
            )

            with mock.patch.object(sys, "frozen", True, create=True), mock.patch.dict(
                os.environ, {"LOCALAPPDATA": str(local_app_data)}
            ):
                result = user_data_paths.persistent_directory(
                    "memory",
                    legacy_root=legacy_root,
                )

            self.assertEqual(result, target_memory)
            self.assertIn("Aminata", (result / "long_term.json").read_text(encoding="utf-8"))
            self.assertTrue((result / "installer_profile.json").is_file())

    def test_rejects_paths_outside_the_user_data_root(self):
        with self.assertRaises(ValueError):
            user_data_paths.persistent_path("../outside.json")

    def test_migrates_legacy_file_only_when_no_user_copy_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_app_data = Path(temp_dir) / "local"
            legacy_root = Path(temp_dir) / "install"
            legacy_config = legacy_root / "config"
            legacy_config.mkdir(parents=True)
            (legacy_config / "installer_gemini_key.txt").write_text(
                "legacy-key",
                encoding="utf-8",
            )

            with mock.patch.object(sys, "frozen", True, create=True), mock.patch.dict(
                os.environ, {"LOCALAPPDATA": str(local_app_data)}
            ):
                destination = user_data_paths.persistent_path(
                    "config/installer_gemini_key.txt",
                    legacy_root=legacy_root,
                )
                self.assertEqual(destination.read_text(encoding="utf-8"), "legacy-key")

                destination.write_text("current-key", encoding="utf-8")
                (legacy_config / "installer_gemini_key.txt").write_text(
                    "stale-key",
                    encoding="utf-8",
                )
                user_data_paths.persistent_path(
                    "config/installer_gemini_key.txt",
                    legacy_root=legacy_root,
                )

            self.assertEqual(destination.read_text(encoding="utf-8"), "current-key")


if __name__ == "__main__":
    unittest.main()

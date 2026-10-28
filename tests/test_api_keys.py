"""Tests for api_keys.py — multi-key loading + env var support.

Uses temp config files so the user's real config/api_keys.json is untouched.
Run: python -m unittest tests.test_api_keys -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api_keys


class ApiKeysTest(unittest.TestCase):

    def setUp(self):
        self._old_path = api_keys.CONFIG_PATH
        self._old_installer_key_path = api_keys.INSTALLER_KEY_PATH
        fd, key_path = tempfile.mkstemp(suffix=".txt")
        os.close(fd)
        os.remove(key_path)
        api_keys.INSTALLER_KEY_PATH = Path(key_path)
        self.addCleanup(
            lambda: os.path.exists(key_path) and os.remove(key_path)
        )
        self._old_env_key = os.environ.get("KAIZUMI_GEMINI_API_KEY")
        self._old_env_keys = os.environ.get("KAIZUMI_GEMINI_API_KEYS")
        if self._old_env_key is None:
            os.environ.pop("KAIZUMI_GEMINI_API_KEY", None)
        if self._old_env_keys is None:
            os.environ.pop("KAIZUMI_GEMINI_API_KEYS", None)

    def tearDown(self):
        api_keys.CONFIG_PATH = self._old_path
        api_keys.INSTALLER_KEY_PATH = self._old_installer_key_path
        for name in ("KAIZUMI_GEMINI_API_KEY", "KAIZUMI_GEMINI_API_KEYS"):
            if name == "KAIZUMI_GEMINI_API_KEY" and self._old_env_key is not None:
                os.environ[name] = self._old_env_key
            elif name == "KAIZUMI_GEMINI_API_KEYS" and self._old_env_keys is not None:
                os.environ[name] = self._old_env_keys
            else:
                os.environ.pop(name, None)

    def _write_config(self, data):
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            import json
            json.dump(data, f)
        api_keys.CONFIG_PATH = Path(os.path.abspath(path))
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

    def test_loads_single_key(self):
        self._write_config({"gemini_api_key": "AIzaA"})
        self.assertEqual(api_keys.get_all_keys(), ["AIzaA"])

    def test_loads_multi_key_dedup(self):
        self._write_config({
            "gemini_api_key": "AIzaA",
            "gemini_api_keys": ["AIzaB", "AIzaA"],
        })
        self.assertEqual(api_keys.get_all_keys(), ["AIzaA", "AIzaB"])

    def test_env_key_included(self):
        self._write_config({"gemini_api_key": "AIzaA"})
        os.environ["KAIZUMI_GEMINI_API_KEY"] = "AIzaEnv"
        self.assertIn("AIzaEnv", api_keys.get_all_keys())

    def test_env_list_included(self):
        self._write_config({"gemini_api_key": "AIzaA"})
        os.environ["KAIZUMI_GEMINI_API_KEYS"] = "AIzaEnv1,AIzaEnv2"
        keys = api_keys.get_all_keys()
        self.assertIn("AIzaEnv1", keys)
        self.assertIn("AIzaEnv2", keys)

    def test_no_keys_raises(self):
        self._write_config({})
        with self.assertRaises(KeyError):
            api_keys.next_key()

    def test_loads_installer_key(self):
        self._write_config({})
        api_keys.INSTALLER_KEY_PATH.write_text("AIzaInstaller", encoding="utf-8")

        self.assertEqual(api_keys.get_all_keys(), ["AIzaInstaller"])

    def test_installer_key_takes_priority_over_existing_config_key(self):
        self._write_config({"gemini_api_key": "existing-key"})
        api_keys.INSTALLER_KEY_PATH.write_text("new-key", encoding="utf-8")

        self.assertEqual(api_keys.get_all_keys(), ["new-key", "existing-key"])

    def test_add_key_accepts_api_key_without_legacy_prefix(self):
        self._write_config({})

        self.assertEqual(api_keys.add_key("AQexample-new-key-format"), 1)
        self.assertEqual(api_keys.get_all_keys(), ["AQexample-new-key-format"])

    def test_api_key_without_legacy_prefix_reaches_gemini_client(self):
        self._write_config({})
        api_keys.INSTALLER_KEY_PATH.write_text(
            "AQexample-new-key-format", encoding="utf-8"
        )
        response = object()
        client = mock.Mock()
        client.models.generate_content.return_value = response

        with mock.patch("google.genai.Client", return_value=client) as create_client:
            result = api_keys.generate_with_retry(
                "gemini-test", "test request"
            )

        self.assertIs(result, response)
        create_client.assert_called_once_with(api_key="AQexample-new-key-format")
        client.models.generate_content.assert_called_once_with(
            model="gemini-test", contents="test request", config=None
        )


if __name__ == "__main__":
    unittest.main()
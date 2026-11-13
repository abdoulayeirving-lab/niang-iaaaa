"""Tests for memory/memory_manager.py — CRUD, pruning, secret filtering.

Uses a temp file so the user's real memory/long_term.json is never touched.
Run: python -m unittest tests.test_memory -v
"""

import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import memory.memory_manager as mm


class MemoryTest(unittest.TestCase):

    def setUp(self):
        fd, self.tmp = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        with open(self.tmp, "w", encoding="utf-8") as f:
            import json
            json.dump({}, f)
        mm.MEMORY_PATH = mm.Path(self.tmp)
        mm.INSTALLER_PROFILE_PATH = mm.Path(self.tmp + ".installer_profile.json")
        mm.CONVERSATION_DB_PATH = mm.Path(self.tmp + ".conversations.sqlite3")
        mm.ARCHIVE_PATH = mm.Path(self.tmp + ".archive.json")
        mm.BACKUP_DIR = mm.Path(self.tmp + ".backups")

    def tearDown(self):
        for path in (
            mm.MEMORY_PATH,
            mm.INSTALLER_PROFILE_PATH,
            mm.CONVERSATION_DB_PATH,
            mm.Path(f"{mm.CONVERSATION_DB_PATH}-wal"),
            mm.Path(f"{mm.CONVERSATION_DB_PATH}-shm"),
            mm.ARCHIVE_PATH,
            mm.Path(self.tmp + ".conversations.sqlite3.tmp"),
        ):
            path.unlink(missing_ok=True)
        if mm.BACKUP_DIR.exists():
            import shutil
            shutil.rmtree(mm.BACKUP_DIR)

    def test_remember_and_search(self):
        mm.remember("favorite_food", "pizza", "preferences")
        self.assertIn("pizza", mm.search_memory("pizza"))

    def test_forget(self):
        mm.remember("favorite_food", "pizza", "preferences")
        res = mm.forget("favorite_food", "preferences")
        self.assertIn("Forgotten", res)
        result = mm.search_memory("pizza")
        self.assertIn("don't have anything", result.lower())

    def test_clear_all(self):
        mm.remember("favorite_food", "pizza", "preferences")
        mm.remember("name", "Ali", "identity")
        res = mm.clear_memory()
        self.assertIn("All memory cleared", res)
        self.assertEqual(mm.load_memory()["preferences"], {})
        self.assertEqual(mm.load_memory()["identity"], {})

    def test_secrets_never_stored(self):
        mm.remember("api_key", "test-api-key-placeholder", "notes")
        mm.remember("wifi_password", "hunter2secret", "notes")
        mem = mm.load_memory()
        self.assertNotIn("api_key", mem["notes"])
        self.assertNotIn("wifi_password", mem["notes"])

    def test_prune_keeps_recent(self):
        for i in range(50):
            mm.remember(f"key_{i}", f"value_{i}", "notes")
        mem = mm.load_memory()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            archive_path = Path(tmp.name)
        try:
            with patch.object(mm, "ARCHIVE_PATH", archive_path):
                mm.prune_memory(mem, cap=40)
        finally:
            archive_path.unlink(missing_ok=True)
        self.assertLessEqual(len(mem["notes"]), 40)

    def test_truncate_long_values(self):
        mm.remember("long_note", "x" * 500, "notes")
        mem = mm.load_memory()
        val = mem["notes"]["long_note"]["value"]
        self.assertLessEqual(len(val), mm.MAX_VALUE_LENGTH + 1)

    def test_import_installer_profile_into_existing_memory(self):
        mm.remember("favorite_color", "blue", "preferences")
        mm.INSTALLER_PROFILE_PATH.write_text(
            '{"identity":{"name":{"value":"Awa"},'
            '"language":{"value":"Wolof"}},'
            '"preferences":{"response_style":{"value":"brief"}}}',
            encoding="utf-8",
        )

        memory = mm.load_memory()

        self.assertEqual(memory["identity"]["name"]["value"], "Awa")
        self.assertEqual(memory["identity"]["language"]["value"], "Wolof")
        self.assertEqual(memory["preferences"]["favorite_color"]["value"], "blue")
        self.assertEqual(memory["preferences"]["response_style"]["value"], "brief")
        self.assertFalse(mm.INSTALLER_PROFILE_PATH.exists())
        self.assertEqual(
            json.loads(mm.MEMORY_PATH.read_text(encoding="utf-8"))["identity"]["name"]["value"],
            "Awa",
        )

    def test_invalid_installer_profile_is_not_deleted(self):
        mm.INSTALLER_PROFILE_PATH.write_text("{invalid", encoding="utf-8")

        memory = mm.load_memory()

        self.assertEqual(memory["identity"], {})
        self.assertTrue(mm.INSTALLER_PROFILE_PATH.exists())

    def test_conversation_archive_is_persistent_and_searchable(self):
        mm.archive_conversation(
            "My sister Amira starts her architecture course in September.",
            "I will remember that Amira starts architecture in September.",
        )

        result = mm.search_memory("sister Amira architecture")

        self.assertIn("Relevant past conversations", result)
        self.assertIn("architecture course in September", result)
        self.assertIn("I will remember", result)

    def test_transcript_archive_redacts_secrets(self):
        mm.archive_conversation(
            "My password is Hunter2! and my favorite color is green.",
            "Your API key is AIza123456789012345678901234.",
        )

        result = mm.search_memory("favorite color green")

        self.assertIn("favorite color is green", result)
        self.assertNotIn("Hunter2!", result)
        self.assertNotIn("AIza123456789012345678901234", result)

    def test_forget_redacts_matching_transcripts(self):
        mm.remember("favorite_color", "teal", "preferences")
        mm.archive_conversation(
            "I love teal and prefer quiet mornings.",
            "I will remember that you love teal.",
        )

        mm.forget("favorite_color", "preferences")

        result = mm.search_memory("teal")
        self.assertNotIn("Relevant past conversations", result)
        self.assertIn("quiet mornings", mm.search_memory("quiet mornings"))

    def test_forget_redacts_accented_details_case_insensitively(self):
        mm.remember("friend_name", "Élodie", "relationships")
        mm.archive_conversation(
            "My friend élodie visited last weekend.",
            "I will remember your friend Élodie.",
        )

        mm.forget("friend_name", "relationships")

        self.assertNotIn("Relevant past conversations", mm.search_memory("élodie"))

    def test_forget_removes_archived_facts_and_backups(self):
        mm.remember("favorite_color", "teal", "preferences")
        mm.ARCHIVE_PATH.write_text(
            json.dumps({"preferences": {"favorite_color": {"value": "teal"}}}),
            encoding="utf-8",
        )

        mm.forget("favorite_color", "preferences")

        self.assertNotIn("favorite_color", mm.load_memory()["preferences"])
        self.assertNotIn("preferences/favorite_color", mm.search_memory("teal"))
        for backup in mm.BACKUP_DIR.glob("long_term_*.json"):
            saved = json.loads(backup.read_text(encoding="utf-8"))
            self.assertNotIn("favorite_color", saved.get("preferences", {}))
        archived = json.loads(mm.ARCHIVE_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("favorite_color", archived.get("preferences", {}))

    def test_clear_category_removes_archived_facts_and_backups(self):
        mm.remember("favorite_color", "teal", "preferences")
        mm.ARCHIVE_PATH.write_text(
            json.dumps({"preferences": {"favorite_food": {"value": "pizza"}}}),
            encoding="utf-8",
        )

        mm.clear_memory("preferences")

        self.assertNotIn("preferences/favorite_color", mm.search_memory("teal"))
        self.assertNotIn("preferences/favorite_food", mm.search_memory("pizza"))
        for backup in mm.BACKUP_DIR.glob("long_term_*.json"):
            saved = json.loads(backup.read_text(encoding="utf-8"))
            self.assertNotIn("preferences", saved)
        archived = json.loads(mm.ARCHIVE_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("preferences", archived)

    def test_clear_all_memory_removes_transcripts_and_backups(self):
        mm.remember("favorite_food", "pizza", "preferences")
        mm.archive_conversation("I like pizza.", "I will remember that.")
        mm.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        (mm.BACKUP_DIR / "long_term_test.json").write_text("{}", encoding="utf-8")

        result = mm.clear_memory()

        self.assertIn("All memory cleared", result)
        self.assertEqual(mm.search_memory("pizza"), "I don't have anything saved matching 'pizza', sir.")
        self.assertFalse(any(mm.BACKUP_DIR.glob("long_term_*.json")))

    def test_clear_conversations_keeps_structured_facts(self):
        mm.remember("favorite_food", "pizza", "preferences")
        mm.archive_conversation("I like pizza.", "I will remember that.")

        mm.clear_memory("conversations")

        self.assertIn("preferences/favorite_food: pizza", mm.search_memory("pizza"))
        self.assertNotIn("Relevant past conversations", mm.search_memory("pizza"))


if __name__ == "__main__":
    unittest.main()
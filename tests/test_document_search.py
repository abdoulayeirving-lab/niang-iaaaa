import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from actions import document_qa


class DocumentSearchTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def test_search_returns_ranked_excerpt_and_disclosure(self):
        (self.root / "plan.txt").write_text(
            "The launch plan has milestones for launch readiness. "
            "Launch review happens on Friday.",
            encoding="utf-8",
        )
        (self.root / "notes.md").write_text(
            "Launch planning notes.",
            encoding="utf-8",
        )

        result = document_qa.search_documents({
            "query": "launch readiness",
            "folder": str(self.root),
        })

        self.assertIn("plan.txt", result)
        self.assertIn("notes.md", result)
        self.assertIn("Matching excerpts are shared with Gemini", result)
        self.assertLess(result.index("plan.txt"), result.index("notes.md"))

    def test_search_only_checks_supported_files_in_requested_folder(self):
        (self.root / "match.txt").write_text("private topic result", encoding="utf-8")
        (self.root / "ignored.exe").write_text("private topic result", encoding="utf-8")
        other = self.root / "other"
        other.mkdir()
        (other / "nested.txt").write_text("private topic result", encoding="utf-8")

        with patch.object(document_qa, "_MAX_SEARCH_FILES", 1):
            result = document_qa.search_documents({
                "query": "private topic",
                "folder": str(self.root),
            })

        self.assertIn("match.txt", result)
        self.assertNotIn("ignored.exe", result)
        self.assertIn("Scan limit reached (1 files)", result)

    def test_rejects_missing_folder_and_short_query(self):
        missing = document_qa.search_documents({
            "query": "anything",
            "folder": str(self.root / "missing"),
        })
        short = document_qa.search_documents({"query": "x", "folder": str(self.root)})

        self.assertIn("Folder not found", missing)
        self.assertIn("at least two characters", short)

    def test_search_skips_oversized_files_and_reports_them(self):
        large = self.root / "large.txt"
        large.write_text("keyword", encoding="utf-8")
        with patch.object(document_qa, "_MAX_SEARCH_FILE_BYTES", 1):
            result = document_qa.search_documents({
                "query": "keyword",
                "folder": str(self.root),
            })
        self.assertIn("No matching documents", result)
        self.assertIn("Skipped 1 unreadable or oversized", result)


if __name__ == "__main__":
    unittest.main()

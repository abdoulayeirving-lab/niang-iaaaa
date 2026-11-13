"""Tests for Niang IA Cline CLI integration."""

import os
import sys
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from niang_ia.integrations.cline.cline_manager import (
    find_cline_binary,
    get_cline_version,
    check_cline_available,
    ClineTask,
    ClineManager,
    redact_secrets,
)


class TestClineDetection(unittest.TestCase):
    """Test Cline CLI detection."""

    def test_find_cline_binary_returns_path(self):
        binary = find_cline_binary()
        self.assertIsNotNone(binary)

    def test_check_cline_available(self):
        result = check_cline_available()
        self.assertTrue(result["available"])
        self.assertIsNotNone(result["version"])
        self.assertIsNone(result["error"])

    def test_get_cline_version(self):
        version = get_cline_version()
        self.assertIsNotNone(version)
        self.assertTrue(version[0].isdigit())


class TestClineTask(unittest.TestCase):
    """Test ClineTask dataclass."""

    def test_task_creation(self):
        task = ClineTask(
            task_id="test-1",
            goal="Test goal",
            working_dir="/tmp/test",
            timeout_seconds=60,
        )
        self.assertEqual(task.task_id, "test-1")
        self.assertEqual(task.goal, "Test goal")
        self.assertEqual(task.status, "pending")
        self.assertFalse(task.cancel_flag.is_set())

    def test_task_to_dict(self):
        task = ClineTask(
            task_id="test-2",
            goal="Test goal 2",
            working_dir="/tmp/test2",
        )
        d = task.to_dict()
        self.assertEqual(d["task_id"], "test-2")
        self.assertEqual(d["status"], "pending")
        self.assertIsNone(d["duration_seconds"])


class TestClineManager(unittest.TestCase):
    """Test ClineManager."""

    def test_manager_creation(self):
        manager = ClineManager()
        self.assertTrue(manager.is_available())

    def test_start_task_returns_task(self):
        manager = ClineManager()
        task = manager.start_task(
            goal="Test task",
            working_dir=os.getcwd(),
            timeout_seconds=5,
            auto_approve=False,
        )
        self.assertIsNotNone(task.task_id)
        self.assertEqual(task.goal, "Test task")
        # Status may be pending, running, or completed depending on timing
        self.assertIn(task.status, ("pending", "running", "completed", "failed"))

    def test_cancel_task(self):
        manager = ClineManager()
        task = manager.start_task(
            goal="Long running task",
            working_dir=os.getcwd(),
            timeout_seconds=60,
            auto_approve=False,
        )
        result = manager.cancel_task(task.task_id)
        self.assertTrue(result)
        self.assertEqual(task.status, "cancelled")

    def test_get_task(self):
        manager = ClineManager()
        task = manager.start_task(
            goal="Test task",
            working_dir=os.getcwd(),
            timeout_seconds=5,
        )
        retrieved = manager.get_task(task.task_id)
        self.assertEqual(retrieved.task_id, task.task_id)

    def test_redact_secrets(self):
        text = "api_key=secret123 token=abc123"
        redacted = redact_secrets(text)
        self.assertNotIn("secret123", redacted)
        self.assertNotIn("abc123", redacted)


if __name__ == "__main__":
    unittest.main()

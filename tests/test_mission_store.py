import base64
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent import mission_store
from agent.task_queue import Task, TaskQueue, TaskStatus


class MissionStoreTests(unittest.TestCase):
    def test_temporary_mission_interrupted_on_restart_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            store = mission_store.MissionStore(Path(directory) / "missions.db")
            task_id = "phase3-integration-1"
            store.save(
                task_id,
                "running",
                {
                    "goal": "Inoffensive temporary recovery test",
                    "phase": "running",
                    "current_step": "No action is replayed",
                    "completed_steps": 0,
                    "total_steps": 0,
                    "action_history": [],
                },
            )

            store.save(
                task_id,
                "interrupted",
                {
                    "goal": "Inoffensive temporary recovery test",
                    "phase": "interrupted",
                    "current_step": "Application closed during the simulated test",
                    "completed_steps": 0,
                    "total_steps": 0,
                    "action_history": [],
                },
            )

            restarted_queue = TaskQueue(persist=True)
            restarted_queue._mission_store = mission_store.MissionStore(
                Path(directory) / "missions.db"
            )
            with patch("agent.settings.artifact_retention_days", return_value=30):
                restarted_queue._restore_missions()

            restored = restarted_queue.get_status(task_id)
            self.assertEqual(restored["status"], TaskStatus.INTERRUPTED.value)
            self.assertEqual(restored["action_history"], [])
            self.assertFalse(restarted_queue._worker_thread)
    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI is required.")
    def test_windows_dpapi_round_trips_mission_payload(self):
        private_payload = b"private mission content"
        encrypted = mission_store._protect(private_payload)

        self.assertNotIn(private_payload, encrypted)
        self.assertEqual(mission_store._unprotect(encrypted), private_payload)

    def test_payload_is_encrypted_in_sqlite_and_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missions.db"
            store = mission_store.MissionStore(path)
            protector = lambda value: b"encrypted:" + base64.b64encode(value)
            unprotector = lambda value: base64.b64decode(
                value.removeprefix(b"encrypted:")
            )
            with (
                patch.object(mission_store, "_protect", side_effect=protector),
                patch.object(mission_store, "_unprotect", side_effect=unprotector),
            ):
                store.save("mission-1", "running", {"goal": "private mission"})
                connection = sqlite3.connect(path)
                try:
                    stored = connection.execute(
                        "SELECT payload FROM missions WHERE task_id = ?",
                        ("mission-1",),
                    ).fetchone()[0]
                finally:
                    connection.close()
                self.assertNotIn(b"private mission", stored)
                self.assertEqual(
                    store.load_all()[0]["payload"]["goal"],
                    "private mission",
                )

    def test_restore_marks_in_flight_mission_interrupted(self):
        class FakeStore:
            def __init__(self):
                self.saved = []

            def prune_terminal(self, _days):
                return 0

            def load_all(self):
                return [{
                    "task_id": "mission-2",
                    "status": "running",
                    "payload": {
                        "goal": "Continue safely",
                        "current_step": "2: verify result",
                        "completed_steps": 1,
                        "total_steps": 2,
                        "action_history": [],
                    },
                }]

            def save(self, *args):
                self.saved.append(args)

        fake_store = FakeStore()
        queue = TaskQueue(persist=True)
        queue._mission_store = fake_store
        with patch("agent.settings.artifact_retention_days", return_value=30):
            queue._restore_missions()

        restored = queue.get_status("mission-2")
        self.assertEqual(restored["status"], TaskStatus.INTERRUPTED.value)
        self.assertIn("Review its history", restored["error"])
        self.assertEqual(fake_store.saved[0][1], TaskStatus.INTERRUPTED.value)

    def test_resume_requires_explicit_confirmation_and_does_not_copy_results(self):
        queue = TaskQueue()
        previous = Task(
            priority=2,
            created_at=1,
            task_id="interrupted-1",
            goal="Check the report status",
            status=TaskStatus.INTERRUPTED,
            action_history=[{
                "number": 1,
                "tool": "browser_control",
                "status": "unknown",
                "result": "sensitive page content",
            }],
        )
        queue._tasks[previous.task_id] = previous

        with self.assertRaises(ValueError):
            queue.resume_interrupted(
                previous.task_id,
                user_confirmed=False,
            )

        resumed_id = queue.resume_interrupted(
            previous.task_id,
            user_confirmed=True,
        )
        resumed = queue._tasks[resumed_id]
        self.assertEqual(resumed.goal, previous.goal)
        self.assertIn("verify", resumed.resume_context)
        self.assertNotIn("sensitive page content", resumed.resume_context)


if __name__ == "__main__":
    unittest.main()

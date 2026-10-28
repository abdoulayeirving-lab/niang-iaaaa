import unittest
from unittest.mock import patch

from agent.task_queue import Task, TaskQueue, TaskStatus
from agent.executor import AgentExecutor


class TaskProgressTest(unittest.TestCase):
    def test_progress_updates_are_visible_in_status(self):
        queue = TaskQueue()
        task = Task(priority=2, created_at=1.0, task_id="abc12345", goal="research")
        task.status = TaskStatus.RUNNING
        queue._tasks[task.task_id] = task

        queue._update_progress(task, {
            "phase": "running",
            "current_step": "2: Save the results",
            "completed_steps": 1,
            "total_steps": 3,
        })

        status = queue.get_status(task.task_id)
        self.assertEqual(status["phase"], "running")
        self.assertEqual(status["current_step"], "2: Save the results")
        self.assertEqual(status["completed_steps"], 1)
        self.assertEqual(status["total_steps"], 3)

    def test_terminal_tasks_ignore_late_progress(self):
        queue = TaskQueue()
        task = Task(priority=2, created_at=1.0, task_id="abc12345", goal="research")
        task.status = TaskStatus.COMPLETED
        queue._tasks[task.task_id] = task

        queue._update_progress(task, {
            "phase": "running",
            "current_step": "late update",
            "completed_steps": 1,
            "total_steps": 2,
        })

        self.assertEqual(queue.get_status(task.task_id)["phase"], "queued")
        self.assertEqual(queue.get_status(task.task_id)["current_step"], "")

    def test_executor_reports_step_and_completion_progress(self):
        events = []
        plan = {
            "steps": [{
                "step": 1,
                "tool": "web_search",
                "description": "Find the answer",
                "parameters": {"query": "answer"},
            }]
        }
        with (
            patch("agent.executor.create_plan", return_value=plan),
            patch("agent.executor._call_tool_with_timeout", return_value="Found it"),
            patch.object(AgentExecutor, "_summarize", return_value="Completed."),
        ):
            result = AgentExecutor().execute("research", on_progress=events.append)

        self.assertEqual(result, "Completed.")
        self.assertEqual(events[0]["phase"], "planned")
        self.assertEqual(events[1]["current_step"], "1: Find the answer")
        self.assertEqual(events[-1]["phase"], "completed")
        self.assertEqual(events[-1]["completed_steps"], 1)


if __name__ == "__main__":
    unittest.main()

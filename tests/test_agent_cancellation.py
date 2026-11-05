import threading
import time
import unittest
from unittest.mock import patch

from agent import executor
from agent.task_queue import Task, TaskQueue, TaskStatus


class AgentCancellationTests(unittest.TestCase):
    def test_tool_timeout_returns_without_waiting_for_a_stuck_action(self):
        started = threading.Event()
        release = threading.Event()

        def stuck_action(*_args):
            started.set()
            release.wait(timeout=2)
            return "finished"

        lock = threading.Lock()
        with (
            patch.object(executor, "_TOOL_EXECUTION_LOCK", lock),
            patch("agent.settings.action_timeout_seconds", return_value=0.05),
            patch.object(executor, "_call_tool", side_effect=stuck_action),
        ):
            start = time.monotonic()
            with self.assertRaises(executor.ToolTimeoutError):
                executor._call_tool_with_timeout("test_tool", {}, None)
            self.assertTrue(started.wait(timeout=1))
            self.assertLess(time.monotonic() - start, 0.5)

            with self.assertRaises(executor.ToolExecutionBusyError):
                executor._call_tool_with_timeout("test_tool", {}, None)

            release.set()
            deadline = time.monotonic() + 1
            while lock.locked() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(lock.locked())

    def test_cancelled_in_flight_action_does_not_dispatch_another_action(self):
        started = threading.Event()
        release = threading.Event()
        cancel_flag = threading.Event()

        def stuck_action(*_args):
            started.set()
            release.wait(timeout=2)
            return "finished"

        lock = threading.Lock()
        with (
            patch.object(executor, "_TOOL_EXECUTION_LOCK", lock),
            patch.object(executor, "_call_tool", side_effect=stuck_action) as call,
        ):
            def cancel_when_started():
                self.assertTrue(started.wait(timeout=1))
                cancel_flag.set()

            canceller = threading.Thread(target=cancel_when_started, daemon=True)
            canceller.start()
            start = time.monotonic()
            with self.assertRaises(executor.MissionCancelled):
                executor._call_tool_with_timeout(
                    "test_tool",
                    {},
                    None,
                    cancel_flag=cancel_flag,
                )
            self.assertLess(time.monotonic() - start, 0.5)
            with self.assertRaises(executor.ToolExecutionBusyError):
                executor._call_tool_with_timeout("second_tool", {}, None)
            call.assert_called_once()

            release.set()
            canceller.join(timeout=1)
            deadline = time.monotonic() + 1
            while lock.locked() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(lock.locked())

    def test_cancelled_mission_never_enters_a_sensitive_tool(self):
        cancel_flag = threading.Event()
        cancel_flag.set()
        approval = unittest.mock.Mock(return_value=True)

        with patch("actions.browser_control.browser_control") as browser:
            with self.assertRaises(executor.MissionCancelled):
                executor._call_tool(
                    "browser_control",
                    {"action": "submit_form", "description": "Submit order"},
                    None,
                    approval_callback=approval,
                    cancel_flag=cancel_flag,
                )

        approval.assert_not_called()
        browser.assert_not_called()

    def test_cancel_during_planning_prevents_first_tool_dispatch(self):
        cancel_flag = threading.Event()
        plan = {
            "steps": [{
                "step": 1,
                "tool": "web_search",
                "description": "Search",
                "parameters": {"query": "example"},
            }]
        }

        def finish_planning(*_args, **_kwargs):
            cancel_flag.set()
            return plan

        with (
            patch("agent.settings.mission_timeout_seconds", return_value=60),
            patch("agent.executor.create_plan", side_effect=finish_planning),
            patch("agent.executor._call_tool_with_timeout") as call_tool,
        ):
            with self.assertRaises(executor.MissionCancelled):
                executor.AgentExecutor().execute(
                    "Search for an example.",
                    cancel_flag=cancel_flag,
                )

        call_tool.assert_not_called()

    def test_expired_deadline_does_not_dispatch_tool(self):
        with (
            patch.object(executor, "_TOOL_EXECUTION_LOCK", threading.Lock()),
            patch("agent.settings.action_timeout_seconds", return_value=1),
            patch.object(executor, "_call_tool") as call_tool,
        ):
            with self.assertRaises(executor.MissionDeadlineExceeded):
                executor._call_tool_with_timeout(
                    "web_search",
                    {"query": "example"},
                    None,
                    timeout_s=0,
                )

        call_tool.assert_not_called()

    def test_running_task_remains_cancelled_when_executor_raises(self):
        queue = TaskQueue()
        task = Task(
            priority=2,
            created_at=time.time(),
            task_id="cancelled-task",
            goal="Stop this mission",
            status=TaskStatus.RUNNING,
            cancel_flag=threading.Event(),
        )
        task.cancel_flag.set()
        queue._tasks[task.task_id] = task
        queue._active_count = 1
        fake_executor = unittest.mock.Mock()
        fake_executor.execute.side_effect = executor.MissionCancelled("Cancelled")

        with patch.object(queue, "_get_executor", return_value=fake_executor):
            queue._run_task(task)

        self.assertEqual(task.status, TaskStatus.CANCELLED)
        self.assertEqual(task.phase, "cancelled")
        self.assertEqual(task.error, "")
        self.assertEqual(queue._active_count, 0)


if __name__ == "__main__":
    unittest.main()

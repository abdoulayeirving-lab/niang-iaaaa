import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Any


class TaskStatus(Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    STOP_REQUESTED = "stop_requested"
    COMPLETED  = "completed"
    PARTIAL = "partial"
    FAILED     = "failed"
    ACTION_UNKNOWN = "action_unknown"
    CANCELLED  = "cancelled"
    INTERRUPTED = "interrupted"


class TaskPriority(Enum):
    LOW    = 3
    NORMAL = 2
    HIGH   = 1   


@dataclass(order=True)
class Task:
    priority:    int                       
    created_at:  float = field(compare=False)
    task_id:     str   = field(compare=False)
    goal:        str   = field(compare=False)
    status:      TaskStatus = field(compare=False, default=TaskStatus.PENDING)
    result:      Any        = field(compare=False, default=None)
    outcome: str = field(compare=False, default="pending")
    verified: bool = field(compare=False, default=False)
    error:       str        = field(compare=False, default="")
    speak:       Any        = field(compare=False, default=None)   
    on_complete: Any        = field(compare=False, default=None)  
    cancel_flag: threading.Event = field(compare=False, default_factory=threading.Event)
    phase:       str         = field(compare=False, default="queued")
    current_step: str        = field(compare=False, default="")
    completed_steps: int     = field(compare=False, default=0)
    total_steps: int         = field(compare=False, default=0)
    action_history: list[dict] = field(compare=False, default_factory=list)
    approval_callback: Any = field(compare=False, default=None)
    resume_context: str = field(compare=False, default="")
    tool_registry: Any = field(compare=False, default=None)


class TaskQueue:
    def __init__(self, max_concurrent: int = 1, persist: bool = False):
        self._queue:        list[Task]       = []
        self._lock:         threading.Lock   = threading.Lock()
        self._condition:    threading.Condition = threading.Condition(self._lock)
        self._tasks:        dict[str, Task]  = {} 
        self._running:      bool             = False
        self._worker_thread: threading.Thread | None = None
        self._max_concurrent = max_concurrent
        self._active_count   = 0
        self._executor       = None  
        self._persist = persist
        self._mission_store = None
        self._tool_registry = None

    def set_tool_registry(self, registry) -> None:
        if registry is None:
            raise ValueError("A tool registry is required.")
        with self._lock:
            self._tool_registry = registry
            for task in self._tasks.values():
                if task.status in (TaskStatus.PENDING, TaskStatus.INTERRUPTED):
                    task.tool_registry = registry

    def _get_mission_store(self):
        if not self._persist:
            return None
        if self._mission_store is None:
            from agent.mission_store import MissionStore
            self._mission_store = MissionStore()
        return self._mission_store

    @staticmethod
    def _task_payload(task: Task) -> dict:
        return {
            "goal": task.goal,
            "result": task.result,
            "outcome": task.outcome,
            "verified": task.verified,
            "error": task.error,
            "phase": task.phase,
            "current_step": task.current_step,
            "completed_steps": task.completed_steps,
            "total_steps": task.total_steps,
            "action_history": task.action_history[-50:],
            "resume_context": task.resume_context,
        }

    def _persist_task(self, task: Task, *, required: bool = False) -> None:
        store = self._get_mission_store()
        if store is None:
            return
        try:
            store.save(task.task_id, task.status.value, self._task_payload(task))
            if task.status in {
                TaskStatus.COMPLETED,
                TaskStatus.PARTIAL,
                TaskStatus.FAILED,
                TaskStatus.ACTION_UNKNOWN,
                TaskStatus.CANCELLED,
                TaskStatus.INTERRUPTED,
            }:
                from agent.settings import artifact_retention_days
                store.prune_terminal(artifact_retention_days())
        except Exception as exc:
            if required:
                raise
            print(f"[TaskQueue] Mission persistence failed: {type(exc).__name__}")

    def _restore_missions(self) -> None:
        store = self._get_mission_store()
        if store is None:
            return
        from agent.settings import artifact_retention_days
        store.prune_terminal(artifact_retention_days())
        with self._lock:
            for record in store.load_all():
                stored_status = record["status"]
                if stored_status not in {status.value for status in TaskStatus}:
                    continue
                in_flight = stored_status in {
                    TaskStatus.PENDING.value,
                    TaskStatus.RUNNING.value,
                    TaskStatus.STOP_REQUESTED.value,
                }
                payload = record["payload"]
                status = (
                    TaskStatus.INTERRUPTED if in_flight
                    else TaskStatus(stored_status)
                )
                task = Task(
                    priority=TaskPriority.NORMAL.value,
                    created_at=time.time(),
                    task_id=record["task_id"],
                    goal=payload.get("goal", ""),
                    status=status,
                    result=payload.get("result"),
                    outcome=(
                        "interrupted" if in_flight
                        else payload.get("outcome", stored_status)
                    ),
                    verified=bool(payload.get("verified", False)),
                    error=payload.get("error", ""),
                    phase=(
                        "interrupted" if in_flight
                        else payload.get("phase", stored_status)
                    ),
                    current_step=payload.get("current_step", ""),
                    completed_steps=payload.get("completed_steps", 0),
                    total_steps=payload.get("total_steps", 0),
                    action_history=payload.get("action_history", []),
                    resume_context=payload.get("resume_context", ""),
                    tool_registry=self._tool_registry,
                )
                if (
                    in_flight
                    and payload.get("current_step")
                ):
                    task.action_history.append({
                        "number": "?",
                        "tool": "unknown",
                        "description": "Action was in progress when the application closed.",
                        "result": "Outcome unknown; verify current state before continuing.",
                        "status": "unknown",
                    })
                if in_flight:
                    task.error = (
                        "Application closed before this mission completed. "
                        "Review its history before explicitly resuming."
                    )
                    store.save(
                        task.task_id,
                        task.status.value,
                        self._task_payload(task),
                    )
                self._tasks[task.task_id] = task

    def _get_executor(self):
        if self._executor is None:
            from agent.executor import AgentExecutor
            self._executor = AgentExecutor()
        return self._executor

    def start(self) -> None:
        if self._running:
            return
        self._restore_missions()
        self._running      = True
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="AgentTaskQueue"
        )
        self._worker_thread.start()
        print("[TaskQueue] ✅ Started")

    def stop(self) -> None:
        self._running = False
        with self._condition:
            self._condition.notify_all()
        print("[TaskQueue] 🔴 Stopped")

    def shutdown(self) -> None:
        with self._lock:
            active_ids = [
                task.task_id
                for task in self._tasks.values()
                if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING)
            ]
        for task_id in active_ids:
            self.cancel(task_id)
        self.stop()

    def submit(
        self,
        goal:        str,
        priority:    TaskPriority = TaskPriority.NORMAL,
        speak:       Callable | None = None,
        on_complete: Callable | None = None,
        approval_callback: Callable[[str, dict, str], bool] | None = None,
        resume_context: str = "",
        tool_registry=None,
    ) -> str:

        task_id = str(uuid.uuid4())[:8]
        task    = Task(
            priority    = priority.value,
            created_at  = time.time(),
            task_id     = task_id,
            goal        = goal,
            speak       = speak,
            on_complete = on_complete,
            approval_callback = approval_callback,
            resume_context = resume_context,
            tool_registry = tool_registry or self._tool_registry,
        )

        with self._condition:
            self._persist_task(task, required=True)
            self._queue.append(task)
            self._queue.sort(key=lambda t: (t.priority, t.created_at))
            self._tasks[task_id] = task
            self._condition.notify()

        print(f"[TaskQueue] Task queued: [{task_id}]")
        return task_id

    def cancel(self, task_id: str) -> bool:
        stop_computer_input = False
        stop_browser_action = False
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status in (
                TaskStatus.COMPLETED,
                TaskStatus.PARTIAL,
                TaskStatus.FAILED,
                TaskStatus.ACTION_UNKNOWN,
                TaskStatus.CANCELLED,
                TaskStatus.INTERRUPTED,
            ):
                return False

            stop_computer_input = task.status == TaskStatus.RUNNING
            task.cancel_flag.set()
            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.CANCELLED
                task.phase = "cancelled"
                task.current_step = ""
                task.outcome = "cancelled"
            else:
                task.status = TaskStatus.STOP_REQUESTED
                task.phase = "stop_requested"
                task.outcome = "stop_requested"
                stop_browser_action = True
            try:
                self._queue.remove(task)
            except ValueError:
                pass
            print(f"[TaskQueue] 🛑 Stop requested: [{task_id}]")
        if stop_browser_action:
            try:
                from actions.playwright_mcp import cancel_playwright_mcp_action
                cancel_playwright_mcp_action(task_id)
            except Exception as exc:
                print(f"[TaskQueue] Browser stop request failed: {exc}")
        if stop_computer_input:
            try:
                from actions.computer_control import computer_control
                computer_control({"action": "stop"})
            except Exception as exc:
                print(f"[TaskQueue] Emergency input stop failed: {exc}")
        self._persist_task(task)
        return True

    def cancel_all_active(self) -> list[str]:
        with self._lock:
            active_ids = [
                task.task_id
                for task in self._tasks.values()
                if task.status in (
                    TaskStatus.PENDING,
                    TaskStatus.RUNNING,
                    TaskStatus.STOP_REQUESTED,
                )
            ]
        return [task_id for task_id in active_ids if self.cancel(task_id)]

    def latest_interrupted(self) -> dict | None:
        with self._lock:
            candidates = [
                task for task in self._tasks.values()
                if task.status in (TaskStatus.INTERRUPTED, TaskStatus.ACTION_UNKNOWN)
            ]
            if not candidates:
                return None
            task = max(candidates, key=lambda item: item.created_at)
            return {
                "task_id": task.task_id,
                "goal": task.goal,
                "error": task.error,
                "action_history": [dict(item) for item in task.action_history],
            }

    def resume_interrupted(
        self,
        task_id: str,
        *,
        user_confirmed: bool,
        speak: Callable | None = None,
        on_complete: Callable | None = None,
        approval_callback: Callable[[str, dict, str], bool] | None = None,
    ) -> str:
        if not user_confirmed:
            raise ValueError("Mission recovery requires explicit user confirmation.")
        with self._lock:
            previous = self._tasks.get(task_id)
            if previous is None or previous.status not in (
                TaskStatus.INTERRUPTED,
                TaskStatus.ACTION_UNKNOWN,
            ):
                raise ValueError("The selected mission is not available for recovery.")
            history = [
                {
                    "number": item.get("number"),
                    "tool": item.get("tool"),
                    "status": item.get("status", "unknown"),
                }
                for item in previous.action_history[-50:]
            ]
            goal = previous.goal
        context = (
            "This is an explicitly user-approved recovery of a previously interrupted "
            "mission. The prior action metadata below is not proof that actions completed. "
            "Never replay an action merely because it appears in history. First inspect "
            "the current state and verify whether its effect already occurred. If the "
            "result cannot be verified safely, stop and ask the user. Prior action "
            "metadata (tool and status only): "
            + json.dumps(history, ensure_ascii=True)
        )
        return self.submit(
            goal,
            speak=speak,
            on_complete=on_complete,
            approval_callback=approval_callback,
            resume_context=context,
        )

    def get_status(self, task_id: str) -> dict | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            return {
                "task_id": task.task_id,
                "goal":    task.goal,
                "status":  task.status.value,
                "result":  task.result,
                "outcome": task.outcome,
                "verified": task.verified,
                "error":   task.error,
                "phase": task.phase,
                "current_step": task.current_step,
                "completed_steps": task.completed_steps,
                "total_steps": task.total_steps,
                "action_history": [dict(item) for item in task.action_history],
            }

    def get_all_statuses(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "task_id": t.task_id,
                    "goal":    t.goal[:50],
                    "status":  t.status.value,
                    "outcome": t.outcome,
                    "verified": t.verified,
                    "phase": t.phase,
                    "current_step": t.current_step,
                    "completed_steps": t.completed_steps,
                    "total_steps": t.total_steps,
                    "action_history": [dict(item) for item in t.action_history[-20:]],
                }
                for t in self._tasks.values()
            ]

    def pending_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._queue if t.status == TaskStatus.PENDING)

    def _worker_loop(self) -> None:
        while self._running:
            task = None

            with self._condition:
                while self._running and not self._next_task():
                    self._condition.wait(timeout=1.0)
                task = self._next_task()
                if task:
                    task.status = TaskStatus.RUNNING
                    task.phase = "planning"
                    self._active_count += 1
                    self._persist_task(task)
                    try:
                        self._queue.remove(task)
                    except ValueError:
                        pass

            if task:
                threading.Thread(
                    target=self._run_task,
                    args=(task,),
                    daemon=True,
                    name=f"AgentTask-{task.task_id}"
                ).start()

    def _next_task(self) -> Task | None:
        if self._active_count >= self._max_concurrent:
            return None
        for task in self._queue:
            if task.status == TaskStatus.PENDING and not task.cancel_flag.is_set():
                return task
        return None

    def _run_task(self, task: Task) -> None:
        print(f"[TaskQueue] Running: [{task.task_id}]")
        from agent.executor import ToolTimeoutError, wait_for_tool_idle

        try:
            executor = self._get_executor()
            result   = executor.execute(
                goal        = task.goal,
                speak       = task.speak,
                cancel_flag = task.cancel_flag,
                on_progress = lambda progress: self._update_progress(task, progress),
                on_action = lambda action: self._record_action(task, action),
                approval_callback = task.approval_callback,
                mission_id = task.task_id,
                resume_context = task.resume_context,
                tool_registry = task.tool_registry or self._tool_registry,
            )

            if task.cancel_flag.is_set():
                wait_for_tool_idle()
            with self._lock:
                if task.cancel_flag.is_set():
                    task.status = TaskStatus.CANCELLED
                    task.phase = "cancelled"
                    task.outcome = "cancelled"
                else:
                    outcome = getattr(result, "status", "completed")
                    task.outcome = outcome
                    task.verified = bool(getattr(result, "verified", False))
                    task.status = (
                        TaskStatus.COMPLETED if outcome == "completed"
                        else TaskStatus.PARTIAL if outcome == "partial"
                        else TaskStatus.FAILED
                    )
                    task.phase = task.status.value
                    task.current_step = ""
                    task.result = str(result)
                    if task.status != TaskStatus.COMPLETED:
                        task.error = str(result)
                self._active_count -= 1

            if task.on_complete and not task.cancel_flag.is_set():
                try:
                    task.on_complete(task.task_id, result)
                except Exception as e:
                    print(f"[TaskQueue] ⚠️ on_complete callback error: {e}")

            if task.status == TaskStatus.COMPLETED:
                print(f"[TaskQueue] ✅ Completed: [{task.task_id}]")
            elif task.status == TaskStatus.PARTIAL:
                print(f"[TaskQueue] ⚠️ Partial result: [{task.task_id}]")
            else:
                print(f"[TaskQueue] ❌ Mission did not complete: [{task.task_id}]")

        except Exception as e:
            is_timeout = isinstance(e, ToolTimeoutError)
            if task.cancel_flag.is_set() or is_timeout:
                if is_timeout:
                    with self._lock:
                        task.status = TaskStatus.ACTION_UNKNOWN
                        task.phase = "action_unknown"
                        task.error = str(e)
                wait_for_tool_idle()
            with self._lock:
                if task.cancel_flag.is_set():
                    task.status = TaskStatus.CANCELLED
                    task.phase = "cancelled"
                    task.current_step = ""
                    task.outcome = "cancelled"
                elif is_timeout:
                    task.status = TaskStatus.ACTION_UNKNOWN
                    task.phase = "action_unknown"
                    task.error = str(e)
                    task.outcome = "action_unknown"
                else:
                    task.status = TaskStatus.FAILED
                    task.phase = "failed"
                    task.error  = str(e)
                    task.outcome = "failed"
                self._active_count -= 1
            if task.status == TaskStatus.CANCELLED:
                print(f"[TaskQueue] Cancelled: [{task.task_id}]")
            elif task.status == TaskStatus.ACTION_UNKNOWN:
                print(f"[TaskQueue] Action outcome unknown: [{task.task_id}]")
            elif task.status == TaskStatus.PARTIAL:
                print(f"[TaskQueue] Partially completed: [{task.task_id}]")
            else:
                print(f"[TaskQueue] Task failed: [{task.task_id}]; details omitted.")

        self._persist_task(task)
        with self._condition:
            self._condition.notify()
        try:
            from actions.browser_control import close_browser_mission
            close_browser_mission(task.task_id)
        except Exception as exc:
            print(f"[TaskQueue] Mission browser cleanup failed: {exc}")

    def _update_progress(self, task: Task, progress: dict) -> None:
        if not isinstance(progress, dict):
            return
        with self._lock:
            if task.status != TaskStatus.RUNNING:
                return
            phase = progress.get("phase")
            current_step = progress.get("current_step")
            completed = progress.get("completed_steps")
            total = progress.get("total_steps")
            if isinstance(phase, str):
                task.phase = phase[:30]
            if isinstance(current_step, str):
                task.current_step = current_step[:200]
            if isinstance(completed, int) and not isinstance(completed, bool):
                task.completed_steps = max(0, completed)
            if isinstance(total, int) and not isinstance(total, bool):
                task.total_steps = max(0, total)
            self._persist_task(task)

    def _record_action(self, task: Task, action: dict) -> None:
        if not isinstance(action, dict):
            return
        with self._lock:
            task.action_history.append(dict(action))
            if len(task.action_history) > 50:
                del task.action_history[:-50]
            self._persist_task(task)

_queue        = TaskQueue(persist=True)
_queue_started = False
_queue_lock    = threading.Lock()


def get_queue() -> TaskQueue:
    global _queue_started
    with _queue_lock:
        if not _queue_started:
            _queue.start()
            _queue_started = True
    return _queue


def shutdown_queue_if_started() -> None:
    with _queue_lock:
        if _queue_started:
            _queue.shutdown()
import json
import os
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
    BLOCKED    = "blocked"
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
    executor_kind: str = field(compare=False, default="niang")
    cline_workspace_root: str = field(compare=False, default="")
    cline_mode: str = field(compare=False, default="assisted")
    opencode_workspace_root: str = field(compare=False, default="")
    opencode_mode: str = field(compare=False, default="assisted")
    routing_provider: str = field(compare=False, default="")
    routing_model: str = field(compare=False, default="")
    routing_reason: str = field(compare=False, default="")
    routing_incident_history: list[dict] = field(compare=False, default_factory=list)
    failover_history: list[dict] = field(compare=False, default_factory=list)
    handoff_summary: dict = field(compare=False, default_factory=dict)
    workspace_verification_required: bool = field(compare=False, default=False)
    last_checkpoint: dict = field(compare=False, default_factory=dict)
    continuity_workspace_proof: Any = field(compare=False, default=None)
    continuity_workspace_root: str = field(compare=False, default="")
    continuity_state: str = field(compare=False, default="normal")
    execution_attempt_id: str = field(compare=False, default="")
    continuity_mission_id: str = field(compare=False, default="")


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
    def _serialize_structured_value(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (dict, list, int, float, bool)):
            return value
        if type(value) is not str and isinstance(value, str):
            text = str(value)
            meta = {}
            for key in ("tool_name", "tool", "status", "ok", "verified", "error_kind", "error", "exit_code"):
                if hasattr(value, key):
                    meta[key] = TaskQueue._serialize_structured_value(getattr(value, key))
            if meta or hasattr(value, "status"):
                return {"__type__": type(value).__name__, "content": text, **meta}
            return text
        if isinstance(value, str):
            return value
        if isinstance(value, tuple):
            return [TaskQueue._serialize_structured_value(item) for item in value]
        if hasattr(value, "to_dict"):
            try:
                return TaskQueue._serialize_structured_value(value.to_dict())
            except Exception:
                pass
        if hasattr(value, "__dict__"):
            serializable = {}
            for key, item in vars(value).items():
                if key.startswith("_"):
                    continue
                serializable[key] = TaskQueue._serialize_structured_value(item)
            if serializable:
                return serializable
        return str(value)

    @staticmethod
    def _task_payload(task: Task) -> dict:
        proof = task.continuity_workspace_proof
        if proof is not None:
            try:
                if not isinstance(proof, (dict, str, int, float, bool, list)):
                    proof = TaskQueue._serialize_structured_value(proof)
                if isinstance(proof, str) and proof.startswith("<") and " object at " in proof and proof.endswith(">"):
                    raise ValueError("continuity proof object is not serializable")
            except Exception as exc:
                raise ValueError(f"continuity proof serialization failed: {type(exc).__name__}") from exc
        continuity_markers = bool(
            task.continuity_mission_id
            or task.continuity_workspace_root
            or task.continuity_state not in {"", "normal"}
            or task.execution_attempt_id
        )
        if task.workspace_verification_required and proof is None and continuity_markers:
            raise ValueError("continuity proof missing for protected mission")
        return {
            "goal": task.goal,
            "result": TaskQueue._serialize_structured_value(task.result),
            "outcome": task.outcome,
            "verified": task.verified,
            "error": task.error,
            "phase": task.phase,
            "current_step": task.current_step,
            "completed_steps": task.completed_steps,
            "total_steps": task.total_steps,
            "action_history": task.action_history[-50:],
            "resume_context": task.resume_context,
            "executor_kind": task.executor_kind,
            "cline_workspace_root": task.cline_workspace_root,
            "cline_mode": task.cline_mode,
            "opencode_workspace_root": task.opencode_workspace_root,
            "opencode_mode": task.opencode_mode,
            "routing_provider": task.routing_provider,
            "routing_model": task.routing_model,
            "routing_reason": task.routing_reason,
            "routing_incident_history": task.routing_incident_history[-20:],
            "failover_history": task.failover_history[-20:],
            "handoff_summary": task.handoff_summary,
            "workspace_verification_required": task.workspace_verification_required,
            "last_checkpoint": task.last_checkpoint,
            "continuity_workspace_proof": proof,
            "continuity_workspace_root": task.continuity_workspace_root,
            "continuity_state": task.continuity_state,
            "continuity_mission_id": task.continuity_mission_id,
            "execution_attempt_id": task.execution_attempt_id,
        }

    def mark_workspace_verification_required(self, task_id: str, required: bool = True, checkpoint: dict | None = None):
        with self._lock:
            task = self._tasks.get(task_id) if hasattr(self, "_tasks") else None
            if task is None:
                return
            task.workspace_verification_required = bool(required)
            if checkpoint is not None:
                task.last_checkpoint = dict(checkpoint)
            if hasattr(self, "_persist"):
                try:
                    self._persist()
                except Exception:
                    pass

    def record_failover_handoff(self, task_id: str, handoff: dict | None = None, failover_event: dict | None = None):
        with self._lock:
            task = self._tasks.get(task_id) if hasattr(self, "_tasks") else None
            if task is None:
                return
            if handoff:
                task.handoff_summary = dict(handoff)
                task.workspace_verification_required = True
            if failover_event:
                task.failover_history.append(dict(failover_event))
                task.failover_history = task.failover_history[-20:]
            if hasattr(self, "_persist"):
                try:
                    self._persist()
                except Exception:
                    pass

    def _persist_task(self, task: Task, *, required: bool = False) -> None:
        try:
            payload = self._task_payload(task)
        except Exception as exc:
            task.status = TaskStatus.BLOCKED
            task.phase = "blocked"
            task.outcome = "blocked"
            task.error = f"Mission persistence failed: {type(exc).__name__}: {str(exc)[:250]}"
            if required:
                raise
            print(f"[TaskQueue] Mission persistence failed: {type(exc).__name__}")
            return
        store = self._get_mission_store()
        if store is None:
            return
        try:
            store.save(task.task_id, task.status.value, payload)
            if task.status in {
                TaskStatus.COMPLETED,
                TaskStatus.PARTIAL,
                TaskStatus.FAILED,
                TaskStatus.BLOCKED,
                TaskStatus.ACTION_UNKNOWN,
                TaskStatus.CANCELLED,
                TaskStatus.INTERRUPTED,
            }:
                from agent.settings import artifact_retention_days
                store.prune_terminal(artifact_retention_days())
        except Exception as exc:
            task.status = TaskStatus.BLOCKED
            task.phase = "blocked"
            task.outcome = "blocked"
            task.error = f"Mission persistence failed: {type(exc).__name__}: {str(exc)[:250]}"
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
                    executor_kind=payload.get("executor_kind", "niang"),
                    cline_workspace_root=payload.get("cline_workspace_root", ""),
                    cline_mode=payload.get("cline_mode", "assisted"),
                    opencode_workspace_root=payload.get("opencode_workspace_root", ""),
                    opencode_mode=payload.get("opencode_mode", "assisted"),
                    routing_provider=payload.get("routing_provider", ""),
                    routing_model=payload.get("routing_model", ""),
                    routing_reason=payload.get("routing_reason", ""),
                    routing_incident_history=payload.get("routing_incident_history", []),
                    failover_history=payload.get("failover_history", []),
                    handoff_summary=payload.get("handoff_summary", {}),
                    workspace_verification_required=bool(payload.get("workspace_verification_required", False)),
                    last_checkpoint=payload.get("last_checkpoint", {}),
                    continuity_workspace_proof=payload.get("continuity_workspace_proof"),
                    continuity_workspace_root=payload.get("continuity_workspace_root", ""),
                    continuity_state=payload.get("continuity_state", "normal"),
                    continuity_mission_id=payload.get("continuity_mission_id", ""),
                    execution_attempt_id=payload.get("execution_attempt_id", ""),
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
                    try:
                        store.save(
                            task.task_id,
                            task.status.value,
                            self._task_payload(task),
                        )
                    except Exception as exc:
                        task.status = TaskStatus.BLOCKED
                        task.phase = "blocked"
                        task.outcome = "blocked"
                        task.error = f"Mission persistence failed during recovery restore: {type(exc).__name__}: {str(exc)[:250]}"
                        task.result = {"status": "blocked", "persisted": False, "error": task.error}
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
        print("[TaskQueue] Started")

    def stop(self) -> None:
        self._running = False
        with self._condition:
            self._condition.notify_all()
        print("[TaskQueue] Stopped")

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
        executor_kind: str = "niang",
        cline_workspace_root: str = "",
        cline_mode: str = "assisted",
        opencode_workspace_root: str = "",
        opencode_mode: str = "assisted",
        workspace_verification_required: bool = False,
        continuity_workspace_proof: Any = None,
        continuity_workspace_root: str = "",
        continuity_state: str = "normal",
        handoff_summary: dict | None = None,
        last_checkpoint: dict | None = None,
        task_id: str | None = None,
        continuity_mission_id: str | None = None,
    ) -> str:

        if executor_kind not in {"niang", "cline", "opencode"}:
            raise ValueError("Unsupported mission engine.")
        if executor_kind == "cline" and not cline_workspace_root:
            raise ValueError("Cline missions require a selected project folder.")
        if cline_mode not in {"plan", "assisted", "autonomous_controlled"}:
            raise ValueError("Unsupported Cline operating mode.")
        if executor_kind == "opencode" and not opencode_workspace_root:
            raise ValueError("OpenCode missions require a selected project folder.")
        if opencode_mode not in {"plan", "assisted", "autonomous_controlled"}:
            raise ValueError("Unsupported OpenCode operating mode.")
        preserved_task_id = str(task_id) if task_id else str(uuid.uuid4())[:8]
        canonical_mission_id = str(continuity_mission_id or preserved_task_id)
        task    = Task(
            priority    = priority.value,
            created_at  = time.time(),
            task_id     = preserved_task_id,
            goal        = goal,
            speak       = speak,
            on_complete = on_complete,
            approval_callback = approval_callback,
            resume_context = resume_context,
            tool_registry = tool_registry or self._tool_registry,
            executor_kind = executor_kind,
            cline_workspace_root = cline_workspace_root,
            cline_mode = cline_mode,
            opencode_workspace_root = opencode_workspace_root,
            opencode_mode = opencode_mode,
            workspace_verification_required = bool(workspace_verification_required),
            continuity_workspace_proof = continuity_workspace_proof,
            continuity_workspace_root = continuity_workspace_root or "",
            continuity_state = continuity_state or "normal",
            handoff_summary = dict(handoff_summary or {}),
            last_checkpoint = dict(last_checkpoint or {}),
            execution_attempt_id = str(uuid.uuid4())[:12],
            continuity_mission_id = canonical_mission_id,
        )

        with self._condition:
            # Preserve history if reusing a terminal mission id for a recovery attempt.
            existing = self._tasks.get(preserved_task_id)
            if existing is not None and existing.status in {TaskStatus.INTERRUPTED, TaskStatus.ACTION_UNKNOWN, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.PARTIAL}:
                archive_id = f"{preserved_task_id}__hist__{int(time.time()*1000)}"
                self._tasks[archive_id] = existing
            self._persist_task(task, required=True)
            self._queue.append(task)
            self._queue.sort(key=lambda t: (t.priority, t.created_at))
            self._tasks[preserved_task_id] = task
            self._condition.notify()

        print(f"[TaskQueue] Task queued: [{preserved_task_id}]")
        return preserved_task_id

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

            stop_computer_input = (
                task.status == TaskStatus.RUNNING and task.executor_kind not in {"cline", "opencode"}
            )
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
                stop_browser_action = task.executor_kind not in {"cline", "opencode"}
            try:
                self._queue.remove(task)
            except ValueError:
                pass
            print(f"[TaskQueue] Stop requested: [{task_id}]")
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
                and task.executor_kind not in {"cline", "opencode"}
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
        workspace_proof=None,
        workspace_root: str | None = None,
        require_workspace_verification: bool | None = None,
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
            if previous.executor_kind in {"cline", "opencode"}:
                raise ValueError(
                    "Interrupted coding-agent missions cannot be replayed automatically; start a new mission after reviewing the project."
                )
            history = [
                {
                    "number": item.get("number"),
                    "tool": item.get("tool"),
                    "status": item.get("status", "unknown"),
                }
                for item in previous.action_history[-50:]
            ]
            has_uncertain = any(
                str(item.get("status", "unknown")).lower() in {"unknown", "in_progress", "running"}
                for item in previous.action_history[-50:]
            )
            protected_mission = bool(
                previous.workspace_verification_required
                or previous.continuity_workspace_proof is not None
            )
            goal = previous.goal
            mission_id = previous.task_id
            effective_workspace = (
                workspace_root
                or previous.opencode_workspace_root
                or previous.cline_workspace_root
                or os.environ.get("NIANG_IA_WORKSPACE_ROOT", "")
            )
        must_verify = protected_mission or require_workspace_verification is True
        if must_verify:
            try:
                from niang_ia.model_orchestrator.workspace_verification import authorize_risky_resume_or_write
                from niang_ia.model_orchestrator.continuity_guard import _normalize_checkpoint
                raw_handoff = previous.handoff_summary or previous.last_checkpoint or None
                handoff_obj, handoff_invalid = _normalize_checkpoint(raw_handoff)
                if handoff_obj is not None:
                    if str(getattr(handoff_obj, "mission_id", "") or "") not in {"", previous.continuity_mission_id or previous.task_id}:
                        handoff_invalid = True
                elif raw_handoff is not None:
                    # Fail closed for protected/resume-required missions: history may help diagnose,
                    # but it does not recreate a valid checkpoint for a security-gated resume.
                    handoff_invalid = True
                has_blocking_uncertainty = bool(has_uncertain or handoff_invalid)
                if handoff_obj is not None:
                    for cp in getattr(handoff_obj, "checkpoints", []) or []:
                        if getattr(cp, "status", "unknown") in {"unknown", "in_progress"}:
                            has_blocking_uncertainty = True
                            break
                if has_blocking_uncertainty:
                    step_state = "unknown_unverified"
                    handoff_for_auth = handoff_obj
                else:
                    step_state = "verified_safe_for_new_action" if workspace_proof is not None else "unknown_unverified"
                    handoff_for_auth = None if workspace_proof is not None else handoff_obj
                ok, issues = authorize_risky_resume_or_write(
                    mission_id=mission_id,
                    workspace_root=effective_workspace or None,
                    proof=workspace_proof,
                    handoff=handoff_for_auth,
                    current_step_state=step_state,
                    allow_without_proof=False,
                )
                if handoff_invalid:
                    ok = False
                    issues = list(issues) + ["handoff_invalid_or_mission_mismatch"]
                if has_blocking_uncertainty and workspace_proof is not None:
                    ok = False
                    if "prior_actions_uncertain_or_in_progress" not in issues:
                        issues = list(issues) + ["prior_actions_uncertain_or_in_progress"]
            except Exception:
                ok, issues = False, ["workspace_verification_unavailable"]
            if not ok:
                raise ValueError(
                    "Resume refused: trusted workspace verification required before any risky recovery/write. "
                    f"Issues: {', '.join(issues)}"
                )
        context = (
            "This is an explicitly user-approved recovery of a previously interrupted "
            "mission. The prior action metadata below is not proof that actions completed. "
            "Never replay an action merely because it appears in history. First inspect "
            "the current state and verify whether its effect already occurred. If the "
            "result cannot be verified safely, stop and ask the user. Prior action "
            "metadata (tool and status only): "
            + json.dumps(history, ensure_ascii=True)
        )
        if must_verify and workspace_proof is not None:
            context += " Trusted workspace verification proof was validated before resume."
        # If verification was required/validated (or mission flagged), carry continuity context to new attempt.
        carry_verification = bool(must_verify or previous.workspace_verification_required)
        canonical_mission_id = previous.continuity_mission_id or previous.task_id
        return self.submit(
            goal,
            speak=speak,
            on_complete=on_complete,
            approval_callback=approval_callback,
            resume_context=context,
            workspace_verification_required=carry_verification,
            continuity_workspace_proof=workspace_proof if must_verify else None,
            continuity_workspace_root=effective_workspace or "",
            continuity_state="recovery_verified" if (must_verify and workspace_proof is not None) else ("recovery_pending" if carry_verification else "normal"),
            handoff_summary=previous.handoff_summary or {},
            last_checkpoint=previous.last_checkpoint or {},
            task_id=previous.task_id,
            continuity_mission_id=canonical_mission_id,
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
                "executor_kind": task.executor_kind,
                "cline_workspace_root": task.cline_workspace_root,
                "opencode_workspace_root": task.opencode_workspace_root,
                "routing_provider": task.routing_provider,
                "routing_model": task.routing_model,
                "routing_reason": task.routing_reason,
                "failover_history": [dict(item) for item in task.failover_history[-10:]],
                "workspace_verification_required": task.workspace_verification_required,
            }

    def get_all_statuses(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "task_id": t.task_id,
                    "created_at": t.created_at,
                    "goal":    t.goal[:50],
                    "status":  t.status.value,
                    "outcome": t.outcome,
                    "verified": t.verified,
                    "phase": t.phase,
                    "current_step": t.current_step,
                    "completed_steps": t.completed_steps,
                    "total_steps": t.total_steps,
                    "action_history": [dict(item) for item in t.action_history[-20:]],
                    "executor_kind": t.executor_kind,
                    "routing_provider": t.routing_provider,
                    "routing_model": t.routing_model,
                    "workspace_verification_required": t.workspace_verification_required,
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
            if task.executor_kind in {"cline", "opencode"}:
                workspace_root = (
                    task.opencode_workspace_root
                    if task.executor_kind == "opencode"
                    else task.cline_workspace_root
                )
                mode = task.opencode_mode if task.executor_kind == "opencode" else task.cline_mode
                protected = bool(task.workspace_verification_required or task.continuity_workspace_proof is not None)
                if protected:
                    if not task.continuity_workspace_proof:
                        task.status = TaskStatus.BLOCKED
                        task.phase = "blocked"
                        task.outcome = "blocked"
                        task.error = "Protected Cline mission refused: continuity proof is required before execution."
                        task.result = {"status": "blocked", "persisted": False, "error": task.error}
                        self._persist_task(task)
                        with self._condition:
                            self._condition.notify()
                        self._active_count -= 1
                        return
                    if not task.continuity_workspace_root:
                        task.status = TaskStatus.BLOCKED
                        task.phase = "blocked"
                        task.outcome = "blocked"
                        task.error = "Protected Cline mission refused: verified workspace root is required before execution."
                        task.result = {"status": "blocked", "persisted": False, "error": task.error}
                        self._persist_task(task)
                        with self._condition:
                            self._condition.notify()
                        self._active_count -= 1
                        return
                    try:
                        from niang_ia.model_orchestrator.workspace_verification import validate_proof
                        ok, issues = validate_proof(
                            task.continuity_workspace_proof,
                            mission_id=(task.continuity_mission_id or task.task_id),
                            workspace_root=task.continuity_workspace_root,
                        )
                        if not ok:
                            raise ValueError(", ".join(issues or ["proof_invalid"]))
                    except Exception as exc:
                        task.status = TaskStatus.BLOCKED
                        task.phase = "blocked"
                        task.outcome = "blocked"
                        task.error = f"Protected Cline mission refused: {type(exc).__name__}: {str(exc)[:250]}"
                        task.result = {"status": "blocked", "persisted": False, "error": task.error}
                        self._persist_task(task)
                        with self._condition:
                            self._condition.notify()
                        self._active_count -= 1
                        return
                from niang_ia.integrations.cline.cline_vscode import open_vscode_workspace
                open_vscode_workspace(workspace_root)
                if task.executor_kind == "opencode":
                    from niang_ia.integrations.opencode.opencode_engine import OpenCodeEngine
                    result = OpenCodeEngine().execute(
                        task.goal,
                        workspace_root,
                        mode,
                        cancel_flag=task.cancel_flag,
                        approval_callback=task.approval_callback,
                        on_progress=lambda progress: self._update_progress(task, progress),
                        on_action=lambda action: self._record_action(task, action),
                    )
                else:
                    from niang_ia.integrations.cline.cline_engine import ClineEngine
                    result = ClineEngine().execute(
                        task.goal,
                        workspace_root,
                        mode,
                        cancel_flag=task.cancel_flag,
                        approval_callback=task.approval_callback,
                        on_progress=lambda progress: self._update_progress(task, progress),
                        on_action=lambda action: self._record_action(task, action),
                    )
            else:
                continuity_context = None
                protected_context_required = bool(task.workspace_verification_required or task.continuity_workspace_proof is not None)
                if protected_context_required:
                    try:
                        from niang_ia.model_orchestrator.continuity_guard import ContinuityExecutionContext
                        continuity_context = ContinuityExecutionContext(
                            mission_id=(task.continuity_mission_id or task.task_id),
                            workspace_root=task.continuity_workspace_root or os.environ.get("NIANG_IA_WORKSPACE_ROOT", ""),
                            workspace_proof=task.continuity_workspace_proof,
                            checkpoint=task.handoff_summary or task.last_checkpoint or {},
                            workspace_verification_required=bool(task.workspace_verification_required),
                            continuity_state=task.continuity_state or "normal",
                            execution_attempt_id=task.execution_attempt_id or "",
                            last_operation_uncertain=any(
                                str(item.get("status", "")).lower() in {"unknown", "in_progress", "running"}
                                for item in (task.action_history or [])[-50:]
                            ),
                            action_history=tuple(dict(item) for item in (task.action_history or [])[-50:]),
                        )
                    except Exception as exc:
                        task.status = TaskStatus.BLOCKED
                        task.phase = "blocked"
                        task.outcome = "blocked"
                        task.error = f"Continuity context construction failed: {type(exc).__name__}"
                        task.result = {"status": "blocked", "error": task.error}
                        self._persist_task(task)
                        with self._condition:
                            self._condition.notify()
                        self._active_count -= 1
                        return
                    if continuity_context is None or not getattr(continuity_context, "mission_id", ""):
                        task.status = TaskStatus.BLOCKED
                        task.phase = "blocked"
                        task.outcome = "blocked"
                        task.error = "Continuity context missing or invalid for protected mission."
                        task.result = {"status": "blocked", "error": task.error}
                        self._persist_task(task)
                        with self._condition:
                            self._condition.notify()
                        self._active_count -= 1
                        return
                    if task.workspace_verification_required and task.continuity_workspace_proof is None:
                        task.status = TaskStatus.BLOCKED
                        task.phase = "blocked"
                        task.outcome = "blocked"
                        task.error = "Continuity proof missing for protected mission."
                        task.result = {"status": "blocked", "error": task.error}
                        self._persist_task(task)
                        with self._condition:
                            self._condition.notify()
                        self._active_count -= 1
                        return
                    if task.continuity_mission_id and continuity_context.mission_id != task.continuity_mission_id:
                        task.status = TaskStatus.BLOCKED
                        task.phase = "blocked"
                        task.outcome = "blocked"
                        task.error = "Continuity context mission identity mismatch."
                        task.result = {"status": "blocked", "error": task.error}
                        self._persist_task(task)
                        with self._condition:
                            self._condition.notify()
                        self._active_count -= 1
                        return
                    if task.continuity_workspace_proof is not None:
                        try:
                            from niang_ia.model_orchestrator.workspace_verification import validate_proof
                            ok, issues = validate_proof(
                                task.continuity_workspace_proof,
                                mission_id=continuity_context.mission_id,
                                workspace_root=task.continuity_workspace_root or continuity_context.workspace_root,
                            )
                            if not ok:
                                raise ValueError(", ".join(issues))
                        except Exception as exc:
                            task.status = TaskStatus.BLOCKED
                            task.phase = "blocked"
                            task.outcome = "blocked"
                            task.error = f"Continuity proof invalid or unusable: {type(exc).__name__}"
                            task.result = {"status": "blocked", "error": task.error}
                            self._persist_task(task)
                            with self._condition:
                                self._condition.notify()
                            self._active_count -= 1
                            return
                executor = self._get_executor()
                result = executor.execute(
                    goal=task.goal,
                    speak=task.speak,
                    cancel_flag=task.cancel_flag,
                    on_progress=lambda progress: self._update_progress(task, progress),
                    on_action=lambda action: self._record_action(task, action),
                    approval_callback=task.approval_callback,
                    mission_id=task.task_id,
                    resume_context=task.resume_context,
                    tool_registry=task.tool_registry or self._tool_registry,
                    continuity_context=continuity_context,
                )

            if task.cancel_flag.is_set() and task.executor_kind not in {"cline", "opencode"}:
                wait_for_tool_idle()
            with self._lock:
                if task.cancel_flag.is_set():
                    task.status = TaskStatus.CANCELLED
                    task.phase = "cancelled"
                    task.outcome = "cancelled"
                else:
                    from agent.executor import _coerce_result_status
                    outcome = _coerce_result_status(result)
                    task.outcome = outcome
                    task.verified = bool(getattr(result, "verified", False))
                    task.status = (
                        TaskStatus.COMPLETED if outcome == "completed"
                        else TaskStatus.PARTIAL if outcome == "partial"
                        else TaskStatus.BLOCKED if outcome == "blocked"
                        else TaskStatus.FAILED if outcome == "failed"
                        else TaskStatus.ACTION_UNKNOWN if outcome == "action_unknown"
                        else TaskStatus.FAILED
                    )
                    task.phase = task.status.value
                    task.current_step = ""
                    if hasattr(result, "text") and not isinstance(result, (str, bytes)):
                        task.result = result.text
                        selected_skills = getattr(result, "selected_skills", [])
                        loaded_skills = getattr(result, "loaded_skills", [])
                        if selected_skills:
                            task.result += (
                                "\n\nSkills selected: " + ", ".join(selected_skills)
                                + "\nSkills loaded: " + (", ".join(loaded_skills) or "none")
                            )
                        quality_gate = getattr(result, "quality_gate", None)
                        if isinstance(quality_gate, dict) and quality_gate:
                            from niang_ia.skills.quality_gate import format_quality_gate
                            task.result = f"{task.result}\n\n{format_quality_gate(quality_gate)}"
                    elif isinstance(result, dict) and isinstance(result.get("text"), str):
                        task.result = result["text"]
                        skill_usage = result.get("skills")
                        if isinstance(skill_usage, dict) and skill_usage.get("selected"):
                            selected_skills = skill_usage["selected"]
                            loaded_skills = skill_usage.get("loaded", [])
                            task.result += (
                                "\n\nSkills selected: " + ", ".join(selected_skills)
                                + "\nSkills loaded: " + (", ".join(loaded_skills) or "none")
                            )
                        quality_gate = result.get("quality_gate")
                        if isinstance(quality_gate, dict) and quality_gate:
                            from niang_ia.skills.quality_gate import format_quality_gate
                            task.result = f"{task.result}\n\n{format_quality_gate(quality_gate)}"
                    else:
                        task.result = result
                    if task.status not in {TaskStatus.COMPLETED, TaskStatus.BLOCKED}:
                        task.error = str(result)
                    elif task.status == TaskStatus.BLOCKED:
                        task.error = str(result)
                self._active_count -= 1

            if task.on_complete and not task.cancel_flag.is_set():
                try:
                    task.on_complete(task.task_id, result)
                except Exception as e:
                    print(f"[TaskQueue] on_complete callback error: {e}")

            if task.status == TaskStatus.COMPLETED:
                print(f"[TaskQueue] Completed: [{task.task_id}]")
            elif task.status == TaskStatus.PARTIAL:
                print(f"[TaskQueue] Partial result: [{task.task_id}]")
            else:
                print(f"[TaskQueue] Mission did not complete: [{task.task_id}]")

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
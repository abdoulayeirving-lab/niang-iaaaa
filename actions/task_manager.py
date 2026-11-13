# actions/task_manager.py
# Kaizumi — Agent Task Status & Control

from agent.task_queue import get_queue


def task_manager(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Query or control background agent tasks.
    actions: status | list | cancel"""
    params = parameters or {}
    action = str(params.get("action", "list")).lower().strip()
    queue  = get_queue()

    if action in ("status", "check"):
        task_id = str(params.get("task_id", "")).strip()
        if not task_id:
            return "Please provide a task_id, sir."
        info = queue.get_status(task_id)
        if not info:
            return f"No task found with ID {task_id}, sir."
        status = info["status"]
        if status == "completed" and info.get("result"):
            return f"Task {task_id} completed. Result: {info['result']}"
        if status == "failed":
            return f"Task {task_id} failed. {info.get('error', '')}"
        if status == "cancelled":
            return f"Task {task_id} was cancelled."
        progress = ""
        if info.get("total_steps"):
            progress = (
                f" Progress: {info['completed_steps']}/{info['total_steps']} steps."
            )
        current = f" Current step: {info['current_step']}." if info.get("current_step") else ""
        return (
            f"Task {task_id} is {status} ({info.get('phase', status)})."
            f"{progress}{current} Goal: {info['goal']}"
        )

    if action in ("cancel", "stop", "abort"):
        task_id = str(params.get("task_id", "")).strip()
        if not task_id:
            cancelled = queue.cancel_all_active()
            if not cancelled:
                return "Aucune mission autonome n’est en cours ou en attente."
            return (
                f"Arrêt demandé pour {len(cancelled)} mission(s) autonome(s) : "
                + ", ".join(cancelled)
                + ". Les actions actives sont en cours d’interruption."
            )
        if queue.cancel(task_id):
            return f"Arrêt demandé pour la mission {task_id}."
        return f"Impossible d’arrêter la mission {task_id} ; elle est peut-être déjà terminée."

    if action in ("list", "all", "tasks"):
        tasks = queue.get_all_statuses()
        if not tasks:
            return "No background tasks, sir."
        lines = []
        for t in tasks[-8:]:
            progress = ""
            if t.get("total_steps"):
                progress = f" {t['completed_steps']}/{t['total_steps']}"
            current = f" — {t['current_step']}" if t.get("current_step") else ""
            lines.append(
                f"{t['task_id']}: {t['status']}{progress}{current} — {t['goal']}"
            )
        return "Tasks: " + " | ".join(lines)

    return f"Unknown task action: {action}, sir."

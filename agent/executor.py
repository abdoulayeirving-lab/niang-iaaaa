import json
import queue
import re
import sys
import threading
import subprocess
import tempfile
import os
import time
from pathlib import Path
from typing import Callable

from agent.planner       import create_plan, replan
from agent.error_handler import analyze_error, generate_fix, ErrorDecision
from agent.tool_registry import ToolExecutionContext, ToolRegistry


class UnknownToolError(RuntimeError):
    """The planner named a tool the executor doesn't implement â€” not retryable."""


class MissionCancelled(RuntimeError):
    """The mission was cancelled before another tool action could be dispatched."""


class ToolTimeoutError(TimeoutError):
    """A tool call timed out; its result may remain unknown."""


class ToolExecutionBusyError(RuntimeError):
    """A previous synchronous tool call is still running."""


class MissionDeadlineExceeded(RuntimeError):
    """The mission deadline passed before an action was dispatched."""


class MissionExecutionResult(str):
    """String-compatible mission outcome with explicit verification metadata."""

    def __new__(cls, content: str, *, status: str, verified: bool = False):
        instance = super().__new__(cls, content)
        instance.status = status
        instance.verified = verified
        return instance


_TOOL_EXECUTION_LOCK = threading.Lock()
_TOOL_EXECUTION_IDLE = threading.Event()
_TOOL_EXECUTION_IDLE.set()


def wait_for_tool_idle(timeout: float | None = None) -> bool:
    """Wait until a synchronous action worker has actually returned."""
    return _TOOL_EXECUTION_IDLE.wait(timeout)


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _run_generated_code(description: str, speak: Callable | None = None) -> str:
    from api_keys import GeminiModel

    if speak:
        speak("Writing custom code for this task, sir.")

    home      = Path.home()
    desktop   = home / "Desktop"
    downloads = home / "Downloads"
    documents = home / "Documents"

    if not desktop.exists():
        try:
            import winreg
            key     = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders")
            desktop = Path(winreg.QueryValueEx(key, "Desktop")[0])
        except Exception:
            pass

    model = GeminiModel(
        model_name="gemini-2.5-flash",
        system_instruction=(
            "You are an expert Python developer. "
            "Write clean, complete, working Python code. "
            "Use standard library + common packages. "
            "Install missing packages with subprocess + pip if needed. "
            "Return ONLY the Python code. No explanation, no markdown, no backticks.\n\n"
            f"SYSTEM PATHS:\n"
            f"  Desktop   = r'{desktop}'\n"
            f"  Downloads = r'{downloads}'\n"
            f"  Documents = r'{documents}'\n"
            f"  Home      = r'{home}'\n"
        )
    )

    try:
        response = model.generate_content(
            f"Write Python code to accomplish this task:\n\n{description}"
        )
        code = response.text.strip()
        code = re.sub(r"```(?:python)?", "", code).strip().rstrip("`").strip()

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        print(f"[Executor] ðŸ Running generated code: {tmp_path}")

        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True, text=True,
            timeout=120, cwd=str(Path.home())
        )

        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        output = result.stdout.strip()
        error  = result.stderr.strip()

        if result.returncode == 0 and output:
            return output
        elif result.returncode == 0:
            return "Task completed successfully."
        elif error:
            raise RuntimeError(f"Code error: {error[:400]}")
        return "Completed."

    except subprocess.TimeoutExpired:
        raise RuntimeError("Generated code timed out after 120 seconds.")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Generated code failed: {e}")

def _inject_context(params: dict, tool: str, step_results: dict, goal: str = "") -> dict:
    if not step_results:
        return params

    params = dict(params)

    if tool == "file_controller" and params.get("action") in ("write", "create_file"):
        content = params.get("content", "")
        if not content or len(content) < 50:
            all_results = [
                v for v in step_results.values()
                if v and len(v) > 100 and v not in ("Done.", "Completed.")
            ]
            if all_results:
                combined = "\n\n---\n\n".join(all_results)
                translated = _translate_to_goal_language(combined, goal)
                params["content"] = translated
                print(f"[Executor] ðŸ’‰ Injected + translated content")

    return params
def _detect_language(text: str) -> str:
    from api_keys import GeminiModel
    model = GeminiModel("gemini-3.5-flash-lite")
    try:
        response = model.generate_content(
            f"What language is this text written in? "
            f"Reply with ONLY the language name in English (e.g. Turkish, English, French).\n\n"
            f"Text: {text[:200]}"
        )
        return response.text.strip()
    except Exception:
        return "English"


def _translate_to_goal_language(content: str, goal: str) -> str:
    if not goal:
        return content
    try:
        from api_keys import GeminiModel
        model = GeminiModel("gemini-2.5-flash")

        target_lang = _detect_language(goal)
        print(f"[Executor] ðŸŒ Translating to: {target_lang}")

        prompt = (
            f"You are a professional translator. "
            f"Translate the following text into {target_lang}.\n"
            f"IMPORTANT:\n"
            f"- Translate EVERYTHING, leave nothing in English\n"
            f"- Keep all facts, numbers, and data intact\n"
            f"- Keep the structure and formatting\n"
            f"- Output ONLY the translated text, nothing else\n\n"
            f"Text to translate:\n{content[:4000]}"
        )
        response = model.generate_content(prompt)
        translated = response.text.strip()
        print(f"[Executor] âœ… Translation done ({target_lang})")
        return translated
    except Exception as e:
        print(f"[Executor] âš ï¸ Translation failed: {e}")
        return content

def _call_tool(
    tool: str,
    parameters: dict,
    speak: Callable | None,
    approval_callback: Callable[[str, dict, str], bool] | None = None,
    cancel_flag: threading.Event | None = None,
    mission_id: str | None = None,
    tool_registry: ToolRegistry | None = None,
) -> str:
    if cancel_flag and cancel_flag.is_set():
        raise MissionCancelled("Task cancelled before the action started.")
    try:
        from safety import (
            describe,
            issue_confirmation_token,
            needs_confirmation,
        )
        if needs_confirmation(tool, parameters, confirm=False):
            if approval_callback is None:
                return (
                    f"Blocked for safety: {tool} requires explicit confirmation; "
                    "no action was taken."
                )
            description = describe(tool, parameters)
            if not approval_callback(tool, dict(parameters), description):
                return f"Blocked for safety: approval was denied for {tool}; no action was taken."
            if cancel_flag and cancel_flag.is_set():
                raise MissionCancelled("Task cancelled while awaiting approval.")
            token = issue_confirmation_token(tool, parameters)
            if needs_confirmation(
                tool,
                parameters,
                confirm=True,
                confirm_token=token,
            ):
                return (
                    f"Blocked for safety: confirmation could not be verified for {tool}; "
                    "no action was taken."
                )
    except MissionCancelled:
        raise
    except Exception:
        return (
            f"Blocked for safety: could not verify permissions for {tool}. "
            "The action was not executed."
        )

    if cancel_flag and cancel_flag.is_set():
        raise MissionCancelled("Task cancelled before the action started.")

    if tool_registry is not None:
        definition = tool_registry.get(tool)
        if definition is None or not definition.agent_enabled:
            raise UnknownToolError(f"Unknown or unavailable mission tool '{tool}'.")
        result = tool_registry.invoke(
            tool,
            parameters,
            ToolExecutionContext(
                mission_id=mission_id,
                cancel_flag=cancel_flag,
                speak=speak,
                agent_mode=True,
            ),
        )
        return result

    if tool == "open_app":
        from actions.open_app import open_app
        return open_app(parameters=parameters, player=None) or "Done."

    elif tool == "web_search":
        from actions.web_search import web_search
        return web_search(parameters=parameters, player=None) or "Done."
    elif tool == "game_updater":
        from actions.game_updater import game_updater
        return game_updater(parameters=parameters, player=None, speak=speak) or "Done."
    elif tool == "browser_control":
        from actions.browser_control import browser_control
        return browser_control(
            parameters=parameters,
            player=None,
            mission_id=mission_id,
            cancel_flag=cancel_flag,
        ) or "Done."

    elif tool == "workspace_list_files":
        from agent.workspace_tools import list_files
        return list_files(**parameters)
    elif tool == "workspace_read_file":
        from agent.workspace_tools import read_file
        return read_file(**parameters)
    elif tool == "workspace_write_file":
        from agent.workspace_tools import write_file
        return write_file(**parameters)
    elif tool == "workspace_edit_file":
        from agent.workspace_tools import edit_file
        return edit_file(**parameters)
    elif tool == "workspace_apply_patch":
        from agent.workspace_tools import apply_patch
        return apply_patch(**parameters)
    elif tool == "workspace_search":
        from agent.workspace_tools import search_text
        return search_text(**parameters)
    elif tool == "workspace_run_check":
        from agent.workspace_tools import run_check
        return run_check(**parameters)

    elif tool == "file_controller":
        from actions.file_controller import file_controller
        return file_controller(parameters=parameters, player=None) or "Done."

    elif tool == "cmd_control":
        from actions.cmd_control import cmd_control
        return cmd_control(parameters=parameters, player=None) or "Done."

    elif tool == "code_helper":
        from actions.code_helper import code_helper
        return code_helper(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "dev_agent":
        from actions.dev_agent import dev_agent
        return dev_agent(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "screen_process":
        from actions.screen_processor import screen_process
        return screen_process(parameters=parameters, player=None) or "Screen captured and analyzed."

    elif tool == "send_message":
        from actions.send_message import send_message
        return send_message(parameters=parameters, player=None) or "Done."

    elif tool == "reminder":
        from actions.reminder import reminder
        return reminder(parameters=parameters, player=None) or "Done."

    elif tool == "youtube_video":
        from actions.youtube_video import youtube_video
        return youtube_video(parameters=parameters, player=None) or "Done."

    elif tool == "weather_report":
        from actions.weather_report import weather_action
        return weather_action(parameters=parameters, player=None) or "Done."

    elif tool == "computer_settings":
        from actions.computer_settings import computer_settings
        return computer_settings(parameters=parameters, player=None) or "Done."

    elif tool == "desktop_control":
        from actions.desktop import desktop_control
        return desktop_control(parameters=parameters, player=None) or "Done."

    elif tool == "computer_control":
        from actions.computer_control import computer_control
        return computer_control(parameters=parameters, player=None) or "Done."

    elif tool == "windows_diagnostics":
        from actions.windows_diagnostics import windows_diagnostics
        return windows_diagnostics(
            parameters=parameters,
            cancel_flag=cancel_flag,
        )

    elif tool == "windows_repair":
        from actions.windows_repair import windows_repair
        return windows_repair(
            parameters=parameters,
            cancel_flag=cancel_flag,
        )

    elif tool == "system_status":
        from actions.system_status import system_status
        return system_status(parameters=parameters, player=None) or "Done."

    elif tool == "task_manager":
        from actions.task_manager import task_manager
        return task_manager(parameters=parameters, player=None) or "Done."

    elif tool == "clipboard":
        from actions.clipboard import clipboard_action
        return clipboard_action(parameters=parameters, player=None) or "Done."

    elif tool == "recall_memory":
        from memory.memory_manager import search_memory
        return search_memory(parameters.get("query", ""), parameters.get("category", "")) or "Done."

    elif tool == "vision_gesture":
        from actions.vision_gesture import vision_gesture
        return vision_gesture(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "generated_code":
        # Safety-first: do not execute LLM-generated arbitrary code by default.
        # Keep the helper available in codebase, but require implementing a safer sandbox/approval flow first.
        raise RuntimeError(
            "Blocked for safety: generated_code execution is disabled in this build."
        )

    elif tool == "flight_finder":
        from actions.flight_finder import flight_finder
        return flight_finder(parameters=parameters, player=None, speak=speak) or "Done."

    elif tool == "notify":
        from actions.notifications import notify
        return notify(parameters=parameters, player=None) or "Done."

    elif tool == "daily_briefing":
        from actions.daily_briefing import daily_briefing
        return daily_briefing(parameters=parameters, player=None) or "Done."

    elif tool == "wake_word":
        from actions.wake_word import wake_word
        return wake_word(parameters=parameters, player=None) or "Done."

    elif tool == "gmail":
        from actions.gmail import gmail_action
        return gmail_action(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "read_pdf":
        from actions.pdf_reader import read_pdf_action
        return read_pdf_action(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "pdf_qa":
        from actions.pdf_reader import pdf_qa
        return pdf_qa(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "autostart":
        from actions.autostart import autostart_action
        return autostart_action(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "vision_click":
        from actions.vision_click import vision_click_action
        return vision_click_action(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "monitor_alerts":
        from actions.monitor import monitor_action
        return monitor_action(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "email_watch":
        from actions.monitor import email_watch_action
        return email_watch_action(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "pc_health":
        from actions.guardian import guardian_action
        return guardian_action(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "translate":
        from actions.translate import translate_action
        return translate_action(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "media_control":
        from actions.media_control import media_control_action
        return media_control_action(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "read_document":
        from actions.document_qa import read_document
        return read_document(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "document_qa":
        from actions.document_qa import document_qa
        return document_qa(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "search_documents":
        from actions.document_qa import search_documents
        return search_documents(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "calendar":
        from actions.calendar_actions import calendar_action
        return calendar_action(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "drive":
        from actions.drive import drive_action
        return drive_action(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "schedule":
        return f"Schedule handled by the main session, sir â€” background agent doesn't run timers."

    elif tool == "create_presentation":
        from actions.office_builder import create_presentation as _make_pptx
        return _make_pptx(title=parameters.get("title", ""),
                          slides=parameters.get("slides") or [],
                          filename=parameters.get("filename")) or "Done."

    elif tool == "create_document":
        from actions.office_builder import create_document as _make_docx
        return _make_docx(
            title=parameters.get("title", ""),
            sections=parameters.get("sections") or [],
            filename=parameters.get("filename"),
            author=parameters.get("author", "NIANG IA"),
        ) or "Done."

    elif tool == "analyze_data":
        from actions.data_analysis import analyze_data
        return analyze_data(parameters=parameters, response=None, player=None) or "Done."

    elif tool == "create_spreadsheet":
        from actions.office_builder import create_spreadsheet as _make_xlsx
        return _make_xlsx(filename=parameters.get("filename", "spreadsheet"),
                          headers=parameters.get("headers") or [],
                          rows=parameters.get("rows") or [],
                          sheet_name=parameters.get("sheet_name", "Sheet1")) or "Done."

    elif tool == "smart_home_control":
        from actions.smart_home import smart_home_control as _sh_control
        return _sh_control(action=parameters.get("action", "status"),
                           device=parameters.get("device"),
                           value=parameters.get("value"),
                           area=parameters.get("area")) or "Done."

    elif tool in ("save_memory", "set_mode", "set_voice", "set_mood"):
        return f"{tool} is a main-session preference tool, sir â€” skipping in background."

    elif tool == "api_add_key":
        return "api_add_key requires the main session, sir â€” skipping in background."

    elif tool in ("google_auth", "google_auth_status"):
        return f"{tool} needs the main session UI, sir â€” skipping in background."

    else:
        raise UnknownToolError(f"Unknown tool '{tool}'.")


def _call_tool_with_timeout(tool: str, parameters: dict, speak: Callable | None,
                            cancel_flag: threading.Event | None = None,
                            approval_callback: Callable[[str, dict, str], bool] | None = None,
                            mission_id: str | None = None,
                            timeout_s: float | None = None,
                            tool_registry: ToolRegistry | None = None) -> str:
    """Run one tool without blocking the queue past timeout or cancellation."""
    from agent.settings import action_timeout_seconds

    configured_timeout = action_timeout_seconds()
    if tool in {"windows_diagnostics", "windows_repair"}:
        from agent.settings import windows_action_timeout_seconds
        configured_timeout = windows_action_timeout_seconds()
    if cancel_flag and cancel_flag.is_set():
        raise MissionCancelled("Task cancelled before the action started.")
    if timeout_s is not None and timeout_s <= 0:
        raise MissionDeadlineExceeded(
            "The mission deadline expired before this action started; no action was dispatched."
        )
    if not _TOOL_EXECUTION_LOCK.acquire(blocking=False):
        raise ToolExecutionBusyError(
            "A previous tool action is still running; no new action was dispatched."
        )
    _TOOL_EXECUTION_IDLE.clear()

    outcome: queue.Queue = queue.Queue(maxsize=1)
    abandon = threading.Event()
    action_cancel = threading.Event()

    def run_tool() -> None:
        try:
            if abandon.is_set() or (cancel_flag and cancel_flag.is_set()):
                raise MissionCancelled("Task cancelled before the action started.")
            result = _call_tool(
                tool,
                parameters,
                speak,
                approval_callback,
                action_cancel,
                mission_id,
                tool_registry,
            )
            completed = (True, result)
        except Exception as exc:
            completed = (False, exc)
        finally:
            _TOOL_EXECUTION_LOCK.release()
            _TOOL_EXECUTION_IDLE.set()
        outcome.put(completed)

    worker = threading.Thread(
        target=run_tool,
        daemon=True,
        name="AgentToolAction",
    )
    try:
        worker.start()
    except Exception:
        _TOOL_EXECUTION_LOCK.release()
        _TOOL_EXECUTION_IDLE.set()
        raise

    timeout_s = min(
        configured_timeout,
        timeout_s if timeout_s is not None else configured_timeout,
    )
    deadline = time.monotonic() + timeout_s
    while True:
        if cancel_flag and cancel_flag.is_set():
            abandon.set()
            action_cancel.set()
            if tool == "browser_control" and mission_id:
                try:
                    from actions.playwright_mcp import cancel_playwright_mcp_action
                    cancel_playwright_mcp_action(mission_id)
                except Exception as exc:
                    print(f"[Executor] Browser cancellation request failed: {exc}")
            raise MissionCancelled(
                "Stop requested. The current action may still be running; "
                "no further action will be dispatched."
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            abandon.set()
            action_cancel.set()
            if tool == "browser_control" and mission_id:
                try:
                    from actions.playwright_mcp import cancel_playwright_mcp_action
                    cancel_playwright_mcp_action(mission_id)
                except Exception as exc:
                    print(f"[Executor] Browser timeout cancellation failed: {exc}")
            raise ToolTimeoutError(
                f"Tool '{tool}' exceeded its {timeout_s}s timeout. Its result is unknown; "
                "no further action will be dispatched."
            )
        try:
            succeeded, result = outcome.get(timeout=min(0.1, remaining))
        except queue.Empty:
            continue
        if succeeded:
            return result
        raise result


def _is_browser_failure(result: str) -> bool:
    lowered = result.strip().lower()
    if re.search(r"\bhttp status:\s*[45]\d\d\b", lowered):
        return True
    return lowered.startswith((
        "blocked navigation:", "navigation blocked:", "navigation error:",
        "browser mcp error:", "playwright mcp action", "navigation error:",
        "browser error:", "browser action timed out.", "timeout loading:",
        "click error:", "type error:", "form submission failed:", "could not ",
        "unknown action:", "youtube search failed", "youtube is open, but",
        "timed out waiting", "tab not found", "expected one",
        "multiple fields", "no selector", "no back history",
        "no forward history",
    ))


def _is_computer_failure(result: str) -> bool:
    try:
        outcome = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return False
    return (
        isinstance(outcome, dict)
        and (outcome.get("executed") is False or bool(outcome.get("error")))
    )


def _is_process_tool_failure(tool: str, parameters: dict, result: str) -> bool:
    if tool not in {"terminal_control", "project_execution"}:
        return False
    try:
        details = json.loads(result)
    except (TypeError, json.JSONDecodeError):
        return True
    if not isinstance(details, dict):
        return True
    action = str(parameters.get("action", "")).casefold()
    if tool == "terminal_control":
        if action == "run":
            return details.get("status") != "completed" or details.get("exit_code") != 0
        if action == "start":
            return details.get("status") != "started"
        if action == "stop":
            return details.get("state") != "stopped"
        return False
    if action == "start":
        return details.get("verified") is not True
    if action == "stop":
        return details.get("state") != "stopped"
    return False


class AgentExecutor:

    MAX_REPLAN_ATTEMPTS = 2
    MAX_ACTIONS_PER_MISSION = 20

    @staticmethod
    def _report_progress(callback, phase, current_step, completed, total):
        if callback is None:
            return
        try:
            callback({
                "phase": phase,
                "current_step": current_step,
                "completed_steps": completed,
                "total_steps": total,
            })
        except Exception as exc:
            print(f"[Executor] Progress callback failed: {exc}")

    def execute(
        self,
        goal:        str,
        speak:       Callable | None        = None,
        cancel_flag: threading.Event | None = None,
        on_progress: Callable[[dict], None] | None = None,
        on_action: Callable[[dict], None] | None = None,
        approval_callback: Callable[[str, dict, str], bool] | None = None,
        mission_id: str | None = None,
        resume_context: str = "",
        tool_registry: ToolRegistry | None = None,
    ) -> MissionExecutionResult:
        from agent.settings import (
            max_actions_per_mission,
            max_attempts_per_step,
            max_replans_per_mission,
            mission_timeout_seconds,
            sensitive_mission_policy,
        )
        from agent.secrets import detect_sensitive_data

        print("\n[Executor] Starting autonomous mission.")

        replan_attempts = 0
        completed_steps = []
        step_results    = {} 
        last_action_result = None
        action_count = 0
        mission_deadline = time.monotonic() + mission_timeout_seconds()
        detected_secrets = detect_sensitive_data(goal)
        if detected_secrets:
            if sensitive_mission_policy() == "block":
                self._report_progress(
                    on_progress, "blocked_sensitive_input", "", 0, 0,
                )
                return MissionExecutionResult(
                    "Mission blocked before Gemini transmission because the request "
                    "appears to contain sensitive data. Remove it or set the policy "
                    "to 'confirm' to require explicit approval.",
                    status="blocked",
                )
            if not approval_callback or not approval_callback(
                "gemini_transmission",
                {"detected_categories": list(detected_secrets)},
                "The mission may contain sensitive information. Approve sending the "
                "mission text to Gemini? Detected values are not shown in this prompt.",
            ):
                return MissionExecutionResult(
                    "Mission blocked; sensitive mission text was not sent to Gemini.",
                    status="blocked",
                )
            if cancel_flag and cancel_flag.is_set():
                raise MissionCancelled("Mission cancelled before Gemini transmission.")
        if cancel_flag and cancel_flag.is_set():
            raise MissionCancelled("Mission cancelled before Gemini planning.")
        remaining_s = mission_deadline - time.monotonic()
        if remaining_s <= 0:
            raise MissionDeadlineExceeded(
                "Mission duration limit expired before Gemini planning; no action was dispatched."
            )
        plan = create_plan(
            goal,
            context=resume_context,
            timeout_s=min(1800, max(1, int(remaining_s))),
            registry=tool_registry,
        )
        if cancel_flag and cancel_flag.is_set():
            raise MissionCancelled("Mission cancelled during Gemini planning.")

        while True:
            steps = plan.get("steps", [])
            if time.monotonic() >= mission_deadline:
                self._report_progress(
                    on_progress, "duration_limit", "", len(completed_steps),
                    len(completed_steps) + len(steps),
                )
                return MissionExecutionResult(
                    "Mission stopped at its configured duration limit.",
                    status="partial",
                )

            if not steps:
                msg = "I couldn't create a valid plan for this task, sir."
                if speak: speak(msg)
                return MissionExecutionResult(msg, status="failed")
            self._report_progress(
                on_progress, "planned", "", len(completed_steps),
                len(completed_steps) + len(steps),
            )

            success      = True
            failed_step  = None
            failed_error = ""

            for step in steps:
                if cancel_flag and cancel_flag.is_set():
                    if speak: speak("Task cancelled, sir.")
                    return MissionExecutionResult("Task cancelled.", status="cancelled")

                step_num = step.get("step", "?")
                tool     = step.get("tool", "generated_code")
                desc     = step.get("description", "")
                params   = step.get("parameters", {})

                params = _inject_context(params, tool, step_results, goal=goal)

                print(f"\n[Executor] Step {step_num}: [{tool}]")
                self._report_progress(
                    on_progress, "running", f"{step_num}: {desc}",
                    len(completed_steps), len(completed_steps) + len(steps),
                )

                attempt = 1
                step_ok = False

                while attempt <= max_attempts_per_step():
                    if cancel_flag and cancel_flag.is_set():
                        break
                    if time.monotonic() >= mission_deadline:
                        self._report_progress(
                            on_progress, "duration_limit", f"{step_num}: {desc}",
                            len(completed_steps), len(completed_steps) + len(steps),
                        )
                        return MissionExecutionResult(
                            "Mission stopped at its configured duration limit.",
                            status="partial",
                        )
                    try:
                        action_limit = max_actions_per_mission()
                        if action_count >= action_limit:
                            msg = (
                                "Task stopped because it reached the "
                                f"{action_limit}-action mission limit."
                            )
                            self._report_progress(
                                on_progress, "action_limit", f"{step_num}: {desc}",
                                len(completed_steps), len(completed_steps) + len(steps),
                            )
                            return MissionExecutionResult(msg, status="partial")
                        action_count += 1
                        result = _call_tool_with_timeout(
                            tool,
                            params,
                            speak,
                            cancel_flag,
                            approval_callback,
                            mission_id,
                            mission_deadline - time.monotonic(),
                            tool_registry,
                        )
                        if getattr(result, "ok", True) is False:
                            self._report_action(
                                on_action,
                                action_count,
                                tool,
                                desc,
                                params,
                                result,
                                "unknown",
                            )
                            raise ToolTimeoutError(str(result))
                        if result.strip().lower().startswith("blocked for safety:"):
                            self._report_action(
                                on_action, action_count, tool, desc, params, result, "blocked"
                            )
                            return MissionExecutionResult(
                                f"Task stopped; no action was taken. {result}",
                                status="blocked",
                            )
                        if tool == "browser_control" and _is_browser_failure(result):
                            if "timed out" in result.casefold() or "timeout" in result.casefold():
                                raise ToolTimeoutError(
                                    "Browser action timed out; its result is unknown."
                                )
                            raise RuntimeError(result)
                        if tool == "workspace_run_check" and " failed with exit code " in result:
                            raise RuntimeError(result)
                        if tool == "computer_control" and _is_computer_failure(result):
                            raise RuntimeError(result)
                        if _is_process_tool_failure(tool, params, result):
                            raise RuntimeError(
                                f"The {tool} action did not complete successfully; "
                                "inspect its structured result before retrying."
                            )
                        self._report_action(
                            on_action, action_count, tool, desc, params, result, "completed"
                        )
                        step_results[step_num] = result 
                        last_action_result = result
                        completed_steps.append(step)
                        self._report_progress(
                            on_progress, "running", f"{step_num}: {desc}",
                            len(completed_steps), len(completed_steps) + len(steps),
                        )
                        print(f"[Executor] Step {step_num} completed.")
                        step_ok = True
                        break

                    except MissionCancelled as e:
                        self._report_action(
                            on_action, action_count, tool, desc, params, str(e), "unknown"
                        )
                        self._report_progress(
                            on_progress, "stop_requested", f"{step_num}: {desc}",
                            len(completed_steps), len(completed_steps) + len(steps),
                        )
                        return MissionExecutionResult(str(e), status="cancelled")

                    except (
                        ToolTimeoutError,
                        ToolExecutionBusyError,
                        MissionDeadlineExceeded,
                    ) as e:
                        self._report_action(
                            on_action, action_count, tool, desc, params, str(e), "unknown"
                        )
                        self._report_progress(
                            on_progress, "stopped", f"{step_num}: {desc}",
                            len(completed_steps), len(completed_steps) + len(steps),
                        )
                        if isinstance(e, (ToolTimeoutError, MissionDeadlineExceeded)):
                            raise
                        return str(e)

                    except UnknownToolError as e:
                        self._report_action(
                            on_action, action_count, tool, desc, params, str(e), "failed"
                        )
                        msg = f"Task stopped because the planned tool is unavailable: {e}"
                        if speak:
                            speak(msg)
                        self._report_progress(
                            on_progress, "failed", f"{step_num}: {desc}",
                            len(completed_steps), len(completed_steps) + len(steps),
                        )
                        return MissionExecutionResult(msg, status="failed")

                    except Exception as e:
                        error_msg = str(e)
                        self._report_action(
                            on_action, action_count, tool, desc, params, error_msg, "failed"
                        )
                        print(
                            f"[Executor] Step {step_num} attempt {attempt} failed; "
                            "evaluating recovery."
                        )

                        recovery = analyze_error(step, error_msg, attempt=attempt)
                        decision = recovery["decision"]
                        user_msg = recovery.get("user_message", "")

                        if speak and user_msg:
                            speak(user_msg)

                        if decision == ErrorDecision.RETRY:
                            attempt += 1
                            if cancel_flag:
                                cancel_flag.wait(2)
                            else:
                                time.sleep(2)
                            continue

                        elif decision == ErrorDecision.SKIP:
                            print(f"[Executor] â­ï¸ Skipping step {step_num}")
                            completed_steps.append(step)
                            self._report_progress(
                                on_progress, "running", f"{step_num}: {desc}",
                                len(completed_steps), len(completed_steps) + len(steps),
                            )
                            step_ok = True
                            break

                        elif decision == ErrorDecision.ABORT:
                            msg = f"Task aborted, sir. {recovery.get('reason', '')}"
                            if speak: speak(msg)
                            return MissionExecutionResult(msg, status="failed")

                        else: 
                            fix_suggestion = recovery.get("fix_suggestion", "")
                            if fix_suggestion and tool != "generated_code":
                                try:
                                    action_limit = max_actions_per_mission()
                                    if action_count >= action_limit:
                                        msg = (
                                            "Task stopped because it reached the "
                                            f"{action_limit}-action mission limit."
                                        )
                                        if speak:
                                            speak(msg)
                                        # Return a proper result object: reporting a
                                        # bare string here made the mission look
                                        # "completed" even after the action limit.
                                        return MissionExecutionResult(msg, status="partial")
                                    fixed_step = generate_fix(step, error_msg, fix_suggestion)
                                    if speak: speak("Trying an alternative approach, sir.")
                                    action_count += 1
                                    res = _call_tool_with_timeout(
                                        fixed_step["tool"],
                                        fixed_step["parameters"],
                                        speak,
                                        cancel_flag,
                                        approval_callback,
                                        mission_id,
                                        mission_deadline - time.monotonic(),
                                        tool_registry,
                                    )
                                    if res.strip().lower().startswith("blocked for safety:"):
                                        self._report_action(
                                            on_action,
                                            action_count,
                                            fixed_step["tool"],
                                            fixed_step.get("description", desc),
                                            fixed_step["parameters"],
                                            res,
                                            "blocked",
                                        )
                                        return MissionExecutionResult(
                                            f"Task stopped; no action was taken. {res}",
                                            status="blocked",
                                        )
                                    self._report_action(
                                        on_action,
                                        action_count,
                                        fixed_step["tool"],
                                        fixed_step.get("description", desc),
                                        fixed_step["parameters"],
                                        res,
                                        "completed",
                                    )
                                    step_results[step_num] = res
                                    last_action_result = res
                                    completed_steps.append(step)
                                    self._report_progress(
                                        on_progress, "running", f"{step_num}: {desc}",
                                        len(completed_steps), len(completed_steps) + len(steps),
                                    )
                                    step_ok = True
                                    break
                                except Exception as fix_err:
                                    print("[Executor] Recovery action failed; details omitted.")

                            failed_step  = step
                            failed_error = error_msg
                            success      = False
                            break

                if not step_ok and not failed_step:
                    failed_step  = step
                    failed_error = "Max retries exceeded"
                    success      = False

                if not success:
                    break

            if success:
                if cancel_flag and cancel_flag.is_set():
                    raise MissionCancelled("Mission cancelled before final reporting.")
                remaining_s = mission_deadline - time.monotonic()
                if remaining_s <= 0:
                    return MissionExecutionResult(
                        "Actions were executed, but reporting exceeded the mission time limit.",
                        status="partial",
                    )
                verified = bool(getattr(last_action_result, "verified", False))
                result = self._summarize(
                    goal,
                    completed_steps,
                    speak,
                    timeout_s=min(1800, max(1, int(remaining_s))),
                    verified=verified,
                )
                self._report_progress(
                    on_progress, "completed" if verified else "partial", "", len(completed_steps),
                    len(completed_steps),
                )
                return MissionExecutionResult(
                    result,
                    status="completed" if verified else "partial",
                    verified=verified,
                )

            if time.monotonic() >= mission_deadline:
                return MissionExecutionResult(
                    "Mission stopped at its configured duration limit.",
                    status="partial",
                )
            if replan_attempts >= max_replans_per_mission():
                msg = f"Task failed after {replan_attempts} replan attempts, sir."
                if speak: speak(msg)
                return MissionExecutionResult(msg, status="failed")

            if speak: speak("Adjusting my approach, sir.")

            replan_attempts += 1
            if cancel_flag and cancel_flag.is_set():
                raise MissionCancelled("Mission cancelled before replanning.")
            remaining_s = mission_deadline - time.monotonic()
            plan = replan(
                goal,
                completed_steps,
                failed_step,
                failed_error,
                context=resume_context,
                timeout_s=min(1800, max(1, int(remaining_s))),
                registry=tool_registry,
            )

    @staticmethod
    def _report_action(callback, number, tool, description, parameters, result, status):
        try:
            from logger import log
            log(
                f"AGENT_ACTION number={number} tool={tool} status={status}",
                level="INFO",
            )
        except Exception as exc:
            print(f"[Executor] Could not write action audit log: {exc}")
        if callback is None:
            return
        try:
            from safety import sanitize
            safe_parameters = sanitize(tool, parameters)
        except Exception as exc:
            print(f"[Executor] Could not sanitize action history: {exc}")
            safe_parameters = {"redacted": True}
        safe_result = str(result)[:800]
        safe_description = str(description)[:200]
        try:
            from agent.secrets import detect_sensitive_data
            from logger import is_private_tool_data
            if is_private_tool_data(tool):
                safe_result = "[private result omitted]"
            elif detect_sensitive_data(safe_result):
                safe_result = "[result omitted because it may contain sensitive data]"
            if detect_sensitive_data(safe_description):
                safe_description = "[sensitive action description omitted]"
        except Exception as exc:
            print(f"[Executor] Could not classify action data for history: {exc}")
            safe_result = "[result omitted]"
            safe_description = "[action description omitted]"
        safe_result = re.sub(
            r"(?i)\b(password|passcode|secret|api[_ -]?key|access[_ -]?token|"
            r"cookie|authorization)\b([\"']?\s*[:=]\s*[\"']?)[^\r\n,}\"']+",
            r"\1\2[REDACTED]",
            safe_result,
        )
        try:
            callback({
                "number": number,
                "tool": tool,
                "description": safe_description,
                "parameters": safe_parameters,
                "result": safe_result,
                "status": status,
            })
        except Exception as exc:
            print(f"[Executor] Action-history callback failed: {exc}")

    def _summarize(
        self,
        goal: str,
        completed_steps: list,
        speak: Callable | None,
        timeout_s: int | None = None,
        verified: bool = False,
    ) -> str:
        verification_note = (
            "The final tool returned explicit verification evidence."
            if verified else
            "The final outcome was not independently verified."
        )
        fallback = (
            f"Executed {len(completed_steps)} planned step(s) for: {goal[:60]}. "
            f"{verification_note}"
        )
        try:
            from api_keys import GeminiModel
            model     = GeminiModel(
                model_name="gemini-3.5-flash-lite",
                timeout_s=timeout_s,
            )
            steps_str = "\n".join(f"- {s.get('description', '')}" for s in completed_steps)
            prompt    = (
                f'User goal: "{goal}"\n'
                f"Completed steps:\n{steps_str}\n\n"
                "Write a single natural sentence summarizing only the actions listed. "
                "Do not infer success beyond the listed steps. "
                f"{verification_note} Address the user as 'sir'."
            )
            response = model.generate_content(prompt)
            summary  = response.text.strip()
            if speak: speak(summary)
            return summary
        except Exception as exc:
            print(f"[Executor] Final summary unavailable: {type(exc).__name__}.")
            if speak: speak(fallback)
            return fallback

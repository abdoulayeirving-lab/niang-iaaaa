import json
import re
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
MAX_PLAN_STEPS = 5
ALLOWED_TOOLS = {
    "open_app", "web_search", "game_updater", "browser_control",
    "file_controller", "notify", "daily_briefing", "wake_word",
    "cmd_control", "computer_settings", "computer_control", "system_status",
    "task_manager", "clipboard", "recall_memory", "vision_gesture",
    "screen_process", "send_message", "reminder", "desktop_control",
    "youtube_video", "weather_report", "flight_finder", "code_helper",
    "dev_agent", "vision_click", "gmail", "read_pdf",
    "pdf_qa", "autostart", "monitor_alerts", "email_watch", "pc_health",
    "translate", "media_control", "read_document", "document_qa", "search_documents", "calendar",
    "drive", "schedule", "create_presentation", "create_spreadsheet",
    "smart_home_control", "create_document", "analyze_data",
}


PLANNER_PROMPT = """You are the planning module of NIANG IA, a personal AI assistant.
Your job: break any user goal into a sequence of steps using ONLY the tools listed below.

ABSOLUTE RULES:
- NEVER use generated_code or write Python scripts. It does not exist.
- NEVER reference previous step results in parameters. Every step is independent.
- Use web_search for ANY information retrieval, research, or current data.
- Use file_controller to save content to disk.
- Use cmd_control to open files or run system commands.
- Max 5 steps. Use the minimum steps needed.

AVAILABLE TOOLS AND THEIR PARAMETERS:

open_app
  app_name: string (required)

web_search
  query: string (required) — write a clear, focused search query
  mode: "search" or "compare" (optional, default: search)
  items: list of strings (optional, for compare mode)
  aspect: string (optional, for compare mode)

game_updater
  action: "update" | "install" | "list" | "download_status" | "schedule" (required)
  platform: "steam" | "epic" | "both" (optional, default: both)
  game_name: string (optional)
  app_id: string (optional)
  shutdown_when_done: boolean (optional)

browser_control
  action: "go_to" | "search" | "inspect" | "click" | "type" | "scroll" | "fill_form" | "get_text" | "press" | "close" (required)
  url: string (for go_to)
  query: string (for search)
  text: string (for click/type)
  fields: object mapping CSS selectors to values (for fill_form; does not submit)
  direction: "up" | "down" (for scroll)

file_controller
  action: "write" | "create_file" | "read" | "list" | "delete" | "move" | "copy" | "find" | "disk_usage" | "zip" | "unzip" (required)
  path: string — use "desktop" for Desktop folder
  name: string — filename
  content: string — file content (for write/create_file)
  destination: string — target for move/copy/zip/unzip

notify
  message: string (required) — notification text
  title: string (optional)

daily_briefing
  city: string (optional) — weather defaults to saved memory

wake_word
  action: "start" | "stop" | "status" (required) — hands-free 'Hey Kaizumi' listener

cmd_control
  task: string (required) — natural language description of what to do
  visible: boolean (optional)

computer_settings
  action: string (required)
  description: string — natural language description
  value: string (optional)

computer_control
  action: "type" | "click" | "hotkey" | "press" | "scroll" | "screenshot" | "screen_find" | "screen_click" | "list_windows" | "focus_window" (required)
  text: string (for type)
  x, y: int (for click)
  keys: string (for hotkey, e.g. "ctrl+c")
  key: string (for press)
  direction: "up" | "down" (for scroll)
  description: string (for screen_find/screen_click)
  title: string (for focus_window)

system_status
  focus: "overview" | "battery" | "cpu" | "memory" | "disk" | "network" | "processes" | "uptime" (optional, default: overview)

task_manager
  action: "status" | "list" | "cancel" (required)
  task_id: string (for status/cancel)

clipboard
  action: "get" | "set" | "paste" | "clear" | "history" | "copy_last" (required)
  text: string (for set)

recall_memory
  query: string (required)
  category: "identity" | "preferences" | "projects" | "relationships" | "wishes" | "notes" (optional)

vision_gesture
  action: "start" | "stop" | "face_count" | "qr" | "snapshot" | "status" (required)
  mode: "gesture" | "air_mouse" | "volume" | "motion" | "posture" | "focus" (for start)

screen_process
  text: string (required) — what to analyze or ask about the screen
  angle: "screen" | "camera" (optional)

send_message
  receiver: string (required)
  message_text: string (required)
  platform: string (required)

reminder
  date: string YYYY-MM-DD (required)
  time: string HH:MM (required)
  message: string (required)

desktop_control
  action: "wallpaper" | "organize" | "clean" | "list" | "task" (required)
  path: string (optional)
  task: string (optional)

youtube_video
  action: "play" | "summarize" | "trending" (required)
  query: string (for play)

weather_report
  city: string (required)

flight_finder
  origin: string (required)
  destination: string (required)
  date: string (required)

code_helper
  action: "write" | "edit" | "run" | "explain" (required)
  description: string (required)
  language: string (optional)
  output_path: string (optional)
  file_path: string (optional)

search_documents
  query: search terms or a question about personal documents
  folder: "Documents" | "Downloads" | "Desktop" | "all" | a specific folder path
  Matching excerpts are returned to Gemini; search only the requested folders.

create_document
  title: document title
  filename: optional filename
  sections: list of objects with title, body (paragraphs), bullets, optional table {headers, rows}
  Create detailed, complete content appropriate to the user's request.

analyze_data
  source: local .csv or .xlsx file
  report_name: optional report filename
  Creates a local descriptive-statistics report; dataset contents stay on this computer.

dev_agent
  description: string (required)
  language: string (optional)
  action: "turn_on" | "turn_off" | "toggle" | "set_level" | "set_temperature" |
          "open_cover" | "close_cover" | "lock" | "unlock" |
          "activate_scene" | "status"
  device: configured device id/name
  area: configured Home Assistant area id/name (turn_on/turn_off only)
  value: brightness percent or target temperature

EXAMPLES:

Goal: "research mechanical engineering and save it to a notepad file"
Steps:

web_search | query: "mechanical engineering overview definition history"
web_search | query: "mechanical engineering applications and future trends"
file_controller | action: write, path: desktop, name: mechanical_engineering.txt, content: "MECHANICAL ENGINEERING RESEARCH\n\nThis file will be filled with web research results."
cmd_control | task: "open mechanical_engineering.txt on desktop with notepad"

Goal: "What is the price of Bitcoin"
Steps:

web_search | query: "Bitcoin price today USD"

Goal: "List the files on the desktop and find the largest 5 files"
Steps:

file_controller | action: list, path: desktop
file_controller | action: largest, path: desktop, count: 5

Goal: "Install PUBG from Steam"
Steps:

game_updater | action: install, platform: steam, game_name: "PUBG"

Goal: "Update all my Steam games"
Steps:

game_updater | action: update, platform: steam

Goal: "Send John a message on WhatsApp saying there is a meeting tomorrow"
Steps:

send_message | receiver: John, message_text: "There is a meeting tomorrow", platform: WhatsApp

Goal: "Open the clock and set a reminder for 30 minutes later"
Steps:

reminder | date: [today], time: [now+30min], message: "Reminder"

OUTPUT — return ONLY valid JSON, no markdown, no explanation, no code blocks:
{
  "goal": "...",
  "steps": [
    {
      "step": 1,
      "tool": "tool_name",
      "description": "what this step does",
      "parameters": {},
      "critical": true
    }
  ]
}
"""


def _get_api_key() -> str:
    from api_keys import next_key
    return next_key()


def _validate_plan(plan: dict, goal: str) -> dict:
    """Reject malformed or unbounded model output before any tool can run."""
    steps = plan.get("steps") if isinstance(plan, dict) else None
    if not isinstance(steps, list) or not steps or len(steps) > MAX_PLAN_STEPS:
        raise ValueError(f"Plan must contain 1 to {MAX_PLAN_STEPS} steps.")

    validated = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"Plan step {index} must be an object.")
        tool = step.get("tool")
        description = step.get("description")
        parameters = step.get("parameters", {})
        if tool not in ALLOWED_TOOLS:
            raise ValueError(f"Unsupported plan tool at step {index}: {tool!r}.")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"Plan step {index} needs a description.")
        if not isinstance(parameters, dict):
            raise ValueError(f"Plan step {index} parameters must be an object.")
        validated.append({
            "step": index,
            "tool": tool,
            "description": description.strip()[:500],
            "parameters": parameters,
            "critical": bool(step.get("critical", True)),
        })

    return {"goal": str(plan.get("goal") or goal), "steps": validated}


def create_plan(goal: str, context: str = "") -> dict:
    import google.generativeai as genai

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(
        model_name="gemini-3.5-flash-lite",
        system_instruction=PLANNER_PROMPT
    )

    user_input = f"Goal: {goal}"
    if context:
        user_input += f"\n\nContext: {context}"

    try:
        response = model.generate_content(user_input)
        text     = response.text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()

        plan = json.loads(text)

        plan = _validate_plan(plan, goal)

        print(f"[Planner] ✅ Plan: {len(plan['steps'])} steps")
        for s in plan["steps"]:
            print(f"  Step {s['step']}: [{s['tool']}] {s['description']}")

        return plan

    except json.JSONDecodeError as e:
        print(f"[Planner] ⚠️ JSON parse failed: {e}")
        return _fallback_plan(goal)
    except Exception as e:
        print(f"[Planner] ⚠️ Planning failed: {e}")
        return _fallback_plan(goal)


def _fallback_plan(goal: str) -> dict:
    print("[Planner] 🔄 Fallback plan")
    return {
        "goal": goal,
        "steps": [
            {
                "step": 1,
                "tool": "web_search",
                "description": f"Search for: {goal}",
                "parameters": {"query": goal},
                "critical": True
            }
        ]
    }


def replan(goal: str, completed_steps: list, failed_step: dict, error: str) -> dict:
    import google.generativeai as genai

    genai.configure(api_key=_get_api_key())
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash",
        system_instruction=PLANNER_PROMPT
    )

    completed_summary = "\n".join(
        f"  - Step {s['step']} ({s['tool']}): DONE" for s in completed_steps
    )

    prompt = f"""Goal: {goal}

Already completed:
{completed_summary if completed_summary else '  (none)'}

Failed step: [{failed_step.get('tool')}] {failed_step.get('description')}
Error: {error}

Create a REVISED plan for the remaining work only. Do not repeat completed steps."""

    try:
        response = model.generate_content(prompt)
        text     = response.text.strip()
        text     = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
        plan     = json.loads(text)

        plan = _validate_plan(plan, goal)

        print(f"[Planner] 🔄 Revised plan: {len(plan['steps'])} steps")
        return plan
    except Exception as e:
        print(f"[Planner] ⚠️ Replan failed: {e}")
        return _fallback_plan(goal)
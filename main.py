import asyncio
import threading
import json
import sys
import os
import time
import traceback
from pathlib import Path

from logger import setup_logger, log, log_tool

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


try:
    import sounddevice as sd
except ModuleNotFoundError:
    sd = None

try:
    from google import genai
    from google.genai import types
except ModuleNotFoundError:
    genai = None
    types = None

from ui import KaizumiUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    should_extract_memory, extract_memory
)
from agent.resilience import ToolResult, run_sync_tool
from agent.loop_guard import LoopGuard

from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import screen_process
from actions.youtube_video     import youtube_video
from actions.cmd_control       import cmd_control
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from actions.system_status     import system_status
from actions.task_manager      import task_manager
from actions.clipboard         import clipboard_action
from actions.vision_gesture    import vision_gesture
from actions.daily_briefing    import daily_briefing
from actions.notifications     import notify
from actions.wake_word         import _service as wake_service
from actions.gmail             import gmail_action
from actions.pdf_reader        import read_pdf as read_pdf_action, pdf_qa
from actions.autostart         import autostart_action
from actions.vision_click      import vision_click_action
from actions.document_qa import (
    read_document as read_document_action,
    document_qa as document_qa_action,
    search_documents as search_documents_action,
)
from actions.data_analysis import analyze_data as analyze_data_action
from actions.monitor           import monitor_action, check_rules as check_monitor_rules, check_email_watch, email_watch_action
from actions.guardian          import guardian_action, check_guardian, battery_health
from actions.translate         import translate_action
from actions.translation_mode import (
    read_live_translation,
    translation_instruction,
    translation_mode_update,
)
from actions.proactive_suggestions import proactive_suggestions as proactive_suggestions_action
from actions.whatsapp_call import (
    WhatsAppCallAssistant,
    whatsapp_call_action,
)
from actions.media_control     import media_control_action
from actions.calendar_actions          import calendar_action
from actions.drive             import drive_action
from vision.live_camera        import LiveCamera


def _record_proactive_usage(tool_name: str) -> None:
    try:
        from actions.proactive_suggestions import record_tool_use
        record_tool_use(tool_name)
    except Exception as exc:
        print(f"[Suggestions] Could not record local usage: {exc}")


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-3.1-flash-live-preview"
THINKING_LEVEL      = "low"  # Gemini 3.1 thinking depth: minimal | low | medium | high
TG_MODEL            = "gemini-2.5-flash"

TG_HELP_TEXT = (
    "ðŸ¤– <b>NIANG IA â€” Telegram remote control</b>\n"
    "Yozing, men bajaraman. Misollar:\n"
    "â€¢ <code>notepadni och</code>\n"
    "â€¢ <code>Toshkent ob-havosi</code>\n"
    "â€¢ <code>CPU qancha</code>\n"
    "â€¢ <code>menga eslatma qo'y 10 daqiqadan keyin</code>\n"
    "â€¢ <code>clipboard'ni ko'rsat</code>\n"
    "â€¢ <code>yangi email bormi</code> / <code>email yubor ...</code>\n"
    "â€¢ <code>kalendarimni ko'rsat</code> / <code>ertaga 15:00 da uchrashuv qo'y</code>\n"
    "â€¢ <code>google_auth</code> (Google ulash) / <code>google tekshir</code>\n\n"
    "ðŸŽ¤ Ovozli xabar yuborsangiz ham tushunaman.\n"
    "âš¡ Tezkor tugmalar va <code>/status</code>, <code>/mute</code>, "
    "<code>/unmute</code>, <code>/mode</code>, <code>/voice</code>, "
    "<code>/screenshot</code>, <code>/help</code>."
)

TG_QUICK_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "ðŸ” Status", "callback_data": "/status"},
            {"text": "ðŸ”‡ Mute",  "callback_data": "/mute"},
            {"text": "ðŸ”Š Unmute", "callback_data": "/unmute"},
        ],
        [
            {"text": "ðŸ§­ Mode", "callback_data": "/mode"},
            {"text": "ðŸ—£ Voice", "callback_data": "/voice"},
        ],
        [
            {"text": "ðŸ“¸ Screenshot", "callback_data": "/screenshot"},
            {"text": "â“ Help", "callback_data": "/help"},
        ],
    ]
}

TG_MODE_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "ðŸ˜ Normal",   "callback_data": "/mode normal"},
            {"text": "ðŸ’• Girlfriend", "callback_data": "/mode girlfriend"},
        ],
        [
            {"text": "ðŸ¤ª Crazy Friend", "callback_data": "/mode crazy_friend"},
            {"text": "ðŸŽ© Butler",       "callback_data": "/mode butler"},
        ],
        [
            {"text": "ðŸ¤ Friend",  "callback_data": "/mode friend"},
            {"text": "ðŸ˜Ž Casual",  "callback_data": "/mode casual"},
        ],
    ]
}

TG_VOICE_KEYBOARD = None  # built after VOICE_NAMES is defined below


def _take_screenshot_bytes() -> bytes | None:
    """Capture the whole screen as PNG bytes (for /screenshot)."""
    try:
        import io
        import pyautogui
        buf = io.BytesIO()
        pyautogui.screenshot().save(buf, "PNG")
        return buf.getvalue()
    except Exception:
        return None
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

PHASE_IDLE, PHASE_LISTENING, PHASE_THINKING, PHASE_SPEAKING = (
    "idle", "listening", "thinking", "speaking"
)
MAX_ROLLING_CHARS = 16000


def _ensure_core_deps():
    missing = []
    if sd is None:
        missing.append("sounddevice")
    if genai is None or types is None:
        missing.append("google-genai")

    if not missing:
        return

    missing_str = ", ".join(missing)
    msg = (
        f"\nMissing dependencies: {missing_str}\n\n"
        "Install dependencies for this project:\n"
        f"  {sys.executable} -m pip install -r requirements.txt\n\n"
        "Tip: On Windows, make sure you install into the SAME Python you run.\n"
    )
    raise SystemExit(msg)


def _normalize_mode(text) -> str:
    """Map user wording to a canonical mode id, or '' if unknown."""
    m = (str(text or "").strip().lower()
         .replace("-", " ").replace("_", " "))
    aliases = {
        "normal": "normal", "default": "normal", "standard": "normal",
        "regular": "normal", "profonal": "normal", "professional": "normal",
        "romantic": "girlfriend", "romantic girlfriend": "girlfriend",
        "girlfriend": "girlfriend", "girl": "girlfriend",
        "crazy friend": "crazy_friend", "crazy_friend": "crazy_friend",
        "crazy": "crazy_friend", "funny friend": "crazy_friend",
        "friend": "friend", "friendly": "friend",
        "butler": "butler", "batman's butler": "butler", "butler mode": "butler",
        "alfred": "butler", "servant": "butler",
        "casual": "casual", "chill": "casual",
    }
    m = aliases.get(m, m)
    valid = {"normal", "girlfriend", "crazy_friend", "butler", "friend", "casual"}
    return m if m in valid else ""


VOICES = {
    "Achernar":      "mayin (Soft)",
    "Achird":        "do'stona (Friendly)",
    "Algenib":       "bo'g'iq (Gravelly)",
    "Algieba":       "silliq (Smooth)",
    "Alnilam":       "qat'iy (Firm)",
    "Aoede":         "engil ayol (Breezy)",
    "Autonoe":       "yorqin (Bright)",
    "Callirrhoe":    "erkin (Easy-going)",
    "Charon":        "chuqur erkak (Informative)",
    "Despina":       "silliq (Smooth)",
    "Enceladus":     "nafasli (Breathy)",
    "Erinome":       "aniq (Clear)",
    "Fenrir":        "qattiq erkak (Excitable)",
    "Gacrux":        "etuk (Mature)",
    "Iapetus":       "aniq (Clear)",
    "Kore":          "jonli ayol (Firm)",
    "Laomedeia":     "quvnoq (Upbeat)",
    "Leda":          "yoshlik (Youthful)",
    "Orus":          "qat'iy erkak (Firm)",
    "Puck":          "quvnoq erkak (Upbeat)",
    "Pulcherrima":   "dadil (Forward)",
    "Rasalgethi":    "ma'lumotli (Informative)",
    "Sadachbia":     "jonli (Lively)",
    "Sadaltager":    "bilimdon (Knowledgeable)",
    "Schedar":       "tinch (Even)",
    "Sulafat":       "iliq (Warm)",
    "Umbriel":       "erkin (Easy-going)",
    "Vindemiatrix":  "muloyim (Gentle)",
    "Zephyr":        "yorqin ayol (Bright)",
    "Zubenelgenubi": "oddiy (Casual)",
}
VOICE_NAMES = list(VOICES.keys())

TG_VOICE_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": f"ðŸŽ™ {name}", "callback_data": f"/voice {name}"}
            for name in VOICE_NAMES[i:i + 2]
        ]
        for i in range(0, len(VOICE_NAMES), 2)
    ]
}


def _normalize_voice(text) -> str:
    """Map user wording to a canonical Gemini voice name, or '' if unknown."""
    v = (str(text or "").strip().lower()
         .replace("-", " ").replace("_", " "))
    aliases = {
        "default": "Aoede", "auto": "Aoede", "standart": "Aoede",
        "normal": "Aoede", "classic": "Aoede",
        "aoede": "Aoede", "charon": "Charon", "fenrir": "Fenrir",
        "kore": "Kore", "puck": "Puck", "zephyr": "Zephyr",
        "ayol": "Aoede", "erkak": "Charon",
    }
    v = aliases.get(v, v.title())
    return v if v in VOICE_NAMES else ""


def _get_style_from_memory(memory: dict | None) -> tuple[str, str]:
    """
    Returns (mode, mood).
    Stored under preferences.assistant_mode / preferences.assistant_mood.
    """
    if not memory:
        return ("normal", "calm")

    prefs = memory.get("preferences", {}) if isinstance(memory, dict) else {}

    mode_entry = prefs.get("assistant_mode")
    mood_entry = prefs.get("assistant_mood")

    mode = mode_entry.get("value") if isinstance(mode_entry, dict) else mode_entry
    mood = mood_entry.get("value") if isinstance(mood_entry, dict) else mood_entry

    mode = _normalize_mode(mode) or "normal"
    mood = (str(mood or "").strip().lower() or "calm")

    valid_moods = {"calm", "playful", "romantic", "strict"}

    if mood not in valid_moods:
        mood = "calm"

    return (mode, mood)


def _get_voice_from_memory(memory: dict | None) -> str:
    """Returns the saved Gemini voice name (defaults to Aoede)."""
    prefs = memory.get("preferences", {}) if isinstance(memory, dict) else {}
    entry = prefs.get("assistant_voice")
    voice = entry.get("value") if isinstance(entry, dict) else entry
    voice = _normalize_voice(voice)
    return voice or "Aoede"


def _get_voice_style_from_memory(memory: dict | None) -> str:
    """Return the saved delivery style, defaulting to natural speech."""
    prefs = memory.get("preferences", {}) if isinstance(memory, dict) else {}
    entry = prefs.get("assistant_voice_style")
    style = entry.get("value") if isinstance(entry, dict) else entry
    style = str(style or "natural").strip().lower()
    return style if style in VOICE_STYLE_GUIDANCE else "natural"


VOICE_STYLE_GUIDANCE = {
    "natural": "Speak naturally with balanced pacing and expression.",
    "calm": "Use a calm, gentle delivery with unhurried pacing.",
    "warm": "Use a warm, friendly delivery while staying clear and natural.",
    "energetic": "Use an upbeat, lively delivery without rushing.",
    "expressive": "Use expressive intonation that fits the meaning of each sentence.",
    "measured": "Use deliberate pacing and crisp articulation.",
}


def _get_api_key() -> str:
    from api_keys import next_key
    return next_key()


def _looks_like_quota(err: str) -> bool:
    e = (err or "").lower()
    return any(tok in e for tok in ("resource_exhausted", "429", "quota", "rate limit"))


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are NIANG IA, a sharp and efficient AI assistant. "
            "NIANG IA was created and developed by Abdoulaye Niang, its sole creator. "
            "He is Senegalese, a student, and passionate about artificial intelligence. "
            "State this clearly when asked who created NIANG IA. Do not claim he created "
            "the underlying AI model or third-party services. "
            "Before screen-dependent actions, inspect the current screen; keep task "
            "context across turns, but let a fresh screen observation override memory. "
            "Reuse an existing visible page when possible. Desktop captures are "
            "point-in-time only, not continuous. Report only actions confirmed by "
            "tool results, and state clearly when a window or tab is inaccessible. "
            "Never invent facts, sources, links, or results, or claim to have searched, "
            "read, executed, launched, or verified something unless you actually did. "
            "Report actions as successful only after a confirming result. State "
            "uncertainty, ask for missing details, and correct errors openly. "
            "For important or changing information, use available tools and reliable "
            "sources; if verification is unavailable, say so. In coding, distinguish "
            "proposed, changed, executed, and tested work; never claim tests passed "
            "unless they ran. Be transparent about access and capabilities. "
            "Be concise, direct, and use the provided tools to complete tasks."
        )


# â”€â”€ HafÄ±za â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_last_memory_input = ""
_memory_lock       = threading.Lock()
_memory_running    = False


def _update_memory_async(user_text: str, assistant_text: str) -> None:
    global _last_memory_input, _memory_running

    user_text   = (user_text   or "").strip()
    assistant_text = (assistant_text or "").strip()

    if len(user_text) < 5 or user_text == _last_memory_input:
        return

    with _memory_lock:
        if _memory_running:
            print("[Memory] â³ Already extracting â€” skipping this turn.")
            return
        _memory_running = True

    _last_memory_input = user_text

    try:
        api_key = _get_api_key()
        if not should_extract_memory(user_text, assistant_text, api_key):
            return
        data = extract_memory(user_text, assistant_text, api_key)
        if data:
            update_memory(data)
            print(f"[Memory] âœ… {list(data.keys())}")
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] âš ï¸ {e}")
    finally:
        with _memory_lock:
            _memory_running = False


# â”€â”€ Tool declarations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Quickly opens Windows applications through a hidden CMD start request; "
            "the recognized name YouTube opens https://www.youtube.com. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Pass only the app/site name, never a CMD command. "
            "Always call this tool â€” never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": (
            "Searches the live web for current facts, news, research, and comparisons. "
            "Use it instead of guessing; summarize results and preserve source URLs."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query"},
                "mode":   {"type": "STRING", "description": "search (default) or compare"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gets real-time weather information for a city.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Windows Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image and RETURNS the analysis "
            "as text. MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. You have NO visual ability without "
            "this tool. After it returns, speak the result naturally. "
            "No other vision channel exists â€” this is the only way to see."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page, "
            "media playback (play/pause/next/previous), and per-app volume "
            "(e.g. 'mute Discord', 'lower Spotify only'). "
            "Use for ANY single computer control command. NEVER route to agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."},
                "app_name":    {"type": "STRING", "description": "App name for per-app volume (e.g. 'Spotify' for app_volume/mute_app)"}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Navigates and reads websites in the browser, inspects visible headings, "
            "links, buttons, and non-password fields, searches pages, and fills fields. "
            "Reuse the current page when possible. This tool controls its own managed "
            "browser page and may not access the user's other browser windows or tabs; "
            "use screen observation and guarded desktop controls for those windows. "
            "Use inspect to discover the actual interface and available selectors. "
            "Base each next step on the actual page result. "
            "Use submit_form only after describing the exact form submission and "
            "receiving explicit user approval; do not use click or Enter to bypass "
            "that confirmation. Never invent page content or claim a change was saved "
            "unless the page confirms it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | inspect | click | type | scroll | fill_form | submit_form | smart_click | smart_type | get_text | press | close"},
                "url":         {"type": "STRING", "description": "URL for go_to action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type or submit_form"},
                "text":        {"type": "STRING", "description": "Text to click or type; submit button text for submit_form"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "fields":      {
                    "type": "ARRAY",
                    "description": "For fill_form: fields to fill; this does not submit the form",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "selector": {"type": "STRING", "description": "CSS selector of the field"},
                            "value": {"type": "STRING", "description": "Value to enter"},
                        },
                        "required": ["selector", "value"],
                    },
                },
                "direction":   {"type": "STRING", "description": "up or down for scroll"},
                "key":         {"type": "STRING", "description": "Key name for press action"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": (
            "Manages files and folders: list, create, delete, move, copy, rename, read, write, "
            "find, disk usage, zip/unzip, and full auto-organization. The 'organize' action "
            "groups loose files into category subfolders (Images, Documents, Spreadsheets, "
            "Code, ...) in mode by_type, by month in by_date, or by AI in mode ai. Use "
            "dry_run=true to preview first. 'undo_organize' restores the last run."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | organize | undo_organize | info | zip | unzip"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "scope":       {"type": "STRING", "description": "For organize: desktop | downloads | documents | pictures | music | videos | home | <custom path>"},
                "mode":        {"type": "STRING", "description": "For organize: by_type (default) | by_date | ai"},
                "dry_run":     {"type": "BOOLEAN", "description": "For organize: preview only, move nothing"},
                "include_subfolders": {"type": "BOOLEAN", "description": "For organize: also process files in subfolders"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy/zip/unzip"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "cmd_control",
        "description": (
            "Runs CMD/terminal commands via natural language: disk space, processes, "
            "system info, network, find files, or anything in the command line."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "task":    {"type": "STRING", "description": "Natural language description of what to do"},
                "visible": {"type": "BOOLEAN", "description": "Open visible CMD window. Default: true"},
                "command": {"type": "STRING", "description": "Optional: exact command if already known"},
            },
            "required": ["task"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "agent_task",
        "description": (
            "Executes complex multi-step tasks requiring multiple different tools. "
            "Examples: 'research X and save to file', 'find and organize files'. "
            "DO NOT use for single commands. NEVER use for Steam/Epic â€” use game_updater."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Complete description of what to accomplish"},
                "priority": {"type": "STRING", "description": "low | normal | high (default: normal)"}
            },
            "required": ["goal"]
        }
    },
    {
        "name": "computer_control",
        "description": (
            "Guarded local Windows UI control: capture screen, inspect accessible "
            "controls, move/click/drag/type, wait for visual changes, and verify "
            "visible outcomes. Observe the current screen before any screen-dependent "
            "action and again after important changes. The screenshot is a point-in-time "
            "view, not continuous monitoring. All input or private-screen actions "
            "require explicit confirmation. Use Ctrl+Alt+Pause as emergency stop "
            "after enabling it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | drag | mouse_down | mouse_up | copy | paste | screenshot | capture_screen | screen_info | active_window | find_ui_elements | wait_for_visual_change | verify_action | stop | enable_emergency_stop | disable_emergency_stop | wait | clear_field | focus_window | screen_describe | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element to find on a fresh screenshot; visual clicks require confidence >= 0.8"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
                "image":       {"type": "STRING",  "description": "Local image template for locating a visible UI element"},
                "button":      {"type": "STRING",  "description": "Mouse button: left | right | middle"},
                "x1":          {"type": "INTEGER", "description": "Drag start X"},
                "y1":          {"type": "INTEGER", "description": "Drag start Y"},
                "x2":          {"type": "INTEGER", "description": "Drag end X"},
                "y2":          {"type": "INTEGER", "description": "Drag end Y"},
                "duration":    {"type": "NUMBER",  "description": "Movement duration in seconds"},
                "timeout":     {"type": "NUMBER",  "description": "Maximum wait duration in seconds"},
                "threshold":   {"type": "NUMBER",  "description": "Minimum mean pixel difference for screen-change detection"},
                "expected":    {"type": "STRING",  "description": "Visible accessible label or text to verify"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "system_status",
        "description": (
            "Reports real-time computer status: battery, CPU, memory/RAM, disk/storage, "
            "network/WiFi, system uptime, and top running processes. "
            "Use when the user asks about system health, performance, battery, storage space, "
            "internet connection, or what's running on the computer."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "focus": {
                    "type": "STRING",
                    "description": "Optional focus area: overview | battery | cpu | memory | disk | network | processes | uptime. Default: overview"
                }
            },
            "required": []
        }
    },
    {
        "name": "set_mode",
        "description": (
            "Sets NIANG IA's conversation mode/persona. "
            "Use when the user says things like: "
            "'girlfriend mode', 'normal mode', 'crazy friend', 'butler mode', "
            "'engaging mode', 'switch your mode', 'o'zgartir'. "
            "This persists across sessions. Modes: "
            "normal | girlfriend | crazy_friend | butler | friend | casual."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mode": {
                    "type": "STRING",
                    "description": "One of: normal | girlfriend | crazy_friend | butler | friend | casual"
                }
            },
            "required": ["mode"]
        }
    },
    {
        "name": "set_voice",
        "description": (
            "Changes NIANG IA's speaking voice (Gemini prebuilt voices). "
            "Use when the user asks to change/switch the voice, or says "
            "'ovozni o'zgartir', 'boshqa ovoz', 'speak with a male voice', "
            "'sounds too robotic'. This persists across sessions and takes "
            "effect shortly. Available voices: "
            + ", ".join(VOICE_NAMES) + "."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "voice": {
                    "type": "STRING",
                    "description": "One of: " + " | ".join(VOICE_NAMES)
                }
            },
            "required": ["voice"]
        }
    },
    {
        "name": "set_mood",
        "description": (
            "Sets NIANG IA's mood/energy within the current mode. "
            "Use when the user asks for calmer, more playful, more romantic, or stricter tone. "
            "This persists across sessions."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mood": {
                    "type": "STRING",
                    "description": "One of: calm | playful | romantic | strict"
                }
            },
            "required": ["mood"]
        }
    },
    {
        "name": "set_voice_style",
        "description": (
            "Changes and saves NIANG IA's spoken delivery style. "
            "Use only when the user asks to adjust how the voice sounds; "
            "this is separate from changing the voice itself or the assistant mood."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "style": {
                    "type": "STRING",
                    "description": "One of: natural | calm | warm | energetic | expressive | measured"
                }
            },
            "required": ["style"]
        }
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving â€” just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity â€” name, age, birthday, city, job, language, nationality | "
                        "preferences â€” favorite food/color/music/film/game/sport, hobbies | "
                        "projects â€” active projects, goals, things being built | "
                        "relationships â€” friends, family, partner, colleagues | "
                        "wishes â€” future plans, things to buy, travel dreams | "
                        "notes â€” habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Alex, pizza, older sister)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "recall_memory",
        "description": (
            "Search long-term memory for a stored fact about the user. "
            "Use when the user asks 'do you remember...', 'what do you know about...', "
            "'what's my favorite...', or when you need a saved detail mid-conversation "
            "(name, preferences, projects, people). Returns what you know."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":    {"type": "STRING", "description": "What to look for (e.g. 'favorite food', 'sister', 'project')"},
                "category": {"type": "STRING", "description": "Optional: identity | preferences | projects | relationships | wishes | notes"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "forget_memory",
        "description": (
            "Delete a specific fact from long-term memory. "
            "Use when the user asks to forget/remove something they told you, "
            "e.g. 'forget that I like X', 'remove my name from memory'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "key":      {"type": "STRING", "description": "The key to remove (e.g. 'name', 'favorite_food', 'sister_name')"},
                "category": {"type": "STRING", "description": "Category containing the key: identity | preferences | projects | relationships | wishes | notes (default notes)"}
            },
            "required": ["key"]
        }
    },
    {
        "name": "clear_memory",
        "description": (
            "Clear all long-term memory, or just one category. "
            "Use when the user asks to clear/reset memory, e.g. 'forget everything'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {"type": "STRING", "description": "Optional: only clear this category (identity | preferences | projects | relationships | wishes | notes). Empty = clear everything."}
            },
            "required": []
        }
    },
    {
        "name": "task_manager",
        "description": (
            "Check or control background agent tasks started via agent_task. "
            "Reports the current phase, completed step count, and active step. "
            "Use for: 'how is my task going?', 'status of my task', 'cancel that task', "
            "'what tasks are running?'. You get a task_id when you start agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "status | list | cancel"},
                "task_id": {"type": "STRING", "description": "Task ID for status/cancel"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "clipboard",
        "description": (
            "Manage the system clipboard: read what's copied, copy text, paste it, "
            "clear it, or recall recent copied items. "
            "Use for 'copy that to clipboard', 'what's on my clipboard?', 'paste it'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "get | set | paste | clear | history | copy_last"},
                "text":   {"type": "STRING", "description": "Text for set/copy action"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "vision_gesture",
        "description": (
            "Full-body computer vision using the camera. Free, local, no AI API. "
            "Modes (continuous): 'gesture' recognizes hand gestures and finger counts; "
            "'air_mouse' moves the cursor with the index finger (pinch to click); "
            "'volume' controls volume via thumb-index pinch; 'motion' detects movement; "
            "'posture' reports body pose (arms raised, leaning); 'objects' runs YOLO object detection. "
            "One-shot actions: 'face_count' counts people, 'qr' reads a QR code, 'ocr' reads text, "
            "'background_remove' saves a transparent subject cutout, 'describe' captions the scene, "
            "'vqa' answers a question about the scene, 'register_face' enrolls a local face profile, "
            "'identify_face'/'verify_identity' recognizes an enrolled face, 'multimodal' asks the configured vision model, "
            "'snapshot' describes what's on camera. "
            "Use when the user asks about gestures, wants hand control, or camera actions."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "start | stop | record_start | record_stop | face_count | qr | ocr | background_remove | describe | vqa | register_face | identify_face | verify_identity | multimodal | snapshot | status"},
                "mode":   {"type": "STRING", "description": "gesture | air_mouse | volume | motion | posture | objects (for start)"},
                "text":   {"type": "STRING", "description": "Optional question, OCR text, or face profile name"},
                "name":   {"type": "STRING", "description": "Face profile name for register_face"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "live_camera",
        "description": (
            "Opt-in live webcam input for the current Gemini Live conversation. "
            "Frames are streamed to Gemini approximately once per second while enabled. "
            "Only start after the user directly asks to turn on or use the live camera; "
            "the UI displays a red LIVE CAMERA indicator while streaming. "
            "Stop immediately when asked. Camera streaming stops automatically when "
            "the Gemini session disconnects."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "start | stop | status"
                }
            },
            "required": ["action"]
        }
    },
    {
        "name": "notify",
        "description": (
            "Sends a Windows toast notification popup (title + message). "
            "Use when the user asks to notify/alert me at a moment, pop a notification, "
            "or remind me with a popup, e.g. 'notify me when the download finishes'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "message": {"type": "STRING", "description": "The notification message text (required)"},
                "title":   {"type": "STRING", "description": "Optional title (default: NIANG IA)"}
            },
            "required": ["message"]
        }
    },
    {
        "name": "daily_briefing",
        "description": (
            "Morning briefing: today's date/time, weather for the user's city, "
            "key facts remembered about them, and system status. "
            "Use when the user says 'good morning', 'daily briefing', 'brief me', "
            "or asks what's going on today."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "Optional city for weather (defaults to saved memory)"}
            },
            "required": []
        }
    },
    {
        "name": "schedule",
        "description": (
            "Sets a timed in-app action that fires after a number of seconds. "
            "When it fires, NIANG IA speaks the message and sends a notification "
            "to the connected phone. Also lists and cancels pending schedules. "
            "Use for countdowns, 'remind me in X minutes', timers, or delayed tasks."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "set | list | cancel (default: list)"},
                "seconds": {"type": "INTEGER", "description": "Delay in seconds (set only, min 10)"},
                "message": {"type": "STRING", "description": "What to say/notify when it fires"},
                "id":      {"type": "INTEGER", "description": "Schedule id to cancel"}
            },
            "required": []
        }
    },
    {
        "name": "wake_word",
        "description": (
            "Controls the hands-free wake word listener ('Hey Kaizumi'). "
            "When active, Kaizumi sleeps until the wake word is said, then listens. "
            "'record' samples your voice and builds a 'Hey Kaizumi' reference. "
            "Use when the user says 'activate wake word', 'record the wake word', "
            "'listen for hey kaizumi', or any wake-word command."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "start | stop | status | record (default: status)"},
                "clips":  {"type": "INTEGER", "description": "Number of clips to record for 'record' (default: 5)"}
            },
            "required": []
        }
    },
    {
        "name": "create_presentation",
        "description": (
            "Generates a PowerPoint (.pptx) file from a simple request and saves it "
            "to Documents/Kaizumi. Use for 'make me a presentation about X', "
            "'create slides about Y'. Pass the topic as title and the slides with "
            "their bullet points. After creating, tell the user where it was saved."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {
                    "type": "STRING",
                    "description": "Presentation title / topic"
                },
                "filename": {
                    "type": "STRING",
                    "description": "Optional file name without extension (defaults to title)"
                },
                "slides": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "title":   {"type": "STRING", "description": "Slide heading"},
                            "bullets": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Bullet points for the slide"}
                        },
                        "required": ["title"]
                    },
                    "description": "List of slides, each with a title and bullet points"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "create_document",
        "description": (
            "Creates a complete structured Word document (.docx) in "
            "Documents/Kaizumi. Generate substantial, organized content from the "
            "user's request with a title and sections containing prose, bullets, "
            "and optional tables. After creating, report the exact saved path."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title": {"type": "STRING", "description": "Document title"},
                "filename": {"type": "STRING", "description": "Optional filename without extension"},
                "author": {"type": "STRING", "description": "Optional document author"},
                "sections": {
                    "type": "ARRAY",
                    "description": "Ordered document sections; create enough detail to satisfy the user's request",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "title": {"type": "STRING", "description": "Section heading"},
                            "level": {"type": "INTEGER", "description": "Heading level 1-3 (default 1)"},
                            "body": {"type": "STRING", "description": "Section prose; use newline-separated paragraphs"},
                            "bullets": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Optional bullet list"},
                            "table": {
                                "type": "OBJECT",
                                "properties": {
                                    "headers": {"type": "ARRAY", "items": {"type": "STRING"}},
                                    "rows": {"type": "ARRAY", "items": {"type": "ARRAY", "items": {"type": "STRING"}}}
                                }
                            }
                        }
                    }
                }
            },
            "required": ["title", "sections"]
        }
    },
    {
        "name": "analyze_data",
        "description": (
            "Analyzes a local CSV or Excel .xlsx dataset and creates a Word "
            "report with row counts, missing values, numeric min/max/mean/median, "
            "and most frequent categories. Analysis is deterministic and local; "
            "dataset contents are not sent to Gemini. Processes at most 10,000 "
            "rows, 50 columns, and 20 MB. Use when the user asks for an analysis "
            "report from a data file."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "source": {"type": "STRING", "description": "Path or filename of a local CSV or .xlsx file"},
                "report_name": {"type": "STRING", "description": "Optional Word report filename without extension"}
            },
            "required": ["source"]
        }
    },
    {
        "name": "video_studio",
        "description": (
            "NIANG IA Video Studio: inspect a local video with OpenCV, report "
            "metadata and sampled visual-change candidates, save a local JSON "
            "report, or create a new polished promo edit with phrase-aligned "
            "smooth-wipe/dissolve transitions, synchronized audio crossfades, "
            "burnt-in captions, subtle reframing, and normalized audio. Edit "
            "requires a local video with subtitles and CapCut-bundled FFmpeg; "
            "it never changes the source and does not create a CapCut project. "
            "Media is not uploaded. Use status to check available editor support."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "status | analyze | edit"},
                "source": {"type": "STRING", "description": "Full local video path; required for analyze or edit"},
                "style": {"type": "STRING", "description": "Optional intended style; not yet applied automatically"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "create_spreadsheet",
        "description": (
            "Creates an Excel (.xlsx) spreadsheet with headers and data rows and saves it "
            "to Documents/Kaizumi. Use for 'make a spreadsheet of ...', "
            "'create a table with columns ... and these values'. "
            "After creating, tell the user where it was saved."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "filename":  {"type": "STRING", "description": "File name without extension"},
                "sheet_name": {"type": "STRING", "description": "Optional sheet name (default: Sheet1)"},
                "headers":   {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Column headers"},
                "rows":      {"type": "ARRAY", "items": {"type": "ARRAY", "items": {"type": "STRING"}}, "description": "Data rows; each row is an array of cell values"}
            },
            "required": ["filename"]
        }
    },
    {
        "name": "smart_home_control",
        "description": (
            "Controls configured lights, switches, fans, covers, thermostats, locks, "
            "media players, scenes, and Home Assistant areas. Actions: turn_on, turn_off, "
            "toggle, set_level, set_temperature, open_cover, close_cover, lock, unlock, "
            "activate_scene, status. To control a whole room, pass its configured area "
            "name/id and turn_on or turn_off. Destructive or sensitive actions require "
            "explicit confirmation."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "turn_on | turn_off | toggle | set_level | set_temperature | open_cover | close_cover | lock | unlock | activate_scene | status"},
                "device": {"type": "STRING", "description": "Device id or name from smart_home.json"},
                "area":   {"type": "STRING", "description": "Configured Home Assistant area id/name for turn_on or turn_off"},
                "value":  {"type": "NUMBER", "description": "Brightness percent for set_level, or temperature for set_temperature"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "gmail",
        "description": (
            "Sends and reads Gmail. 'send' composes an email to any address; "
            "'read' lists the most recent inbox emails. Requires a Gmail app "
            "password saved in config/api_keys.json (gmail_user + "
            "gmail_app_password). Use for 'send an email to X', 'check my email', "
            "'what is in my inbox'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "send | read (default: send)"},
                "to":      {"type": "STRING", "description": "Recipient email address (send only)"},
                "subject": {"type": "STRING", "description": "Email subject (send only)"},
                "body":    {"type": "STRING", "description": "Email body text (send only)"},
                "limit":   {"type": "INTEGER", "description": "How many recent emails to read (read only, default 5)"}
            },
            "required": []
        }
    },
    {
        "name": "read_pdf",
        "description": (
            "Reads a PDF file and shows a preview of its content (page count and "
            "opening text). Give the file name or path, e.g. 'manual.pdf' or "
            "'C:\\Users\\you\\Documents\\manual.pdf'. Use for 'open/read the PDF', "
            "'what is in this document'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path": {"type": "STRING", "description": "PDF file name or full path"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "pdf_qa",
        "description": (
            "Answers a question about the contents of a PDF file. Finds the "
            "relevant parts of the document and answers from them. Use for "
            "'what does the PDF say about X', 'summarize this document', "
            "'find Y in the manual'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "path":     {"type": "STRING", "description": "PDF file name or full path"},
                "question": {"type": "STRING", "description": "Question about the document's content"}
            },
            "required": ["path", "question"]
        }
    },
    {
        "name": "autostart",
        "description": (
            "Controls whether NIANG IA starts automatically at Windows login. "
            "Actions: status | enable | disable. 'enable' registers NIANG IA in "
            "the startup list (optionally with the Bluetooth phone transport via "
            "'remote'). Use for 'start at login', 'run on startup', 'open automatically'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "status | enable | disable (default: status)"},
                "remote": {"type": "BOOLEAN", "description": "For 'enable': also start the Bluetooth transport (default true)"}
            },
            "required": []
        }
    },
    {
        "name": "vision_click",
        "description": (
            "Clicks anywhere on the screen by looking at it. Describe the element "
            "to click ('the Send button', 'the Chrome icon', 'the search box') and "
            "NIANG IA finds it on the screenshot and clicks it. Use for 'click the "
            "Send button', 'press the green button', 'click on the search field'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "target":      {"type": "STRING", "description": "What to click, in plain words"},
                "click":       {"type": "STRING", "description": "Optional: 'double' for a double-click"},
                "only_coords": {"type": "BOOLEAN", "description": "Optional: return coordinates without clicking"}
            },
            "required": ["target"]
        }
    },
    {
        "name": "monitor_alerts",
        "description": (
            "Sets PC monitoring alerts: warn when CPU, RAM, disk or battery "
            "crosses a threshold, then NIANG IA speaks + notifies the phone. "
            "Actions: list | add | remove | check | status. "
            "Use for 'alert me when cpu goes above 90', 'warn me when my battery "
            "is below 20 percent', 'tell me if ram is high', 'monitor the pc'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING", "description": "list | add | remove | check | status (default: list)"},
                "kind":      {"type": "STRING", "description": "Metric to watch: cpu | ram | disk | battery"},
                "threshold": {"type": "NUMBER", "description": "Percent threshold to trigger"},
                "above":     {"type": "BOOLEAN", "description": "True=alert above threshold (cpu/ram/disk), false=alert below (battery). Default true."},
                "message":   {"type": "STRING", "description": "Optional custom alert message"},
                "id":        {"type": "INTEGER", "description": "Alert id to remove"}
            },
            "required": []
        }
    },
    {
        "name": "pc_health",
        "description": (
            "PC Health Guardian: automatic proactive alerts for battery, disk "
            "space, RAM, CPU, temperature and backup reminders â€” works out of "
            "the box with smart defaults, no setup needed. "
            "Actions: status | report | enable | disable | check | backup | "
            "set | reset. Use for 'pc health report', 'how is my battery', "
            "'battery health', 'health check', 'backup done', 'stop monitoring', "
            "'warn me about low disk'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "status | report | enable | disable | check | backup | set | reset (default: status)"},
                "key":    {"type": "STRING", "description": "Setting to change with 'set': battery_low | battery_full_plugged | disk_min_free_gb | ram_high | cpu_high | temp_high | backup_days | cooldown"},
                "value":  {"type": "NUMBER", "description": "New numeric value for 'set'"}
            },
            "required": []
        }
    },
    {
        "name": "read_document",
        "description": (
            "Reads any local document or web page and shows a preview: PDF, TXT, "
            "Markdown, HTML, Word (.docx), CSV, Excel, PowerPoint, or a website "
            "URL. Use for 'read this document', 'what is in the file', "
            "'show me that page'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "source": {"type": "STRING", "description": "File name, full path, or URL"}
            },
            "required": ["source"]
        }
    },
    {
        "name": "document_qa",
        "description": (
            "Answers questions about the content of ANY document or web page: "
            "PDF, Word, TXT, Markdown, HTML, Excel, PowerPoint or a website URL. "
            "Finds the relevant parts and answers from them. Use for "
            "'summarize this document', 'what does the file say about X', "
            "'what is on this website about Y'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "source":   {"type": "STRING", "description": "File name, full path, or URL"},
                "question": {"type": "STRING", "description": "Question about the content"}
            },
            "required": ["source", "question"]
        }
    },
    {
        "name": "search_documents",
        "description": (
            "Searches local documents in Documents, Downloads, and Desktop, or "
            "in one folder the user specifies. Supports PDF, Word, PowerPoint, "
            "Excel, CSV, text, Markdown, HTML, JSON, XML, and log files. "
            "Search is local and bounded; only matching excerpts are returned "
            "to Gemini to answer the user's query. Tell the user that matching "
            "excerpts are shared with Gemini. Never search outside the requested "
            "folders or the default personal folders."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Terms or question to search for in documents"},
                "folder": {"type": "STRING", "description": "Optional: Documents | Downloads | Desktop | all | or a specific folder path"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "email_watch",
        "description": (
            "Turns on or off an automatic watcher that alerts the user as soon "
            "as new mail arrives in Gmail (speaks + notifies + phone push). "
            "Actions: enable | disable | status. Requires Gmail already "
            "configured. Use for 'alert me when I get new email', 'tell me when "
            "a new mail arrives', 'stop email alerts'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "enable | disable | status (default: status)"}
            },
            "required": []
        }
    },
    {
        "name": "translate",
        "description": (
            "Translates any text into another language. Use for 'translate this "
            "into Russian', 'how do I say X in English', 'translate Y to Uzbek'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "text":  {"type": "STRING", "description": "Text to translate"},
                "to":    {"type": "STRING", "description": "Target language, e.g. English, Russian, Uzbek (default English)"},
                "from":  {"type": "STRING", "description": "Optional source language (auto-detected if omitted)"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "set_live_translation",
        "description": (
            "Enables, disables, or checks continuous spoken interpretation for "
            "the live microphone conversation. When enabled, NIANG IA translates "
            "each utterance into the selected target language instead of answering "
            "it. Actions: enable, disable, status. Source language is optional "
            "and defaults to automatic detection."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "enable | disable | status"},
                "from": {"type": "STRING", "description": "Optional source language; omitted means auto-detect"},
                "to": {"type": "STRING", "description": "Target language, required when enabling"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "proactive_suggestions",
        "description": (
            "Manages opt-in personalized suggestions based on repeated tool use. "
            "Actions: enable, disable, status, suggest. When enabled, NIANG IA "
            "stores only allow-listed tool names and dates locally for up to 30 "
            "days, never tool arguments or conversation content. Suggestions "
            "appear in the daily briefing and require repeated use on at least "
            "three different days."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "enable | disable | status | suggest"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "whatsapp_call",
        "description": (
            "Manual-assist WhatsApp calling only. It never searches contacts, "
            "dials, or hangs up. The user must select and verify the exact "
            "WhatsApp contact/number, personally connect the call, and tell the "
            "other person NIANG IA is an AI. Actions: prepare, devices, status, "
            "connect, mute, resume, stop. 'connect' streams live call audio and "
            "selected display names to Gemini and requires explicit confirmation. "
            "NIANG IA does not retain local call transcripts or recordings; "
            "provider policies apply. A successful Gemini connection does not verify "
            "the WhatsApp call state."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "prepare | devices | status | connect | mute | resume | stop"},
                "contact_name": {"type": "STRING", "description": "Exact WhatsApp contact name manually verified by the user; required for connect"},
                "contact_confirmed": {"type": "BOOLEAN", "description": "True only after the user selected the exact contact/number, the call is connected, and the person was told NIANG IA is an AI"},
                "owner_name": {"type": "STRING", "description": "Optional authorized user's name for NIANG IA's introduction"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "media_control",
        "description": (
            "Controls whatever music or video is playing (Spotify, YouTube, "
            "VLC, media players): play/pause, next, previous, volume up/down, "
            "mute. Works with global media keys. Use for 'play music', 'pause', "
            "'next song', 'volume down', 'switch the track'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | pause | toggle | next | prev | volume_up | volume_down | mute (default: toggle)"}
            },
            "required": []
        }
    },
    {
        "name": "api_add_key",
        "description": (
            "Adds a NEW Gemini API key to the rotation pool. Use when the "
            "current key(s) hit their daily quota (the AI says the limit is "
            "exhausted). The user pastes a new key starting with 'AIza...'. "
            "Old keys are kept and reused automatically after their quota "
            "resets. Use for 'yangi api key qoshish', 'add api key AIza...', "
            "'key qo'sh'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "key": {"type": "STRING", "description": "The new Gemini API key, starts with AIza"}
            },
            "required": ["key"]
        }
    },
    {
        "name": "google_auth",
        "description": (
            "Starts Google authorization (Device Flow). Returns a code + URL "
            "that the user must open on their phone (google.com/device) and "
            "enter. Then authorization completes in the background. Use when "
            "Google Calendar/Drive/Gmail API need connecting, or when the AI "
            "says Google is not authorized."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "google_auth_status",
        "description": (
            "Reports whether Google is authorized (and which Gmail account), "
            "or is still waiting for the user to enter the code."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "calendar",
        "description": (
            "Google Calendar operations: list upcoming events, add a new "
            "event, delete an event. Use for 'what's on my calendar', 'add an "
            "event tomorrow at 3pm', 'dushanba 10da uchrashuv qo'y', 'delete "
            "the dentist appointment'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | add | delete (default: list)"},
                "summary":     {"type": "STRING", "description": "Event title (for add/delete)"},
                "start":       {"type": "STRING", "description": "Start 'YYYY-MM-DD HH:MM' or 'HH:MM' (for add)"},
                "end":         {"type": "STRING", "description": "End time, same format (for add)"},
                "description": {"type": "STRING", "description": "Optional details (for add)"},
                "event_id":    {"type": "STRING", "description": "Event id (for delete)"},
                "max_results": {"type": "INTEGER", "description": "How many events to list (default 10)"}
            },
            "required": []
        }
    },
    {
        "name": "drive",
        "description": (
            "Google Drive operations: list recent files, search, read a file's "
            "text content, upload a text file. Use for 'drive'dagi fayllar', "
            "'search my drive for X', 'read this document from drive', 'upload "
            "this note to drive'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":     {"type": "STRING", "description": "list | search | read | upload (default: list)"},
                "query":      {"type": "STRING", "description": "Search query (for search)"},
                "file_id":    {"type": "STRING", "description": "File id (for read)"},
                "name":       {"type": "STRING", "description": "File name (for upload)"},
                "content":    {"type": "STRING", "description": "Text content (for upload)"},
                "max_results":{"type": "INTEGER", "description": "How many files to list (default 10)"}
            },
            "required": []
        }
    },
]

# â”€â”€ Safety: inject a `confirm` flag into every tool that may be HIGH risk â”€â”€â”€â”€
# The model can pass confirm=true only after the user explicitly approves. The
# gate in _execute_tool/_dispatch_tool enforces this centrally (see safety.py).
for _decl in TOOL_DECLARATIONS:
    _name = _decl.get("name", "")
    if _name in {
        "cmd_control", "desktop_control", "file_controller", "gmail",
        "task_manager", "code_helper", "game_updater",
        "computer_settings", "computer_control", "calendar", "drive",
        "smart_home_control", "browser_control", "send_message", "autostart",
        "whatsapp_call",
    }:
        _decl.setdefault("parameters", {}).setdefault("properties", {})[
            "confirm"
        ] = {"type": "BOOLEAN",
             "description": ("Must be TRUE only after the user explicitly "
                             "approves this action.")}
        _decl.setdefault("parameters", {}).setdefault("properties", {})[
            "confirm_token"
        ] = {"type": "STRING",
             "description": ("One-time token from a blocked response "
                             "([token: ...]). Copy it exactly when re-invoking "
                             "after user approval.")}
        _decl.setdefault("parameters", {}).setdefault("properties", {})[
            "face_verify"
        ] = {"type": "BOOLEAN",
             "description": ("Optional: require local face identity verification "
                             "before executing this confirmed action.")}


class KaizumiLive:

    def __init__(self, ui: KaizumiUI, enable_bluetooth: bool = False):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._send_lock     = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self._last_play_ts  = 0.0
        self._turn_complete = False
        self._ready         = False
        self._startup_greeting_sent = False
        self._phase         = PHASE_IDLE
        self._phase_lock    = threading.Lock()
        self._rolling_parts = []
        self._rolling_len   = 0
        self._roll_turns    = 0
        self._analysis_sources = []
        self._analysis_lock = threading.Lock()
        self._analysis_generation = 0
        self.loop_guard     = LoopGuard()
        self._tool_handlers = self._build_tool_handlers()
        self.ui.on_text_command = self._on_text_command
        self.ui.on_files_selected = self._on_files_selected
        self.ui.on_clear_documents = self._clear_analysis_sources
        self.ui.on_voiceover_requested = self._on_voiceover_requested
        self.enable_bluetooth = enable_bluetooth
        self._schedules     = []
        self._sched_lock    = threading.Lock()
        self._live_camera = LiveCamera()
        self._whatsapp_call = WhatsAppCallAssistant(
            state_callback=lambda state, detail: self.ui.set_whatsapp_call_status(
                state.value, detail,
            ),
            model=LIVE_MODEL,
        )
        self.ui.on_whatsapp_call_control = self._whatsapp_call_control

        self.telegram_token = None
        self.telegram_chat  = None
        try:
            _tg_cfg = json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
            self.telegram_token = (_tg_cfg.get("telegram_bot_token") or "").strip() or None
            self.telegram_chat  = _tg_cfg.get("telegram_chat_id")
        except Exception:
            pass
        # Environment overrides (docker / dev / CI friendly).
        if os.environ.get("KAIZUMI_TELEGRAM_TOKEN"):
            self.telegram_token = os.environ["KAIZUMI_TELEGRAM_TOKEN"].strip() or None
        if os.environ.get("KAIZUMI_TELEGRAM_CHAT_ID"):
            try:
                self.telegram_chat = int(os.environ["KAIZUMI_TELEGRAM_CHAT_ID"])
            except (TypeError, ValueError):
                self.telegram_chat = os.environ["KAIZUMI_TELEGRAM_CHAT_ID"]

        try:
            wake_service.configure(on_detect=self._on_wake_detect)
        except Exception:
            pass

    def _on_wake_detect(self):
        """Excited when the wake word is heard â€” un-mute and listen (barge-in)."""
        try:
            if not self._ready or not self.session:
                print("[WakeWord] âš ï¸ Ignored â€” session not ready.")
                return
            if getattr(self, "_bt_bridge", None) is not None and self._bt_bridge.connected_count() > 0:
                print("[WakeWord] ðŸš« Ignored â€” phone remote active via Bluetooth.")
                return
            self.ui.muted = False
            self.set_speaking(False)
            self.ui.write_log("SYS: Wake word heard â€” listening.")
        except Exception as e:
            print(f"[WakeWord] âš ï¸ {e}")

    def attach_tray(self):
        """Background tray icon + global hotkeys (optional deps)."""
        try:
            from actions import system_tray

            def _on_ui(cb):
                return lambda: self.ui.root.after(0, cb)

            def _wake_active():
                from actions.wake_word import _pick_engine
                return _pick_engine()[1]._running

            def _toggle_wake():
                try:
                    from actions.wake_word import _pick_engine
                    from actions.kaizumi_wake import _matcher as kw_matcher
                    name, eng = _pick_engine()
                    if not eng.available:
                        print("[Tray] âš ï¸ Wake word engine not ready:", name)
                        return
                    if eng._running:
                        r = eng.stop()
                    else:
                        eng.configure(on_detect=self._on_wake_detect)
                        r = eng.start()
                    print(f"[Tray] {r}")
                    self.ui.write_log(f"SYS: {r}")
                except Exception as e:
                    print(f"[Tray] âš ï¸ {e}")

            def _hide_show():
                state = self.ui.root.state()
                if state in ("normal", "iconic"):
                    self.ui.root.withdraw()
                else:
                    self.ui.root.deiconify()
                    self.ui.root.lift()

            def _brief():
                if self._loop and self.session:
                    self.speak("Give me today's morning briefing.")
                print("[Tray] Briefing requested")

            def _quit():
                try:
                    self.ui.root.after(0, self.ui.root.destroy)
                except Exception:
                    os._exit(0)

            callbacks = {
                "toggle_mute": _on_ui(self.ui._toggle_mute),
                "toggle_wake": _toggle_wake,
                "hide_show":   _hide_show,
                "briefing":    _brief,
                "quit":        _quit,
            }

            def menu_factory():
                import pystray
                return pystray.Menu(
                    pystray.MenuItem(
                        lambda item: "ðŸ”‡ Unmute" if self.ui.muted else "ðŸ”Š Mute (F4)",
                        _on_ui(self.ui._toggle_mute),
                    ),
                    pystray.MenuItem(
                        lambda item: "ðŸ˜´ Stop Wake Word" if _wake_active() else "ðŸ’¤ Activate Wake Word",
                        _toggle_wake,
                    ),
                    pystray.MenuItem("ðŸ“‹ Daily Briefing", _brief),
                    pystray.MenuItem("ðŸ‘ Hide/Show Window", _hide_show),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("ðŸšª Quit NIANG IA", _quit, default=True),
                )

            tray_ok   = system_tray.configure_icon(menu_factory)
            hot_ok    = system_tray.register_hotkeys(callbacks)
            print(f"[Tray] ðŸ–¥ Tray: {'on' if tray_ok else 'off'} | Hotkeys: {hot_ok} registered ({system_tray.available()})")
        except Exception as e:
            print(f"[Tray] âš ï¸ Could not attach tray: {e}")
            import traceback; traceback.print_exc()

    def _clear_analysis_sources(self):
        with self._analysis_lock:
            self._analysis_sources = []
            self._analysis_generation += 1

    @staticmethod
    def _is_document_question(text: str) -> bool:
        import re

        terms = (
            "document", "fichier", "texte import", "ces fichiers", "cette page",
            "ce site", "from the document", "this file", "these files", "this page",
            "compare", "résume", "resume", "explique", "traduis", "analyse",
            "auteur", "montant", "tableau", "summarize", "explain", "amount",
            "author",
        )
        lowered = text.casefold()
        if any(term in lowered for term in terms):
            return True
        return bool(re.search(
            r"\b(qui|quoi|quand|où|quel|quelle|quels|quelles|pourquoi|comment|"
            r"combien|what|when|where|who|why|how|which)\b",
            lowered,
        ))

    def _on_files_selected(self, paths):
        from actions.intelligent_analysis import analyze_sources, extract_source

        with self._analysis_lock:
            self._analysis_generation += 1
            generation = self._analysis_generation

        def is_current():
            with self._analysis_lock:
                return generation == self._analysis_generation

        def worker():
            self.ui.set_state("PROCESSING")
            sources = []
            failures = []
            for index, path in enumerate(paths, 1):
                if not is_current():
                    return
                self.ui.set_file_status(
                    f"Extraction {index}/{len(paths)} · contenu transmis à Gemini pour analyse…"
                )
                try:
                    source = extract_source(
                        path,
                        progress=lambda message: self.ui.set_file_status(message),
                    )
                    sources.append(source)
                except Exception as exc:
                    failures.append(f"{Path(path).name} : {exc}")
                    self.ui.write_log(f"ERR: Analyse impossible — {Path(path).name} : {exc}")

            if sources:
                with self._analysis_lock:
                    if generation != self._analysis_generation:
                        return
                    self._analysis_sources = sources
                self.ui.set_file_status("Analyse IA en cours — contenu envoyé à Google Gemini…")
                try:
                    answer = analyze_sources(sources)
                    if not is_current():
                        return
                    report_sources = ", ".join(source["name"] for source in sources)
                    self.ui.set_analysis_report(
                        f"NIANG IA — Rapport d'analyse\nSources : {report_sources}\n\n{answer}"
                    )
                    self.ui.write_log("NIANG IA: " + answer)
                    status = f"Analyse terminée · {len(sources)} source(s)"
                    if failures:
                        status += f" · {len(failures)} échec(s)"
                    self.ui.set_file_status(
                        status + " · Ctrl+Maj+V voix off · clic ici pour relancer."
                    )
                except Exception as exc:
                    if not is_current():
                        return
                    self.ui.write_log(f"ERR: Analyse Gemini impossible : {exc}")
                    self.ui.set_file_status(
                        f"Échec Gemini : {exc} · cliquez ici pour réessayer.",
                        error=True,
                    )
            elif failures and is_current():
                self.ui.set_file_status(
                    "Aucun fichier analysé · cliquez ici pour réessayer.", error=True,
                )

            if failures and is_current():
                self.ui.write_log("ERR: " + " | ".join(failures))
            if is_current():
                self.ui.set_state(
                    "MUTED" if self.ui.muted else
                    ("LISTENING" if self.ui.connected else "ONLINE")
                )

        threading.Thread(target=worker, daemon=True).start()

    def _answer_document_question(self, question: str, url=""):
        from actions.intelligent_analysis import analyze_sources, extract_source

        urls = [url] if isinstance(url, str) and url else list(url or [])
        if len(urls) > 5:
            self.ui.write_log("ERR: Limite de cinq pages par demande de comparaison.")
            return

        def worker():
            self.ui.set_state("PROCESSING")
            try:
                if urls:
                    self.ui.set_analysis_report("")
                    sources = []
                    for page_url in urls:
                        self.ui.write_log(
                            f"SYS: Récupération de {page_url} ; le texte accessible sera envoyé à Google Gemini."
                        )
                        sources.append(extract_source(page_url))
                else:
                    with self._analysis_lock:
                        sources = list(self._analysis_sources)
                if not sources:
                    raise ValueError("Aucun document n'est chargé. Importez un fichier avec Ctrl+O.")
                answer = analyze_sources(sources, question)
                report_sources = ", ".join(source["name"] for source in sources)
                self.ui.set_analysis_report(
                    f"NIANG IA — Rapport d'analyse\nSources : {report_sources}\n\n{answer}"
                )
                self.ui.write_log("NIANG IA: " + answer)
            except Exception as exc:
                self.ui.write_log(f"ERR: Analyse de la source impossible : {exc}")
            finally:
                self.ui.set_state(
                    "MUTED" if self.ui.muted else
                    ("LISTENING" if self.ui.connected else "ONLINE")
                )

        threading.Thread(target=worker, daemon=True).start()

    def _on_voiceover_requested(self, text, settings, progress, done):
        from actions.intelligent_analysis import (
            MAX_ANALYSIS_CHARS,
            analyze_sources,
            generate_voiceover,
        )

        def worker():
            try:
                narration = text.strip()
                if not narration:
                    with self._analysis_lock:
                        sources = list(self._analysis_sources)
                    if not sources:
                        raise ValueError("Saisissez un texte ou importez un document.")
                    progress("Préparation d'un script de narration à partir des documents…")
                    script = analyze_sources(
                        sources,
                        "Rédige un script de voix off clair et naturel, fidèle aux documents, "
                        "en gardant leurs informations principales. Ne lis pas de métadonnées.",
                    )
                    narration = script.split("\n\nLimite d'analyse:", 1)[0].strip()
                    if sum(len(source["text"]) for source in sources) > MAX_ANALYSIS_CHARS:
                        progress("Script basé sur les premiers 100 000 caractères analysés.")
                path = generate_voiceover(
                    narration,
                    voice=settings["voice"],
                    language=settings["language"],
                    pace=settings["pace"],
                    tone=settings["tone"],
                    progress=progress,
                )
                done(str(path), None)
            except Exception as exc:
                done(None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_text_command(self, text: str):
        import re

        urls = re.findall(r"https?://[^\s]+", text, flags=re.IGNORECASE)
        if urls:
            self._answer_document_question(
                text, [url.rstrip(".,;:!?)]}") for url in urls]
            )
            return
        with self._analysis_lock:
            has_sources = bool(self._analysis_sources)
        if has_sources and self._is_document_question(text):
            self._answer_document_question(text)
            return
        if not self._loop or not self.session or not self._send_lock:
            return
        async def _send():
            async with self._send_lock:
                await self.session.send_realtime_input(text=text)
        asyncio.run_coroutine_threadsafe(_send(), self._loop)

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        self._set_phase(PHASE_SPEAKING if value else PHASE_LISTENING)

    def _persona_info(self) -> tuple[str, str, str]:
        """Return (mode, mood, voice) for the UI header badges."""
        try:
            memory       = load_memory()
            mode, mood   = _get_style_from_memory(memory)
            voice        = _get_voice_from_memory(memory)
            return (mode, mood, voice)
        except Exception:
            return ("normal", "calm", "Aoede")

    def _set_phase(self, phase: str):
        with self._phase_lock:
            self._phase = phase
        if phase == PHASE_THINKING:
            self.ui.set_state("THINKING")
        elif phase == PHASE_SPEAKING:
            self.ui.set_state("SPEAKING")
        elif phase == PHASE_LISTENING:
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
        else:
            self.ui.set_state("ONLINE")
        bt = getattr(self, "_bt_bridge", None)
        bt_active = bt is not None and bt.connected_count() > 0
        if bt_active:
            state = {
                PHASE_THINKING:  "THINKING",
                PHASE_SPEAKING:  "SPEAKING",
                PHASE_LISTENING: "MUTED" if self.ui.muted else "LISTENING",
            }.get(phase, "ONLINE")
            self.broadcast_remote({"type": "phase", "state": state})

    def broadcast_remote(self, payload: dict):
        """Send a JSON event to every connected Bluetooth phone (async-safe)."""
        bt = getattr(self, "_bt_bridge", None)
        if bt is None or not self._loop:
            return
        try:
            asyncio.run_coroutine_threadsafe(
                bt.broadcast(payload), self._loop
            )
        except Exception:
            pass

    def _safely_send(self, client, payload: dict):
        """Send one JSON event to one Bluetooth phone (async-safe)."""
        if not self._loop:
            return
        client.send_json_sync(payload)

    def _current_phase(self) -> str:
        with self._phase_lock:
            return self._phase

    def _schedule_session_reload(self):
        """Mode/voice changed â€” close the live session shortly so run() reconnects
        and re-applies the system prompt / speech config from memory."""
        if not self._loop or not self.session:
            return

        async def _reload_soon():
            await asyncio.sleep(2.5)
            try:
                await self.session.close()
            except Exception:
                pass

        try:
            asyncio.run_coroutine_threadsafe(_reload_soon(), self._loop)
        except Exception:
            pass

    def _update_rolling(self, user_text: str, kaizumi_text: str):
        if not user_text and not kaizumi_text:
            return
        part = f"User: {user_text}\nNIANG IA: {kaizumi_text}\n"
        self._rolling_parts.append(part)
        self._rolling_len += len(part)
        with self._phase_lock:
            self._roll_turns += 1
        while self._rolling_len > MAX_ROLLING_CHARS and self._rolling_parts:
            old = self._rolling_parts.pop(0)
            self._rolling_len -= len(old)

    def _rolling_digest(self, limit: int = 1400) -> str:
        """Flatten the recent-context buffer into the prompt-able string."""
        joined = "".join(self._rolling_parts)[-MAX_ROLLING_CHARS:]
        if len(joined) > limit:
            joined = joined[-limit:]
            cut = joined.find("\n")
            if cut > 0:
                joined = joined[cut:]
        return joined.strip()

    def _persist_rolling_summary(self):
        """Save a compact summary of recent turns into long-term memory so a
        restart doesn't wipe the conversation context entirely."""
        try:
            with self._phase_lock:
                self._roll_turns = 0
            recent = self._rolling_digest(limit=2000)
            if not recent:
                return
            from datetime import datetime
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            update_memory({
                "notes": {
                    f"conversation_{stamp.replace(' ', '_').replace(':', '-')}": {
                        "value": recent[:400]
                    }
                }
            })
            print("[Memory] ðŸ§  Rolling summary persisted")
        except Exception as e:
            print(f"[Memory] âš ï¸ Could not persist summary: {e}")

    def speak(self, text: str):
        if not self._loop or not self.session or not self._send_lock:
            return
        async def _send():
            async with self._send_lock:
                await self.session.send_realtime_input(text=text)
        asyncio.run_coroutine_threadsafe(_send(), self._loop)

    def _log_tool_error(self, tool_name: str, tr: ToolResult):
        short = str(tr.content)[:120]
        self.ui.write_log(f"ERR: {tool_name} â€” {short}")
        if tr.error_kind == "fatal":
            self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_tool_handlers(self):
        """name -> (handler(args)->str, timeout_seconds)."""
        ui    = self.ui
        speak = self.speak

        def _agent_task(args):
            from agent.task_queue import get_queue, TaskPriority
            priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
            priority = priority_map.get(str(args.get("priority", "normal")).lower(), TaskPriority.NORMAL)
            task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=speak)
            return f"Task started (ID: {task_id})."

        def _recall(args):
            from memory.memory_manager import search_memory
            return search_memory(args.get("query", ""), args.get("category", ""))

        def _forget(args):
            from memory.memory_manager import forget_memory
            return forget_memory(args.get("key", ""), args.get("category", "notes"))

        def _clear_mem(args):
            from memory.memory_manager import clear_memory
            return clear_memory(args.get("category", ""))

        def _wake(args):
            from actions.wake_word import wake_word as wake_word_action
            return wake_word_action(parameters=args, player=ui)

        def _save_memory(args):
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] ðŸ’¾ save_memory: {category}/{key} = {value}")
            return "ok"

        def _set_mode(args):
            mode = _normalize_mode(args.get("mode", ""))
            if not mode:
                return ("Invalid mode. Use: normal, girlfriend, crazy_friend, "
                        "butler, friend, casual.")
            update_memory({"preferences": {"assistant_mode": {"value": mode}}})
            self._schedule_session_reload()
            self.ui.set_persona(*self._persona_info())
            return f"Mode set to: {mode}."

        def _set_voice(args):
            voice = _normalize_voice(args.get("voice", ""))
            if not voice:
                return ("Invalid voice. Use: " + ", ".join(VOICE_NAMES) + ".")
            update_memory({"preferences": {"assistant_voice": {"value": voice}}})
            self._schedule_session_reload()
            self.ui.set_persona(*self._persona_info())
            return f"Voice set to: {voice}."

        def _set_mood(args):
            mood = str(args.get("mood", "")).strip().lower()
            valid = {"calm", "playful", "romantic", "strict"}
            if mood not in valid:
                return f"Invalid mood '{mood}'. Use: calm, playful, romantic, strict."
            update_memory({"preferences": {"assistant_mood": {"value": mood}}})
            self.ui.set_persona(*self._persona_info())
            return f"Mood set to: {mood}."

        def _set_voice_style(args):
            style = str(args.get("style", "")).strip().lower()
            if style not in VOICE_STYLE_GUIDANCE:
                return ("Invalid voice style. Use: natural, calm, warm, "
                        "energetic, expressive, or measured.")
            update_memory({"preferences": {"assistant_voice_style": {"value": style}}})
            self._schedule_session_reload()
            return f"Voice delivery style set to: {style}."

        def _set_live_translation(args):
            updates, result = translation_mode_update(args)
            if result == "status":
                enabled, source, target = read_live_translation(load_memory())
                if not enabled:
                    return "Live translation is disabled."
                return (
                    f"Live translation is enabled: "
                    f"{source or 'auto-detect'} to {target}."
                )
            if updates is None:
                return result
            update_memory(updates)
            self._schedule_session_reload()
            return result + " Reconnecting to apply the translation mode."

        def _proactive_suggestions(args):
            return proactive_suggestions_action(parameters=args)

        def _whatsapp_call(args):
            memory = load_memory()
            return whatsapp_call_action(
                parameters=args,
                assistant=self._whatsapp_call,
                voice_name=_get_voice_from_memory(memory),
                voice_guidance=VOICE_STYLE_GUIDANCE[
                    _get_voice_style_from_memory(memory)
                ],
            )

        def _live_camera_control(args):
            action = str(args.get("action", "status")).strip().lower()
            if action == "start":
                from actions.vision_gesture import _service as vision_service
                if vision_service.is_running:
                    raise RuntimeError(
                        "Stop the other vision camera mode before starting live camera."
                    )
                self._live_camera.start()
                ui.set_live_camera_status(True)
                ui.set_vision_signal("LIVE CAMERA: frames are streamed to Gemini")
                return "Live camera is on. Webcam frames are being sent to Gemini."
            if action == "stop":
                self._live_camera.stop()
                ui.set_live_camera_status(False)
                ui.set_vision_signal("Live camera is off")
                return "Live camera is off. No more webcam frames are being sent."
            if action == "status":
                active = self._live_camera.is_active
                return f"Live camera is {'on' if active else 'off'}."
            return "Unknown live camera action. Use start, stop, or status."

        def _vision_gesture(args):
            action = str(args.get("action", "")).strip().lower()
            if self._live_camera.is_active and action not in ("status", "stop"):
                raise RuntimeError(
                    "Stop live camera before starting another camera operation."
                )
            return vision_gesture(parameters=args, player=ui, speak=speak)

        def _api_add_key(args):
            import api_keys
            key = str(args.get("key", "")).strip()
            try:
                n = api_keys.add_key(key)
            except ValueError as e:
                return f"âŒ {e}"
            return (f"âœ… Yangi API kalit qo'shildi (jami: {n}). "
                    "Limit tugagan kalitlar avtomatik aylanadi.")

        def _google_auth(args):
            import threading
            import google_oauth
            if not google_oauth.is_configured():
                return (
                    "L'accès au compte Google n'est pas encore configuré. Créez un "
                    "client OAuth de type application de bureau dans Google Cloud, "
                    "puis renseignez google_client_id et google_client_secret dans "
                    "config/api_keys.json. Ne partagez pas ces secrets dans la "
                    "conversation. Relancez ensuite la connexion Google."
                )
            if google_oauth.has_token():
                return (f"Google allaqachon ulangan"
                        + (f" ({google_oauth.email_address()})" if google_oauth.email_address() else "")
                        + ". /google_auth_status bilan ko'ring.")
            info = google_oauth.auth_start()
            if not info.get("ok"):
                return f"âŒ {info.get('error')}"
            device_code = info["device_code"]
            user_code   = info["user_code"]
            url         = info.get("verification_url", "google.com/device")

            def _poll():
                try:
                    google_oauth.auth_poll(device_code, interval=info.get("interval", 5), timeout=600)
                except Exception as e:
                    print(f"[Google] auth poll error: {e}")
            threading.Thread(target=_poll, daemon=True).start()
            return (f"ðŸ“± Avtorizatsiya kodi: *{user_code}*\n"
                    f"Telefonda oching: {url}\n"
                    "Google akkauntingizga kiring va kodni kiriting.\n"
                    "Tasdiqlagach men avtomatik saqlayman. 2-3 daqiqa kuting, "
                    "keyin 'google tekshir' deb so'rang.")

        def _google_auth_status(args):
            import google_oauth
            return google_oauth.status()

        def _office_pptx(args):
            from actions.office_builder import create_presentation as _make_pptx
            return _make_pptx(
                title=args.get("title", ""),
                slides=args.get("slides") or [],
                filename=args.get("filename"),
            )

        def _office_xlsx(args):
            from actions.office_builder import create_spreadsheet as _make_xlsx
            return _make_xlsx(
                filename=args.get("filename", "spreadsheet"),
                headers=args.get("headers") or [],
                rows=args.get("rows") or [],
                sheet_name=args.get("sheet_name", "Sheet1"),
            )

        def _office_docx(args):
            from actions.office_builder import create_document as _make_docx
            return _make_docx(
                title=args.get("title", ""),
                sections=args.get("sections") or [],
                filename=args.get("filename"),
                author=args.get("author", "NIANG IA"),
            )

        def _analyze_data(args):
            return analyze_data_action(parameters=args, response=None, player=ui)

        def _video_studio(args):
            from actions.video_studio import video_studio_action
            return video_studio_action(parameters=args)

        def _smart_home(args):
            from actions.smart_home import smart_home_control as _sh_control
            return _sh_control(
                action=args.get("action", "status"),
                device=args.get("device"),
                value=args.get("value"),
                area=args.get("area"),
            )

        def _browser_control(args):
            args = dict(args)
            fields = args.get("fields")
            if isinstance(fields, list):
                mapped_fields = {}
                for field in fields:
                    if (
                        not isinstance(field, dict)
                        or not isinstance(field.get("selector"), str)
                        or not isinstance(field.get("value"), str)
                    ):
                        raise ValueError("Browser form fields must include selector and value strings.")
                    selector = field["selector"]
                    if selector in mapped_fields:
                        raise ValueError(f"Duplicate browser form field selector: {selector}")
                    mapped_fields[selector] = field["value"]
                args["fields"] = mapped_fields
            return browser_control(parameters=args, player=ui)

        return {
            "open_app":          (lambda a: open_app(parameters=a, response=None, player=ui), 60),
            "weather_report":    (lambda a: weather_action(parameters=a, player=ui), 60),
            "browser_control":   (_browser_control, 120),
            "file_controller":   (lambda a: file_controller(parameters=a, player=ui), 60),
            "send_message":      (lambda a: send_message(parameters=a, response=None, player=ui, session_memory=None), 60),
            "reminder":          (lambda a: reminder(parameters=a, response=None, player=ui), 30),
            "youtube_video":     (lambda a: youtube_video(parameters=a, response=None, player=ui), 90),
            "screen_process":    (lambda a: screen_process(parameters=a, player=ui), 120),
            "computer_settings": (lambda a: computer_settings(parameters=a, response=None, player=ui), 120),
            "cmd_control":       (lambda a: cmd_control(parameters=a, player=ui), 120),
            "desktop_control":   (lambda a: desktop_control(parameters=a, player=ui), 60),
            "code_helper":       (lambda a: code_helper(parameters=a, player=ui, speak=speak), 180),
            "dev_agent":         (lambda a: dev_agent(parameters=a, player=ui, speak=speak), 180),
            "agent_task":        (_agent_task, 15),
            "web_search":        (lambda a: web_search_action(parameters=a, player=ui), 90),
            "computer_control":  (lambda a: computer_control(parameters=a, player=ui), 120),
            "system_status":     (lambda a: system_status(parameters=a, player=ui), 45),
            "task_manager":      (lambda a: task_manager(parameters=a, player=ui), 60),
            "clipboard":         (lambda a: clipboard_action(parameters=a, player=ui), 45),
            "vision_gesture":    (_vision_gesture, 120),
            "recall_memory":     (_recall, 20),
            "forget_memory":     (_forget, 10),
            "clear_memory":      (_clear_mem, 10),
            "game_updater":      (lambda a: game_updater(parameters=a, player=ui, speak=speak), 120),
            "flight_finder":     (lambda a: flight_finder(parameters=a, player=ui), 120),
            "notify":            (lambda a: notify(parameters=a, player=ui), 30),
            "daily_briefing":    (lambda a: daily_briefing(parameters=a, player=ui), 120),
            "wake_word":         (_wake, 45),
            "save_memory":       (_save_memory, 10),
            "set_mode":          (_set_mode, 10),
            "set_voice":         (_set_voice, 10),
            "set_mood":          (_set_mood, 10),
            "set_voice_style":   (_set_voice_style, 10),
            "set_live_translation": (_set_live_translation, 10),
            "proactive_suggestions": (_proactive_suggestions, 10),
            "whatsapp_call":      (_whatsapp_call, 30),
            "live_camera":       (_live_camera_control, 15),
            "gmail":             (lambda a: gmail_action(parameters=a, response=None, player=ui), 60),
            "read_pdf":          (lambda a: read_pdf_action(parameters=a, response=None, player=ui), 60),
            "pdf_qa":            (lambda a: pdf_qa(parameters=a, response=None, player=ui), 90),
            "autostart":         (lambda a: autostart_action(parameters=a, response=None, player=ui), 20),
            "vision_click":      (lambda a: vision_click_action(parameters=a, response=None, player=ui), 90),
            "monitor_alerts":    (lambda a: monitor_action(parameters=a, response=None, player=ui), 15),
            "pc_health":         (lambda a: guardian_action(parameters=a, response=None, player=ui), 15),
            "email_watch":       (lambda a: email_watch_action(parameters=a, response=None, player=ui), 15),
            "translate":         (lambda a: translate_action(parameters=a, response=None, player=ui), 45),
            "media_control":     (lambda a: media_control_action(parameters=a, response=None, player=ui), 20),
            "read_document":     (lambda a: read_document_action(parameters=a, response=None, player=ui), 45),
            "document_qa":       (lambda a: document_qa_action(parameters=a, response=None, player=ui), 90),
            "search_documents":  (lambda a: search_documents_action(parameters=a, response=None, player=ui), 180),
            "api_add_key":       (_api_add_key, 15),
            "google_auth":       (_google_auth, 30),
            "google_auth_status": (_google_auth_status, 15),
            "calendar":          (lambda a: calendar_action(parameters=a, response=None, player=ui), 60),
            "drive":             (lambda a: drive_action(parameters=a, response=None, player=ui), 60),
            "schedule":          (lambda a: self._schedule(a), 30),
            "create_presentation": (_office_pptx, 60),
            "create_document":     (_office_docx, 60),
            "analyze_data":        (_analyze_data, 180),
            "video_studio":        (_video_studio, 90),
            "create_spreadsheet":  (_office_xlsx, 60),
            "smart_home_control":  (_smart_home, 30),
        }

    async def _dispatch_tool(self, name: str, args: dict) -> ToolResult:
        from safety import sanitize as _sanitize
        blocked = self.loop_guard.check(name, args)
        if blocked:
            print(f"[NIANG IA] ðŸ›‘ {name} blocked by loop guard")
            return ToolResult(ok=False, content=blocked, error_kind="loop")

        # â”€â”€ Safety gate: high-risk actions need explicit user confirmation â”€â”€
        from safety import (
            needs_confirmation, describe, CONFIRM_MESSAGE,
            CONFIRM_PARAM, CONFIRM_TOKEN_PARAM, issue_confirmation_token,
        )
        confirm = bool(args.pop(CONFIRM_PARAM, False))
        confirm_token = str(args.pop(CONFIRM_TOKEN_PARAM, ""))
        face_verify = bool(args.pop("face_verify", False))
        if needs_confirmation(name, args, confirm=confirm, confirm_token=confirm_token):
            token = issue_confirmation_token(name, args) if not confirm else ""
            print(f"[NIANG IA] â›” {name} blocked â€” confirmation required")
            return ToolResult(
                ok=True,
                content=CONFIRM_MESSAGE.format(desc=describe(name, args),
                                               param=CONFIRM_PARAM)
                + (f"\n[token: {token}]" if token else ""),
                error_kind="confirmation",
            )

        if face_verify:
            identity = await run_sync_tool(
                lambda: vision_gesture({"action": "verify_identity"}, player=self.ui),
                "face_identity_verification",
                timeout=30,
            )
            if not identity.ok or not str(identity.content).lower().startswith("identity verified:"):
                return ToolResult(
                    ok=False,
                    content="Face identity verification failed. The requested action was not executed.",
                    error_kind="identity",
                )

        entry = self._tool_handlers.get(name)
        if entry is None:
            return ToolResult(ok=False, content=f"Unknown tool: {name}", error_kind="fatal")

        if name == "browser_control":
            print("[Telegram] browser_control [details omitted]")
        else:
            print(f"[Telegram] ðŸ”§ {name} {_sanitize(name, args)}")
        fn, timeout = entry
        result = await run_sync_tool(lambda: fn(args), name, timeout=timeout)
        if result.ok:
            _record_proactive_usage(name)
        return result

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        mode, mood = _get_style_from_memory(memory)
        voice      = _get_voice_from_memory(memory)
        voice_style = _get_voice_style_from_memory(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y â€” %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        style_ctx = (
            "[ASSISTANT MODE & MOOD]\n"
            f"Mode: {mode}\n"
            f"Mood: {mood}\n"
            f"Voice: {voice}\n"
            f"Voice delivery: {VOICE_STYLE_GUIDANCE[voice_style]}\n"
            "Apply this delivery without changing the selected voice.\n"
            "Follow the mode/mood rules from the system prompt.\n\n"
        )

        parts = [time_ctx]
        translation_ctx = translation_instruction(memory)
        if translation_ctx:
            parts.append(translation_ctx)
        recent_ctx = self._rolling_digest(limit=1400)
        if recent_ctx:
            parts.append(
                "[RECENT CONVERSATION â€” use it to stay consistent, but focus on what the user just said]\n"
                + recent_ctx + "\n"
            )
        if mem_str:
            parts.append(mem_str)
        parts.append(style_ctx)
        parts.append(
            "[WINDOWS COMPUTER-USE PROTOCOL]\n"
            "For a multi-step desktop task, observe the current screen/window first, "
            "identify controls through UI Automation when available, and act on one "
            "confirmed step at a time. Use only coordinates from a fresh screen "
            "observation. After each meaningful action, wait for a visual change or "
            "verify an accessible label; execution alone does not prove success. "
            "Never claim a click, keystroke, save, or export succeeded without "
            "observable verification. Do not invent confirmation tokens. A "
            "computer_control screen description/search sends the captured image "
            "to Gemini and requires explicit confirmation. Use stop or the enabled "
            "Ctrl+Alt+Pause emergency shortcut immediately when asked to stop.\n\n"
        )
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            realtime_input_config=types.RealtimeInputConfig(
            activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
        ),
        session_resumption=types.SessionResumptionConfig(),
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow()
            ),
            thinking_config=types.ThinkingConfig(
                thinking_level=THINKING_LEVEL
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        from safety import sanitize as _sanitize
        log_tool(name, _sanitize(name, args))
        if name == "browser_control":
            print("[NIANG IA] browser_control [details omitted]")
        else:
            print(f"[NIANG IA] ðŸ”§ {name}  {_sanitize(name, args)}")
        self.ui.set_state("THINKING")

        # â”€â”€ save_memory: sessiz, hÄ±zlÄ±, Gemini'ye bildirim yok â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] ðŸ’¾ save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        # â”€â”€ set_mode / set_mood / set_voice: persist style across sessions â”€â”€
        if name == "set_mode":
            mode = _normalize_mode(args.get("mode", ""))
            if not mode:
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={"result": ("Invalid mode. Use: normal, girlfriend, "
                                         "crazy_friend, butler, friend, casual.")}
                )
            update_memory({"preferences": {"assistant_mode": {"value": mode}}})
            self._schedule_session_reload()
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": f"Mode set to: {mode}."}
            )

        if name == "set_voice":
            voice = _normalize_voice(args.get("voice", ""))
            if not voice:
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={"result": ("Invalid voice. Use: "
                                          + ", ".join(VOICE_NAMES) + ".")}
                )
            update_memory({"preferences": {"assistant_voice": {"value": voice}}})
            self._schedule_session_reload()
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": f"Voice set to: {voice}."}
            )

        if name == "set_mood":
            mood = str(args.get("mood", "")).strip().lower()
            valid = {"calm", "playful", "romantic", "strict"}
            if mood not in valid:
                return types.FunctionResponse(
                    id=fc.id, name=name,
                    response={"result": f"Invalid mood '{mood}'. Use: calm, playful, romantic, strict."}
                )
            update_memory({"preferences": {"assistant_mood": {"value": mood}}})
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": f"Mood set to: {mood}."}
            )

        result = "Done."

        # â”€â”€ Loop guard: stop identical-arg / ping-pong tool loops in live mode â”€â”€
        blocked = self.loop_guard.check(name, args)
        if blocked:
            print(f"[NIANG IA] ðŸ›‘ {name} blocked by loop guard")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": blocked}
            )

        # â”€â”€ Safety gate: high-risk actions need explicit user confirmation â”€â”€
        from safety import (
            needs_confirmation, describe, CONFIRM_MESSAGE,
            CONFIRM_PARAM, CONFIRM_TOKEN_PARAM, issue_confirmation_token, sanitize,
        )
        confirm = bool(args.pop(CONFIRM_PARAM, False))
        confirm_token = str(args.pop(CONFIRM_TOKEN_PARAM, ""))
        if needs_confirmation(name, args, confirm=confirm, confirm_token=confirm_token):
            token = issue_confirmation_token(name, args) if not confirm else ""
            print(f"[NIANG IA] â›” {name} blocked â€” confirmation required")
            log_tool(name, sanitize(name, args), error="confirmation required")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": CONFIRM_MESSAGE.format(
                    desc=describe(name, args), param=CONFIRM_PARAM)
                    + (f"\n[token: {token}]" if token else "")}
            )

        self.broadcast_remote({"type": "tool", "name": name, "status": "start",
                               "summary": " ".join(
                                   str(v) for v in sanitize(name, args).values()
                               )[:120]})
        try:
            # Uniform dispatch through the shared handler table so every
            # declared tool gets a timeout and works in both voice and
            # Telegram paths.
            entry = self._tool_handlers.get(name)
            if entry is not None:
                handler, timeout = entry
                from agent.resilience import run_sync_tool
                r = await run_sync_tool(lambda: handler(args), name, timeout=timeout)
                result = r.content or f"{name} done."
                if r.ok:
                    _record_proactive_usage(name)
            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            private_ui_tool = name in {
                "computer_control", "computer_settings", "screen_process",
            }
            if private_ui_tool:
                print("[NIANG IA] Computer-use action raised an error [details redacted]")
            else:
                traceback.print_exc()
            if name == "whatsapp_call":
                log_tool(name, sanitize(name, args), error="call action failed")
            elif private_ui_tool:
                log_tool(name, sanitize(name, args), error="computer-use action failed")
            else:
                log_tool(name, args, error=e)
            if name == "whatsapp_call":
                self.ui.write_log("ERR: WhatsApp call audio action failed.")
            elif private_ui_tool:
                self.ui.write_log("ERR: Computer-use action failed.")
            else:
                self.ui.write_log(f"ERR: {name} â€” {str(e)[:120]}")
            try:
                if private_ui_tool:
                    self.speak("The computer-use action failed.")
                else:
                    self.speak(f"Sir, {name} hit an error. {str(e)[:80]}")
            except Exception:
                pass
            self.broadcast_remote({
                "type": "tool",
                "name": name,
                "status": "error",
                "summary": (
                    "WhatsApp call audio action failed."
                    if name == "whatsapp_call"
                    else "Computer-use action failed."
                    if private_ui_tool
                    else str(e)[:120]
                ),
            })

        self.broadcast_remote({
            "type": "tool",
            "name": name,
            "status": "done",
            "summary": (
                "WhatsApp call audio action completed."
                if name == "whatsapp_call"
                else "Computer-use action completed; result details are private."
                if name in {"computer_control", "computer_settings", "screen_process"}
                else str(result)[:120]
            ),
        })

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        if name in {
            "whatsapp_call", "computer_control", "computer_settings", "screen_process",
        }:
            log_tool(
                name,
                sanitize(name, args),
                result=(
                    "[call action result redacted]"
                    if name == "whatsapp_call" else "[computer-use result redacted]"
                ),
            )
        else:
            log_tool(name, args, result=result)
        if name == "browser_control":
            print(f"[NIANG IA] browser_control completed")
        elif name == "whatsapp_call":
            print("[NIANG IA] WhatsApp call audio action completed [details redacted]")
        elif name in {"computer_control", "computer_settings", "screen_process"}:
            print(f"[NIANG IA] {name} completed [details redacted]")
        else:
            print(f"[NIANG IA] ðŸ“¤ {name} â†’ {str(result)[:80]}")

        # â”€â”€ Result: tek cÃ¼mle sÃ¶yle, dur â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    def _whatsapp_call_control(self, action: str) -> None:
        if action == "mute":
            result = self._whatsapp_call.mute()
        elif action == "stop":
            result = self._whatsapp_call.stop()
        else:
            return
        self.ui.write_log(f"SYS: {result}")

    def _schedule(self, args: dict) -> str:
        """In-app timed actions: when they fire, NIANG IA speaks + notifies the
        phone instead of relying on Windows Task Scheduler."""
        action = str(args.get("action", "list")).lower().strip()
        now = time.time()

        with self._sched_lock:
            if action in ("set", "add", "create"):
                try:
                    seconds = max(10, int(args.get("seconds", 60)))
                except (TypeError, ValueError):
                    return "I need `seconds` as a number."
                message = str(args.get("message", "Reminder")).strip() or "Reminder"
                sid = len(self._schedules) + 1
                if any(s.get("id") == sid and not s.get("fired") for s in self._schedules):
                    sid = max((s.get("id", 0) for s in self._schedules), default=0) + 1
                self._schedules.append({
                    "id": sid, "fire_at": now + seconds,
                    "message": message, "fired": False,
                })
                when = self._fmt_time(now + seconds)
                return (f"Scheduled: '{message}' in {seconds}s (ID {sid}, fires at {when}). "
                        "I will speak up and notify your phone.")

            if action in ("cancel", "delete", "remove"):
                try:
                    sid = int(args.get("id", 0))
                except (TypeError, ValueError):
                    return "I need `id` as a number."
                for s in self._schedules:
                    if s.get("id") == sid:
                        self._schedules.remove(s)
                        return f"Cancelled schedule ID {sid}."
                return f"No scheduled action with ID {sid}, sir."

            # list / status
            pending = [s for s in self._schedules if not s.get("fired")]
            if not pending:
                return "No active scheduled actions, sir."
            lines = [f"ID {s['id']} â†’ '{s['message']}' at {self._fmt_time(s['fire_at'])}"
                     for s in pending[:8]]
            return "Active schedules: " + "; ".join(lines)

    @staticmethod
    def _fmt_time(ts: float) -> str:
        try:
            return time.strftime("%I:%M %p", time.localtime(ts))
        except Exception:
            return "?"

    async def _scheduler_loop(self):
        """Fire due scheduled actions â€” speak + notify phone, once each."""
        try:
            from actions.notifications import notify
        except Exception:
            notify = None
        while True:
            try:
                due = []
                with self._sched_lock:
                    for s in self._schedules:
                        if not s.get("fired") and time.time() >= s.get("fire_at", 0):
                            due.append(s)
                            s["fired"] = True
                for s in due:
                    msg = f"â° Reminder: {s['message']}"
                    print(f"[Scheduler] ðŸ”” {msg}")
                    if self.session:
                        self.speak(msg)
                    self.ui.write_log(msg)
                    self.broadcast_remote({"type": "system", "text": msg})
                    if notify:
                        try:
                            await asyncio.to_thread(
                                notify,
                                {"title": "NIANG IA", "message": s["message"]},
                                self.ui)
                        except Exception:
                            pass
            except Exception as e:
                print(f"[Scheduler] âš ï¸ {e}")
            await asyncio.sleep(5)

    async def _monitor_loop(self, interval: float = 30.0):
        """Background watchdog: speak + push any newly-triggered alert."""
        while True:
            try:
                alerts = await asyncio.to_thread(check_monitor_rules)
                for text in alerts:
                    print(f"[Monitor] ðŸ”” {text}")
                    self.ui.write_log(text)
                    self.broadcast_remote({"type": "system", "text": text})
                    if self.session:
                        self.speak(text)
            except Exception as e:
                print(f"[Monitor] âš ï¸ {e}")
            try:
                alerts = await asyncio.to_thread(check_guardian)
                for text in alerts:
                    print(f"[Guardian] ðŸ”” {text}")
                    self.ui.write_log(text)
                    self.broadcast_remote({"type": "system", "text": text})
                    from actions.notifications import notify
                    await asyncio.to_thread(
                        notify,
                        {"title": "PC Health", "message": text},
                        self.ui)
                    if self.session:
                        self.speak(text)
            except Exception as e:
                print(f"[Guardian] âš ï¸ {e}")
            try:
                for text in await asyncio.to_thread(check_email_watch):
                    print(f"[Email] ðŸ”” {text}")
                    self.ui.write_log(text)
                    self.broadcast_remote({"type": "system", "text": text})
                    from actions.notifications import notify
                    await asyncio.to_thread(
                        notify,
                        {"title": "NIANG IA", "message": text},
                        self.ui)
                    if self.session:
                        self.speak(text)
            except Exception as e:
                print(f"[Email] âš ï¸ {e}")
            await asyncio.sleep(interval)

    # â”€â”€ Telegram remote-control bot â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _telegram_context(self) -> str:
        from datetime import datetime
        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        mode, mood = _get_style_from_memory(memory)
        voice      = _get_voice_from_memory(memory)
        now        = datetime.now()
        parts = [
            "[CURRENT DATE & TIME]",
            f"Right now it is: {now.strftime('%A, %B %d, %Y â€” %I:%M %p')}",
            "",
            "[ASSISTANT MODE & MOOD]",
            f"Mode: {mode}  Mood: {mood}  Voice: {voice}",
            "",
        ]
        recent = self._rolling_digest(limit=1000)
        if recent:
            parts += ["[RECENT CONVERSATION]", recent, ""]
        tg_hist = self._tg_history_context(limit=900)
        if tg_hist:
            parts += [
                "[TELEGRAM CHAT HISTORY â€” previous exchanges with this user, "
                "use it to stay consistent]",
                tg_hist, "",
            ]
        if mem_str:
            parts.append(mem_str)
        parts.append(_load_system_prompt())
        return "\n".join(parts)

    def _tg_history_context(self, limit: int = 900) -> str:
        """Flatten the last Telegram exchanges into a prompt-able string."""
        hist = getattr(self, "_tg_history", None) or []
        if not hist:
            return ""
        lines, used = [], 0
        for role, txt in list(hist)[-8:]:
            line = f"{'User' if role == 'user' else 'NIANG IA'}: {txt}"
            if used + len(line) > limit:
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines)

    def _remember_tg_turn(self, role: str, text: str):
        if not getattr(self, "_tg_history", None):
            from collections import deque
            self._tg_history = deque(maxlen=20)
        text = (text or "").strip()[:500]
        if text:
            self._tg_history.append((role, text))

    async def _telegram_run_command(self, text: str) -> str:
        """Mini agent loop: Gemini interprets â†’ tools run â†’ text reply."""
        import api_keys
        from google.genai import types as gtypes
        config = gtypes.GenerateContentConfig(
            system_instruction=self._telegram_context(),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            temperature=0.4,
        )
        contents = [gtypes.Content(parts=[gtypes.Part(text=str(text))])]
        final = ""
        tool_results = []
        for _ in range(4):
            try:
                resp = await api_keys.aio_generate(
                    model=TG_MODEL, contents=contents,
                    config=config, api_version="v1beta")
            except Exception as e:
                msg = str(e)
                if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                    return ("âš ï¸ Barcha API kalitlari limitga yetgan "
                            "(20 so'rov/kun). Yangi kalit qo'shing yoki "
                            "bir necha soatdan keyin urinib ko'ring.")
                return f"Model error: {e}"
            if resp.text:
                final = resp.text.strip()
            calls = getattr(resp, "function_calls", None)
            if not calls:
                break
            model_parts = (list(resp.candidates[0].content.parts)
                           if resp.candidates else [])
            tool_parts = []
            for fc in calls:
                name = fc.name
                args = dict(fc.args or {})
                from safety import sanitize as _sanitize
                tr = await self._dispatch_tool(name, args)
                raw = str(tr.content) if tr.ok else f"error: {tr.content}"
                if tr.ok and not str(tr.content).strip():
                    raw = f"(tool {name} returned no data)"
                result = raw[:400]
                tool_results.append(f"{name}: {result[:120]}")
                if name == "browser_control":
                    print("[Telegram] browser_control completed [details omitted]")
                else:
                    print(f"[Telegram] ðŸ”§ {name} {_sanitize(name, args)} â†’ {str(result)[:80]}")
                tool_parts.append(gtypes.Part(
                    function_response=gtypes.FunctionResponse(
                        name=name, response={"result": result})))
            contents += [
                gtypes.Content(role="model", parts=model_parts),
                gtypes.Content(role="tool", parts=tool_parts),
            ]
        if not final:
            if tool_results:
                final = ("âš¡ Bajarildi:\nâ€¢ " +
                         "\nâ€¢ ".join(tool_results[:6]))
            else:
                final = "Done, sir."
        return final

    async def _telegram_quick_command(self, token, chat, text: str):
        """Instant slash-commands and inline-keyboard callbacks.

        Returns (handled, result, reply_markup); result is None | str | bytes(photo)."""
        import telegram_bot as tg
        low = text.lower().strip()
        if low in ("/help", "/start", "help", "start"):
            tg.send_message(token, chat, TG_HELP_TEXT,
                            reply_markup=TG_QUICK_KEYBOARD)
            return True, None, None
        if low in ("/stop",):
            return True, None, None
        if low == "/status":
            return True, await self._telegram_status(), None
        if low == "/mute":
            if not self.ui.muted:
                self.ui.muted = True
                self.ui.set_state("MUTED")
                self.ui.write_log("SYS: Telegram: microphone muted.")
                self.ui._safe_ui(self.ui._draw_mute_button)
            return True, ("ðŸ”‡ Mikrofon o'chirildi (MUTED). "
                          "Endi faqat matn/Telegram orqali gapiryapman."), None
        if low == "/unmute":
            if self.ui.muted:
                self.ui.muted = False
                self.ui.set_state("LISTENING")
                self.ui.write_log("SYS: Telegram: microphone active.")
                self.ui._safe_ui(self.ui._draw_mute_button)
            return True, "ðŸŽ¤ Mikrofon yoniq (LIVE). Gaplashavering.", None
        if low == "/screenshot":
            shot = await asyncio.to_thread(_take_screenshot_bytes)
            if shot:
                return True, shot, None
            return True, "ðŸ“¸ Screenshot olishning iloji bo'lmadi (pyautogui?).", None
        if low == "/mode" or low.startswith("/mode "):
            mode, mood = _get_style_from_memory(load_memory())
            rest = text.strip()[len("/mode"):].strip()
            if not rest:
                return True, (f"ðŸ§­ Hozirgi rejim: <b>{tg.html_escape(mode)}</b> "
                              f"(kayfiyat: {tg.html_escape(mood)})\n"
                              "Tanlang ðŸ‘‡"), TG_MODE_KEYBOARD
            new_mode = _normalize_mode(rest)
            if not new_mode:
                return True, ("âŒ Noto'g'ri rejim. Tanlang: normal, girlfriend, "
                              "crazy_friend, butler, friend, casual."), None
            update_memory({"preferences": {"assistant_mode": {"value": new_mode}}})
            self._schedule_session_reload()
            return True, f"ðŸ”„ Rejim o'zgartirildi: <b>{tg.html_escape(new_mode)}</b>.", None
        if low == "/voice" or low.startswith("/voice "):
            current = _get_voice_from_memory(load_memory())
            rest = text.strip()[len("/voice"):].strip()
            if not rest:
                desc = "\n".join(f"â€¢ <b>{v}</b> â€” {VOICES[v]}" for v in VOICE_NAMES)
                return True, (f"ðŸ—£ Hozirgi ovoz: <b>{tg.html_escape(current)}</b>\n"
                              f"{desc}\nTanlang ðŸ‘‡"), TG_VOICE_KEYBOARD
            new_voice = _normalize_voice(rest)
            if not new_voice:
                return True, ("âŒ Noto'g'ri ovoz. Tanlang: " +
                              ", ".join(VOICE_NAMES) + "."), None
            update_memory({"preferences": {"assistant_voice": {"value": new_voice}}})
            self._schedule_session_reload()
            return True, (f"ðŸŽ™ Ovoz o'zgartirildi: <b>{tg.html_escape(new_voice)}</b>. "
                          "Bir necha soniyada yangi ovoz bilan ulanyapman..."), None
        return False, None, None

    async def _telegram_status(self) -> str:
        import telegram_bot as tg
        from datetime import datetime
        phase   = self._current_phase().upper()
        mode, mood = _get_style_from_memory(load_memory())
        voice   = _get_voice_from_memory(load_memory())
        bt = getattr(self, "_bt_bridge", None)
        clients = bt.connected_count() if bt is not None else 0
        now     = datetime.now().strftime("%A, %B %d, %Y â€” %I:%M %p")
        return (
            "ðŸ“Š <b>NIANG IA statusi</b>\n"
            f"ðŸ•’ {tg.html_escape(now)}\n"
            f"ðŸŽ™ Mikrofon: <b>{'ðŸ”‡ MUTED' if self.ui.muted else 'ðŸŽ¤ LIVE'}</b>\n"
            f"ðŸ”„ Holat: <b>{tg.html_escape(phase)}</b>\n"
            f"ðŸ“± Ulangan telefonlar: {clients}\n"
            f"ðŸ§­ Rejim: <b>{tg.html_escape(mode)}</b>  |  "
            f"Kayfiyat: <b>{tg.html_escape(mood)}</b>\n"
            f"ðŸ—£ Ovoz: <b>{tg.html_escape(voice)}</b>"
        )

    async def _telegram_handle_text(self, token, chat, text: str):
        import telegram_bot as tg
        handled, result, reply_markup = await self._telegram_quick_command(token, chat, text)
        if handled:
            if isinstance(result, bytes):
                tg.send_photo(token, chat, result,
                              caption="ðŸ“¸ Hozirgi ekran, sir.")
            elif result:
                tg.send_message(token, chat, tg.html_escape(str(result)),
                                reply_markup=reply_markup)
            return
        tg.send_typing(token, chat)
        placeholder = tg.send_message(token, chat, "â³ ...") or {}
        msg_id = placeholder.get("message_id")
        answer = await self._telegram_run_command(text)
        safe   = tg.html_escape(answer)
        if msg_id:
            tg.edit_message(token, chat, msg_id, safe)
        else:
            tg.send_message(token, chat, safe)
        self._remember_tg_turn("user", text)
        self._remember_tg_turn("ai", answer)

    async def _telegram_handle_voice(self, token, chat, voice, caption: str = ""):
        import telegram_bot as tg
        file_id = (voice or {}).get("file_id")
        if not file_id:
            tg.send_message(token, chat, "That audio wasn't readable, sir.")
            return
        tg.send_typing(token, chat)
        placeholder = tg.send_message(token, chat, "ðŸŽ§ ...") or {}
        msg_id = placeholder.get("message_id")

        def _edit(text: str):
            safe = tg.html_escape(text)
            if msg_id:
                tg.edit_message(token, chat, msg_id, safe)
            else:
                tg.send_message(token, chat, safe)

        audio = await asyncio.to_thread(tg.download_file, token, file_id)
        if not audio:
            _edit("Couldn't download the voice message, sir.")
            return
        try:
            api_key = _get_api_key()
            transcript = await asyncio.to_thread(
                tg.transcribe_voice, api_key, audio)
        except Exception as e:
            _edit(f"Voice transcription failed: {tg.html_escape(str(e))}")
            return
        if not transcript:
            _edit("I couldn't hear anything, sir.")
            return
        if caption:
            transcript = caption
        _edit(f"ðŸ“ <i>Eshitildi:</i> {tg.html_escape(transcript[:300])}")
        answer = await self._telegram_run_command(transcript)
        _edit(tg.html_escape(answer))
        self._remember_tg_turn("user", transcript)
        self._remember_tg_turn("ai", answer)

    async def _telegram_loop(self):
        import telegram_bot as tg
        token = self.telegram_token
        if not token:
            return
        chat = self.telegram_chat
        if not await asyncio.to_thread(tg.ping_bot, token):
            print("[Telegram] âš ï¸ Bot token rejected â€” check config/api_keys.json.")
            return
        offset_path = BASE_DIR / "config" / "telegram_offset.txt"

        def _load_offset() -> int:
            try:
                return int(offset_path.read_text(encoding="utf-8").strip())
            except Exception:
                return 0

        def _save_offset(off: int):
            try:
                offset_path.write_text(str(off), encoding="utf-8")
            except Exception:
                pass

        print("[Telegram] ðŸ¤– Bot online â€” polling for your messages.")
        self.ui.write_log("SYS: Telegram bot online.")
        if not await asyncio.to_thread(tg.set_bot_commands, token):
            print("[Telegram] âš ï¸ Could not set bot command menu.")
        offset = _load_offset()
        while True:
            try:
                for upd in await asyncio.to_thread(tg.get_updates, token, offset, 25):
                    offset = upd.get("update_id", 0) + 1
                    _save_offset(offset)
                    cbq = upd.get("callback_query")
                    msg = upd.get("message") or {}
                    if cbq:
                        cid = (cbq.get("message") or {}).get("chat", {}).get("id")
                    else:
                        cid = msg.get("chat", {}).get("id")
                    if str(cid) != str(chat):
                        continue
                    try:
                        if cbq:
                            cb_id = cbq.get("id")
                            data  = (cbq.get("data") or "").strip()
                            if cb_id:
                                tg.answer_callback(token, cb_id)
                            if data:
                                await self._telegram_handle_text(token, chat, data)
                            continue
                        text  = (msg.get("text") or "").strip()
                        voice = msg.get("voice") or msg.get("audio")
                        cap   = (msg.get("caption") or "").strip()
                        if voice:
                            await self._telegram_handle_voice(token, chat, voice, cap)
                        elif text:
                            await self._telegram_handle_text(token, chat, text)
                    except Exception as e:
                        import traceback; traceback.print_exc()
                        tg.send_message(token, chat, tg.html_escape(f"âš ï¸ {e}"))
            except Exception as e:
                print(f"[Telegram] âš ï¸ {e}")
            await asyncio.sleep(0.5)

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            async with self._send_lock:
                await self.session.send_realtime_input(
                    audio=types.Blob(data=msg["data"], mime_type=msg["mime_type"])
                )

    async def _stream_live_camera(self):
        last_sequence = -1
        last_sent = 0.0
        try:
            while True:
                if not self._live_camera.is_active:
                    await asyncio.sleep(0.2)
                    continue
                now = time.monotonic()
                if now - last_sent >= 1.0:
                    frame = await asyncio.to_thread(self._live_camera.latest_jpeg)
                    if frame is not None and frame[0] != last_sequence:
                        async with self._send_lock:
                            await self.session.send_realtime_input(
                                video=types.Blob(data=frame[1], mime_type="image/jpeg")
                            )
                        last_sequence = frame[0]
                        last_sent = now
                await asyncio.sleep(0.1)
        finally:
            if await asyncio.to_thread(self._live_camera.stop):
                self.ui.set_live_camera_status(False)
                self.ui.set_vision_signal("Live camera stopped: Gemini session disconnected")

    async def _listen_audio(self):
        print("[NIANG IA] ðŸŽ¤ Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                assistant_speaking = self._is_speaking
            if not self.ui.muted:
                data = indata.tobytes()
                loop.call_soon_threadsafe(self._safe_put_mic, data)

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[NIANG IA] ðŸŽ¤ Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[NIANG IA] âŒ Mic: {e}")
            raise

    def _safe_put_mic(self, data):
        try:
            self.out_queue.put_nowait({"data": data, "mime_type": "audio/pcm"})
        except asyncio.QueueFull:
            pass

    async def _watch_speaking(self):
        while True:
            await asyncio.sleep(2)
            with self._speaking_lock:
                speaking = self._is_speaking
                last     = self._last_play_ts
            if speaking and last and time.monotonic() - last > 25:
                print("[NIANG IA] â± Speaking watchdog fired â€” force-cleared")
                self.set_speaking(False)

    async def _send_startup_greeting(self):
        if self._startup_greeting_sent:
            return
        if self.ui.silent_mode:
            self._startup_greeting_sent = True
            return
        await self.session.send_realtime_input(
            text=(
                "Greet the user aloud now with a brief, warm welcome. Introduce "
                "yourself as NIANG IA, say you are ready to help, and use the "
                "language and conversational style specified in your instructions. "
                "Do not wait for the user to speak or type first."
            )
        )
        self._startup_greeting_sent = True
        self.ui.write_log("SYS: NIANG IA vous salue et est prête à vous aider.")

    async def _receive_audio(self):
        print("[NIANG IA] Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():
                    if response.data and not getattr(self.ui, "silent_mode", False):
                        self.audio_in_queue.put_nowait(response.data)

                    sc = getattr(response, "server_content", None)
                    if sc is not None:
                        if getattr(sc, "interrupted", False):
                            while not self.audio_in_queue.empty():
                                try:
                                    self.audio_in_queue.get_nowait()
                                except asyncio.QueueEmpty:
                                    break
                            self._turn_complete = False
                            self.set_speaking(False)

                        output_tx = getattr(sc, "output_transcription", None)
                        if output_tx and getattr(output_tx, "text", None):
                            txt = output_tx.text.strip()
                            if txt:
                                out_buf.append(txt)

                        input_tx = getattr(sc, "input_transcription", None)
                        if input_tx and getattr(input_tx, "text", None):
                            txt = input_tx.text.strip()
                            if txt:
                                in_buf.append(txt)

                        if getattr(sc, "turn_complete", False):
                            self._turn_complete = True

                            full_in = " ".join(in_buf).strip()
                            full_out = " ".join(out_buf).strip()

                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                            if full_out:
                                self.ui.write_log(f"NIANG IA: {full_out}")

                            in_buf = []
                            out_buf = []

                            bt = getattr(self, "_bt_bridge", None)
                            if bt is not None:
                                try:
                                    if full_in:
                                        await bt.forward_transcript("user", full_in)
                                    if full_out:
                                        await bt.forward_transcript("kaizumi", full_out)
                                except Exception as e:
                                    print(f"[Bluetooth] forward: {e}")

                            self._update_rolling(full_in, full_out)

                            if full_in and len(full_in) > 5:
                                threading.Thread(
                                    target=_update_memory_async,
                                    args=(full_in, full_out),
                                    daemon=True,
                                ).start()

                            with self._phase_lock:
                                n_turns = self._roll_turns
                            if n_turns >= 10:
                                self._persist_rolling_summary()

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[NIANG IA] Tool call: {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)

                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )

        except Exception as e:
            print(f"[NIANG IA] Recv error: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[NIANG IA] ðŸ”Š Play started")
        loop = asyncio.get_event_loop()

        # SÃ¼rekli aÃ§Ä±k output stream â€” PyAudio'daki stream.write() davranÄ±ÅŸÄ±yla aynÄ±
        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()
        try:
            while True:
                chunk = await self.audio_in_queue.get()
                if getattr(self.ui, "silent_mode", False):
                    # Drain already-buffered audio as well, so switching to
                    # Text-only takes effect immediately instead of allowing
                    # the tail of the previous reply to play.
                    self.set_speaking(False)
                    continue
                if not self._is_speaking:
                    self.set_speaking(True)
                self._last_play_ts = time.monotonic()
                await asyncio.to_thread(stream.write, chunk)
                if self.audio_in_queue.empty() and self._turn_complete:
                    self._turn_complete = False
                    self.set_speaking(False)
        except Exception as e:
            print(f"[NIANG IA] âŒ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    async def run(self):
        self._loop = asyncio.get_event_loop()

        bt_bridge = None
        if self.enable_bluetooth:
            # Bluetooth phone transport (no USB/ADB). Silently off if winrt
            # isn't installed or the adapter can't do BLE peripheral.
            try:
                from remote.bluetooth_transport import start_bluetooth_bridge
                bt_bridge = await start_bluetooth_bridge(self)
            except Exception as e:
                bt_bridge = None
                log(f"Bluetooth transport OFF: {e}", level="WARN")
            self._bt_bridge = bt_bridge

        tg_task = None
        if self.telegram_token:
            tg_task = asyncio.create_task(self._telegram_loop())

        client = None
        backoff = 3
        try:
            while True:
                try:
                    if client is None:
                        try:
                            client = genai.Client(
                                api_key=_get_api_key(),
                                http_options={"api_version": "v1beta"}
                            )
                        except KeyError as ke:
                            msg = ("No Gemini API key configured. Open "
                                   "config/api_keys.json and add gemini_api_key.")
                            log(msg, level="ERROR")
                            self.ui.write_log(f"SYS: {msg}")
                            self.ui.set_state("THINKING")
                            self.ui.set_connecting(False)
                            await asyncio.sleep(5)
                            continue
                        except Exception as ke:
                            log(f"API client error: {ke}", level="ERROR")
                            await asyncio.sleep(5)
                            continue
                    print("[NIANG IA] ðŸ”Œ Connecting...")
                    self.ui.set_state("THINKING")
                    self.ui.set_connecting(True)
                    config = self._build_config()

                    async with (
                        client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                        asyncio.TaskGroup() as tg,
                    ):
                        backoff = 3  # success resets the backoff
                        self.session        = session
                        self._loop          = asyncio.get_event_loop()
                        self._send_lock     = asyncio.Lock()
                        self.audio_in_queue = asyncio.Queue()
                        self.out_queue      = asyncio.Queue(maxsize=64)
                        self._ready         = True

                        log("Gemini session CONNECTED")
                        print("[NIANG IA] âœ… Connected.")
                        self.ui.set_connection(True)
                        self.ui.set_persona(*self._persona_info())
                        self.ui.set_state("LISTENING")
                        self.ui.write_log("SYS: NIANG IA online.")

                        tg.create_task(self._send_realtime())
                        tg.create_task(self._receive_audio())
                        tg.create_task(self._play_audio())
                        tg.create_task(self._watch_speaking())
                        await self._send_startup_greeting()
                        tg.create_task(self._listen_audio())
                        tg.create_task(self._scheduler_loop())
                        tg.create_task(self._monitor_loop())
                        tg.create_task(self._stream_live_camera())

                except Exception as e:
                    log(f"Session error: {e}", level="ERROR")
                    print(f"[NIANG IA] âš ï¸ {e}")
                    traceback.print_exc()
                    # Rotate the key on quota/exhaustion so a dead key can't
                    # pin the reconnect loop forever.
                    try:
                        from api_keys import mark_exhausted
                        if client is not None and _looks_like_quota(str(e)):
                            key = getattr(getattr(client, "_api_client", None),
                                          "api_key", "")
                            if key:
                                mark_exhausted(key)
                            client = None
                    except Exception:
                        pass

                self._ready         = False
                self.session        = None
                self.out_queue      = None
                self.audio_in_queue = None
                self.set_speaking(False)
                self.ui.set_connection(False)
                self.ui.set_state("THINKING")
                log(f"Session lost â€” reconnecting in {backoff}s", level="WARN")
                print(f"[NIANG IA] ðŸ”„ Reconnecting in {backoff}s...")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
        finally:
            if tg_task:
                try:
                    tg_task.cancel()
                except Exception:
                    pass
            if bt_bridge:
                try:
                    from remote.bluetooth_transport import close_bluetooth_bridge
                    close_bluetooth_bridge()
                except Exception:
                    pass


def _tk_exception_handler(exc_type, exc_value, tb):
    """Suppress the noisy 'Exception in Tkinter callback' block when the user
    presses Ctrl+C mid-draw; real errors still print normally."""
    if isinstance(exc_value, KeyboardInterrupt):
        return
    traceback.print_exception(exc_type, exc_value, tb)


def main():
    _ensure_core_deps()
    log_file = setup_logger(BASE_DIR)
    log(f"Base dir: {BASE_DIR}\nLog file: {log_file}")
    ui = KaizumiUI("face.png")

    enable_bluetooth = "--remote" in sys.argv[1:]

    def runner():
        ui.wait_for_api_key()
        kaizumi = KaizumiLive(ui, enable_bluetooth=enable_bluetooth)
        kaizumi.attach_tray()
        try:
            asyncio.run(kaizumi.run())
        except KeyboardInterrupt:
            print("\nðŸ”´ Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.report_callback_exception = _tk_exception_handler
    try:
        ui.root.mainloop()
    except KeyboardInterrupt:
        print("\nðŸ›‘ Stopping NIANG IA (Ctrl+C)...")
        try:
            from actions.system_tray import stop as _tray_stop
            _tray_stop()
        except Exception:
            pass
        try:
            ui.root.destroy()
        except Exception:
            pass
        print("ðŸ‘‹ Shut down cleanly. See you, sir!")


if __name__ == "__main__":
    main()

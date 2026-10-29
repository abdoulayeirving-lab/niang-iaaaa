# actions/computer_control.py
# Kaizumi — Computer Control
#
# Atomic computer control functions using PyAutoGUI + keyboard + clipboard.
# Used by the agent when no existing action file covers the task.
#
# Capabilities:
#   - Type text anywhere (active window, forms, fields)
#   - Mouse click, double-click, right-click, drag
#   - Keyboard shortcuts and key combinations
#   - Scroll (up/down/left/right)
#   - Window management (minimize, maximize, close, focus)
#   - Clipboard (copy, paste, get content)
#   - Screenshot + locate element on screen
#   - Wait / smart wait for element to appear
#   - Random data generation (name, email, username, password, phone, address)
#   - Hotkey sequences
#   - Find and click image/element on screen

import json
import sys
import time
import random
import string
import subprocess
import platform
import ctypes
import math
import threading
from datetime import datetime
from pathlib import Path
from ctypes import wintypes

_PG_MOD = None
_STOP_REQUESTED = threading.Event()
_HELD_BUTTONS = set()
_EMERGENCY_HOTKEY_ID = None


def _pg():
    """Lazily import pyautogui; returns the module or None."""
    global _PG_MOD
    if _PG_MOD is None:
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            pyautogui.PAUSE    = 0.05
            _PG_MOD = pyautogui
        except ImportError:
            _PG_MOD = False
    return _PG_MOD or None

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _load_user_profile() -> dict:
    """Load user profile from long_term.json for form filling."""
    memory_path = BASE_DIR / "memory" / "long_term.json"
    try:
        if memory_path.exists():
            data = json.loads(memory_path.read_text(encoding="utf-8"))
            identity = data.get("identity", {})
            return {
                "name":  identity.get("name",  {}).get("value", ""),
                "age":   identity.get("age",   {}).get("value", ""),
                "city":  identity.get("city",  {}).get("value", ""),
                "email": identity.get("email", {}).get("value", ""),
            }
    except Exception:
        pass
    return {}


def _ensure_pyautogui():
    if _pg() is None:
        raise RuntimeError(
            "PyAutoGUI not installed. Run: pip install pyautogui"
        )


_FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Drew", "Quinn",
    "Avery", "Blake", "Cameron", "Dakota", "Emerson", "Finley", "Harper"
]
_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Wilson", "Moore", "Taylor", "Anderson", "Thomas", "Jackson"
]
_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "proton.me", "mail.com"]


def generate_random_data(data_type: str) -> str:
    """
    Generates random realistic data for form filling.

    Types: name | first_name | last_name | email | username |
           password | phone | birthday | address | zip_code
    """
    dt = data_type.lower().strip()

    if dt == "first_name":
        return random.choice(_FIRST_NAMES)

    elif dt == "last_name":
        return random.choice(_LAST_NAMES)

    elif dt == "name":
        return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"

    elif dt == "email":
        first = random.choice(_FIRST_NAMES).lower()
        last  = random.choice(_LAST_NAMES).lower()
        num   = random.randint(10, 999)
        return f"{first}.{last}{num}@{random.choice(_DOMAINS)}"

    elif dt == "username":
        first = random.choice(_FIRST_NAMES).lower()
        num   = random.randint(100, 9999)
        return f"{first}{num}"

    elif dt == "password":
        chars = string.ascii_letters + string.digits + "!@#$%"
        pwd   = (
            random.choice(string.ascii_uppercase) +
            random.choice(string.digits) +
            random.choice("!@#$%") +
            "".join(random.choices(chars, k=9))
        )
        return "".join(random.sample(pwd, len(pwd)))

    elif dt == "phone":
        return f"+1{random.randint(200,999)}{random.randint(1000000,9999999)}"

    elif dt == "birthday":
        year  = random.randint(1980, 2000)
        month = random.randint(1, 12)
        day   = random.randint(1, 28)
        return f"{month:02d}/{day:02d}/{year}"

    elif dt == "address":
        num    = random.randint(100, 9999)
        street = random.choice(["Main St", "Oak Ave", "Park Blvd", "Elm St", "Cedar Ln"])
        return f"{num} {street}"

    elif dt == "zip_code":
        return str(random.randint(10000, 99999))

    elif dt == "city":
        return random.choice(["New York", "Los Angeles", "Chicago", "Houston", "Phoenix"])

    return f"random_{data_type}_{random.randint(1000,9999)}"


def _action_result(action: str, *, executed: bool, result=None,
                   verified: bool = False, error: str = "") -> str:
    return json.dumps(
        {
            "action": action,
            "executed": executed,
            "verified": verified,
            "result": result,
            "error": error or None,
        },
        ensure_ascii=False,
    )


def _log(message: str) -> None:
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    printable = str(message).encode(encoding, errors="replace").decode(
        encoding,
        errors="replace",
    )
    print(printable)


def _screen_info() -> dict:
    _ensure_pyautogui()
    width, height = _pg().size()
    scale = 1.0
    if platform.system() == "Windows":
        try:
            scale = ctypes.windll.user32.GetDpiForSystem() / 96.0
        except (AttributeError, OSError):
            pass
    monitors = []
    try:
        import mss
        with mss.MSS() as screens:
            monitors = [
                {
                    "index": index,
                    "left": int(monitor["left"]),
                    "top": int(monitor["top"]),
                    "width": int(monitor["width"]),
                    "height": int(monitor["height"]),
                }
                for index, monitor in enumerate(screens.monitors[1:], start=1)
            ]
    except ImportError:
        monitors = [{"index": 1, "left": 0, "top": 0, "width": width, "height": height}]
    return {
        "width": width,
        "height": height,
        "scale_factor": round(scale, 2),
        "monitors": monitors,
    }


def _active_window() -> dict:
    if platform.system() != "Windows":
        raise RuntimeError("Active window details are currently supported on Windows only.")
    user32 = ctypes.windll.user32
    handle = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(handle)
    title = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(handle, title, length + 1)
    rect = wintypes.RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(rect)):
        raise OSError("Windows could not read the active window bounds.")
    return {
        "title": title.value,
        "handle": int(handle),
        "bounds": {
            "left": rect.left,
            "top": rect.top,
            "width": rect.right - rect.left,
            "height": rect.bottom - rect.top,
        },
    }


def _find_ui_elements() -> list[dict]:
    if platform.system() != "Windows":
        raise RuntimeError("Accessible UI element discovery is currently Windows-only.")
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise RuntimeError("pywinauto is required for Windows UI Automation.") from exc

    active = _active_window()
    window = Desktop(backend="uia").window(handle=active["handle"])
    elements = []
    for control in window.descendants():
        title = control.window_text().strip()
        control_type = control.element_info.control_type or ""
        if not title and control_type not in {"Button", "Edit", "MenuItem", "TabItem"}:
            continue
        bounds = control.rectangle()
        elements.append({
            "name": title[:160],
            "role": control_type,
            "bounds": {
                "left": bounds.left,
                "top": bounds.top,
                "width": bounds.width(),
                "height": bounds.height(),
            },
        })
        if len(elements) >= 100:
            break
    return elements


def _wait_for_visual_change(timeout: float = 10, threshold: float = 3.0) -> dict:
    _ensure_pyautogui()
    timeout = float(timeout)
    threshold = float(threshold)
    if not 0.1 <= timeout <= 30:
        raise ValueError("Visual-change timeout must be between 0.1 and 30 seconds.")
    if not 0 < threshold <= 100:
        raise ValueError("Visual-change threshold must be between 0 and 100.")
    baseline = _pg().screenshot().convert("RGB").resize((64, 64))
    baseline_bytes = baseline.tobytes()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _STOP_REQUESTED.is_set():
            return {"changed": False, "stopped": True}
        time.sleep(0.2)
        current = _pg().screenshot().convert("RGB").resize((64, 64))
        current_bytes = current.tobytes()
        difference = sum(
            abs(left - right)
            for left, right in zip(baseline_bytes, current_bytes)
        ) / max(1, len(current_bytes))
        if difference >= threshold:
            return {
                "changed": True,
                "elapsed_seconds": round(timeout - max(0, deadline - time.monotonic()), 2),
                "mean_pixel_difference": round(difference, 2),
            }
    return {"changed": False, "timed_out": True}


def _verify_action(expected_text: str) -> dict:
    expected = str(expected_text or "").strip().casefold()
    if not expected:
        raise ValueError("Provide the visible text or accessible label to verify.")
    matches = [
        element for element in _find_ui_elements()
        if expected in element["name"].casefold()
    ]
    return {
        "verified": bool(matches),
        "expected_text": expected_text,
        "matches": matches[:10],
    }


def _stop_all_input_actions() -> dict:
    _STOP_REQUESTED.set()
    errors = []
    if _PG_MOD not in (None, False):
        for button in tuple(_HELD_BUTTONS):
            try:
                _PG_MOD.mouseUp(button=button)
            except Exception as exc:
                errors.append(f"{button}: {exc}")
            _HELD_BUTTONS.discard(button)
        try:
            _PG_MOD.mouseUp()
        except Exception as exc:
            errors.append(f"release: {exc}")
    return {
        "stop_requested": True,
        "released_buttons": not errors,
        "release_errors": errors,
    }


def _set_emergency_hotkey(enabled: bool) -> dict:
    global _EMERGENCY_HOTKEY_ID
    try:
        import keyboard
    except ImportError as exc:
        raise RuntimeError("The keyboard package is required for the emergency hotkey.") from exc
    if enabled:
        if _EMERGENCY_HOTKEY_ID is None:
            _EMERGENCY_HOTKEY_ID = keyboard.add_hotkey(
                "ctrl+alt+pause",
                _stop_all_input_actions,
                suppress=False,
            )
        return {"enabled": True, "shortcut": "Ctrl+Alt+Pause"}
    if _EMERGENCY_HOTKEY_ID is not None:
        keyboard.remove_hotkey(_EMERGENCY_HOTKEY_ID)
        _EMERGENCY_HOTKEY_ID = None
    return {"enabled": False}


def _type_text(text: str, interval: float = 0.03) -> str:
    """Types text at the current cursor position."""
    _ensure_pyautogui()
    if not isinstance(text, str) or len(text) > 10_000:
        raise ValueError("Text must be a string of at most 10,000 characters.")
    interval = float(interval)
    if not 0 <= interval <= 0.5:
        raise ValueError("Typing interval must be between 0 and 0.5 seconds.")
    _STOP_REQUESTED.clear()
    previous_pause = _pg().PAUSE
    _pg().PAUSE = 0
    try:
        if not text.isascii():
            if not _PYPERCLIP:
                raise RuntimeError("Unicode typing requires the installed clipboard helper.")
            pyperclip.copy(text)
            _pg().hotkey("ctrl", "v")
        else:
            for character in text:
                if _STOP_REQUESTED.is_set():
                    return "Typing stopped by user."
                _pg().write(character, interval=0)
                if interval and _STOP_REQUESTED.wait(interval):
                    return "Typing stopped by user."
    finally:
        _pg().PAUSE = previous_pause
    return f"Typed: {text[:50]}{'...' if len(text) > 50 else ''}"


def _click(x: int = None, y: int = None, button: str = "left",
           clicks: int = 1, image: str = None) -> str:
    """
    Clicks at coordinates or on a screen image.
    If image path given, locates it on screen and clicks.
    """
    _ensure_pyautogui()
    if button not in {"left", "right", "middle"}:
        raise ValueError("Mouse button must be left, right, or middle.")
    if clicks not in {1, 2}:
        raise ValueError("Click count must be one or two.")

    if image:
        loc = _pg().locateCenterOnScreen(image, confidence=0.8)
        if not loc:
            raise RuntimeError(f"Image was not found on screen: {image}")
        x, y = loc.x, loc.y

    if x is not None and y is not None:
        width, height = _pg().size()
        x, y = int(x), int(y)
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(f"Click coordinates must be within the {width}x{height} screen.")
        _pg().click(x, y, button=button, clicks=clicks)
        return f"Clicked ({x}, {y}) with {button} button"

    _pg().click(button=button, clicks=clicks)
    return f"Clicked at current position"


def _hotkey(*keys) -> str:
    """Presses a key combination. E.g. hotkey('ctrl', 'c')"""
    _ensure_pyautogui()
    _pg().hotkey(*keys)
    return f"Hotkey: {'+'.join(keys)}"


def _press(key: str) -> str:
    """Presses a single key."""
    _ensure_pyautogui()
    _pg().press(key)
    return f"Pressed: {key}"


def _scroll(direction: str = "down", amount: int = 3) -> str:
    """Scrolls in the specified direction."""
    _ensure_pyautogui()
    if direction not in {"up", "down", "left", "right"}:
        raise ValueError("Scroll direction must be up, down, left, or right.")
    amount = int(amount)
    if not 1 <= amount <= 100:
        raise ValueError("Scroll amount must be between 1 and 100.")
    clicks = amount if direction in ("up", "right") else -amount
    if direction in ("up", "down"):
        _pg().scroll(clicks)
    else:
        _pg().hscroll(clicks)
    return f"Scrolled {direction} {amount} times"


def _move_mouse(x: int, y: int, duration: float = 0.3) -> str:
    """Moves mouse to coordinates."""
    _ensure_pyautogui()
    width, height = _pg().size()
    if not (0 <= int(x) < width and 0 <= int(y) < height):
        raise ValueError(f"Mouse coordinates must be within the {width}x{height} screen.")
    duration = float(duration)
    if not 0 <= duration <= 5:
        raise ValueError("Mouse movement duration must be between 0 and 5 seconds.")
    _STOP_REQUESTED.clear()
    start_x, start_y = _pg().position()
    steps = max(1, math.ceil(duration / 0.025))
    previous_pause = _pg().PAUSE
    _pg().PAUSE = 0
    try:
        for step in range(1, steps + 1):
            if _STOP_REQUESTED.is_set():
                return "Mouse movement stopped by user."
            progress = step / steps
            current_x = round(start_x + (int(x) - start_x) * progress)
            current_y = round(start_y + (int(y) - start_y) * progress)
            _pg().moveTo(current_x, current_y, duration=0)
            if duration and _STOP_REQUESTED.wait(duration / steps):
                return "Mouse movement stopped by user."
    finally:
        _pg().PAUSE = previous_pause
    return f"Mouse moved to ({x}, {y})"


def _drag(x1: int, y1: int, x2: int, y2: int, duration: float = 0.5) -> str:
    """Drags from (x1,y1) to (x2,y2)."""
    _ensure_pyautogui()
    width, height = _pg().size()
    if not all(0 <= value < limit for value, limit in (
        (x1, width), (x2, width), (y1, height), (y2, height)
    )):
        raise ValueError(f"Drag coordinates must be within the {width}x{height} screen.")
    duration = float(duration)
    if not 0 <= duration <= 5:
        raise ValueError("Drag duration must be between 0 and 5 seconds.")
    _STOP_REQUESTED.clear()
    _move_mouse(x1, y1, duration=0)
    _pg().mouseDown(button="left")
    _HELD_BUTTONS.add("left")
    try:
        steps = max(1, math.ceil(duration / 0.025))
        previous_pause = _pg().PAUSE
        _pg().PAUSE = 0
        try:
            for step in range(1, steps + 1):
                if _STOP_REQUESTED.is_set():
                    return "Drag stopped by user."
                progress = step / steps
                current_x = round(x1 + (x2 - x1) * progress)
                current_y = round(y1 + (y2 - y1) * progress)
                _pg().moveTo(current_x, current_y, duration=0)
                if duration and _STOP_REQUESTED.wait(duration / steps):
                    return "Drag stopped by user."
        finally:
            _pg().PAUSE = previous_pause
    finally:
        _pg().mouseUp(button="left")
        _HELD_BUTTONS.discard("left")
    return f"Dragged from ({x1},{y1}) to ({x2},{y2})"


def _clipboard_copy() -> str:
    """Gets current clipboard content."""
    if _PYPERCLIP:
        return pyperclip.paste()
    raise RuntimeError("Clipboard reading requires the installed pyperclip helper.")


def _clipboard_set(text: str) -> str:
    """Sets clipboard content and pastes it."""
    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.1)
        _hotkey("ctrl", "v")
        return f"Pasted: {text[:50]}"
    return "pyperclip not available"


def _screenshot(save_path: str = None) -> str:
    """Takes a screenshot."""
    _ensure_pyautogui()
    if not save_path:
        folder = Path.home() / "Pictures" / "NIANG_IA_Screenshots"
        folder.mkdir(parents=True, exist_ok=True)
        save_path = str(folder / f"screenshot_{datetime.now():%Y%m%d_%H%M%S_%f}.png")
    destination = Path(save_path).expanduser().resolve()
    try:
        destination.relative_to(Path.home().resolve())
    except ValueError as exc:
        raise ValueError("Screenshot files must be saved inside the current user's home folder.") from exc
    if destination.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        raise ValueError("Screenshots must use a .png, .jpg, or .jpeg extension.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    img = _capture_screen_image()
    img.save(destination)
    return str(destination.resolve())


def _capture_screen_image():
    import mss
    from PIL import Image

    with mss.MSS() as screens:
        shot = screens.grab(screens.monitors[0])
    return Image.frombytes("RGB", shot.size, shot.rgb)


def _wait(seconds: float) -> str:
    """Waits for specified seconds."""
    seconds = float(seconds)
    if not 0 <= seconds <= 30:
        raise ValueError("Wait duration must be between 0 and 30 seconds.")
    _STOP_REQUESTED.clear()
    if _STOP_REQUESTED.wait(seconds):
        return "Wait stopped by user."
    return f"Waited {seconds}s"


def _wait_for_image(image_path: str, timeout: int = 10) -> str:
    """Waits until an image appears on screen (up to timeout seconds)."""
    _ensure_pyautogui()
    timeout = int(timeout)
    if not 1 <= timeout <= 30:
        raise ValueError("Image wait timeout must be between 1 and 30 seconds.")
    _STOP_REQUESTED.clear()
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if _STOP_REQUESTED.is_set():
            return "Image wait stopped by user."
        loc = _pg().locateCenterOnScreen(image_path, confidence=0.8)
        if loc:
            return f"Image found at ({loc.x}, {loc.y})"
        _STOP_REQUESTED.wait(0.5)
    return f"Image not found within {timeout}s: {image_path}"


def _get_screen_size() -> str:
    """Returns current screen resolution."""
    _ensure_pyautogui()
    w, h = _pg().size()
    return f"{w}x{h}"


def _focus_window(title: str) -> str:
    """Brings a window to focus by title (Windows)."""
    if platform.system() == "Windows":
        try:
            # Single-quote the title and double any embedded quotes so a
            # malicious title can never break out of the PowerShell script.
            safe_title = title.replace("'", "''")
            script = f"(New-Object -ComObject WScript.Shell).AppActivate('{safe_title}')"
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=5, check=False
            )
            if result.returncode or result.stdout.strip().lower() != "true":
                raise RuntimeError(result.stderr.strip() or "Windows did not activate a matching window.")
            time.sleep(0.3)
            return f"Focused window: {title}"
        except Exception as e:
            return f"Could not focus window: {e}"
    return "Window focus only supported on Windows"


def _list_windows() -> str:
    """Enumerates open top-level window titles (Windows)."""
    if platform.system() != "Windows":
        return "Window listing only supported on Windows"
    try:
        import ctypes
        user32 = ctypes.windll.user32
        titles = []
        skip = {"", "Program Manager", "Default IME"}

        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        @EnumWindowsProc
        def _enum(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            if title and title not in skip:
                titles.append(title)
            return True

        user32.EnumWindows(_enum, None)
        titles = list(dict.fromkeys(titles))
        return "Open windows: " + " | ".join(titles[:15]) if titles else "No windows detected."
    except Exception as e:
        return f"Could not list windows: {e}"


def _select_all() -> str:
    return _hotkey("ctrl", "a")


def _clear_field() -> str:
    """Selects all and deletes — clears an input field."""
    _hotkey("ctrl", "a")
    time.sleep(0.1)
    _press("delete")
    return "Field cleared"


def _smart_type(text: str, clear_first: bool = True) -> str:
    """
    Types text into the currently focused field.
    Optionally clears the field first.
    Uses clipboard for long text (faster, more reliable).
    """
    if not isinstance(text, str) or len(text) > 10_000:
        raise ValueError("Text must be a string of at most 10,000 characters.")
    if clear_first:
        _clear_field()
        time.sleep(0.1)

    return _type_text(text)



def _describe_screen() -> str:
    raise RuntimeError(
        "Screen-image analysis is disabled: NIANG IA never sends screenshots to Gemini."
    )


def _parse_visual_target(text: str, width: int, height: int) -> dict | None:
    if "NOT_FOUND" in text.upper():
        return None
    try:
        target = json.loads(text)
        if (
            not isinstance(target, dict)
            or type(target["x"]) is not int
            or type(target["y"]) is not int
            or isinstance(target["confidence"], bool)
            or not isinstance(target["confidence"], (int, float))
        ):
            raise TypeError("visual target fields have incorrect types")
        x = target["x"]
        y = target["y"]
        confidence = float(target["confidence"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "Visual search must return JSON with x, y, and confidence."
        ) from exc
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise RuntimeError("Visual search confidence must be between 0 and 1.")
    if not 0 <= x < width or not 0 <= y < height:
        raise RuntimeError(
            f"Visual model returned out-of-screen coordinates ({x}, {y}) "
            f"for a {width}x{height} screen."
        )
    return {"x": x, "y": y, "confidence": confidence}


def _analyze_screen_for_element(description: str) -> dict | None:
    raise RuntimeError(
        "Visual screen search is disabled: NIANG IA never sends screenshots to Gemini."
    )

_SENSITIVE_PARAM_KEYS = {
    "text", "value", "password", "content", "message", "data",
    "description", "expected", "title", "path", "image",
}


def _safe_params(parameters: dict) -> dict:
    """Return params with potentially sensitive values masked for console logs."""
    if not isinstance(parameters, dict):
        return {}
    out = {}
    for k, v in parameters.items():
        if isinstance(v, str) and k.lower() in _SENSITIVE_PARAM_KEYS and len(v) > 3:
            out[k] = v[:2] + "…"
        else:
            out[k] = v
    return out

def computer_control(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    Universal computer control action.

    Actions:
      type          : Type text at current cursor position
      smart_type    : Clear field + type (clipboard-based for long text)
      click         : Click at coordinates or on image
      double_click  : Double click
      right_click   : Right click
      hotkey        : Key combination (e.g. ctrl+c)
      press         : Single key press
      scroll        : Scroll up/down/left/right
      move          : Move mouse to coordinates
      drag          : Drag from one point to another
      copy          : Get clipboard content
      paste         : Set and paste clipboard content
      screenshot    : Take a screenshot
      wait          : Wait N seconds
      wait_image    : Wait for image to appear on screen
      clear_field   : Select all + delete in current field
      focus_window  : Bring window to foreground
      screen_find   : AI-powered element finder — returns coordinates
      screen_click  : AI-powered element finder + click
      screen_info   : Screen resolution, scaling, and attached monitors
      active_window : Current foreground window title and bounds
      find_ui_elements : Accessible controls from the active Windows window
      wait_for_visual_change : Wait for a real screen change
      screen_monitor_start : Sample screen changes locally at a 30 ms target (no uploads)
      screen_monitor_status : Show local monitor state and change counts only
      screen_monitor_stop : Stop local screen monitoring
      verify_action : Verify visible text through Windows UI Automation
      mouse_down / mouse_up : Hold or release a mouse button
      stop : Release held mouse buttons and cancel interruptible input
      enable_emergency_stop / disable_emergency_stop : Ctrl+Alt+Pause global stop
      random_data   : Generate random data for forms
      user_data     : Get user's real data from memory
    """
    action = (parameters or {}).get("action", "").lower().strip()

    if not action:
        return "Please specify an action for computer_control, sir."

    if player:
        player.write_log(f"[Computer] {action}")

    _log(f"[ComputerControl] Action: {action}  Params: {_safe_params(parameters)}")

    try:
        if action == "screen_monitor_start":
            from actions.local_screen_monitor import start_monitor
            result = start_monitor()
            return _action_result(
                action,
                executed=result["state"] in {"starting", "running"},
                result=result,
                verified=result["state"] == "running",
                error=result.get("error") or "",
            )

        elif action == "screen_monitor_status":
            from actions.local_screen_monitor import monitor_status
            result = monitor_status()
            return _action_result(
                action,
                executed=True,
                result=result,
                verified=result["state"] in {"running", "stopped"},
                error=result.get("error") or "",
            )

        elif action == "screen_monitor_stop":
            from actions.local_screen_monitor import stop_monitor
            result = stop_monitor()
            return _action_result(
                action,
                executed=result["state"] != "running",
                result=result,
                verified=result["state"] == "stopped",
                error=result.get("error") or "",
            )

        elif action == "type":
            text = parameters.get("text", "")
            return _action_result(action, executed=True, result=_type_text(text))

        elif action == "smart_type":
            text        = parameters.get("text", "")
            clear_first = parameters.get("clear_first", True)
            result = _smart_type(text, clear_first=clear_first)
            return _action_result(action, executed=True, result=result)
        
        elif action in ("click", "left_click"):
            result = _click(
                x=parameters.get("x"),
                y=parameters.get("y"),
                button="left",
                clicks=1,
                image=parameters.get("image")
            )
            return _action_result(action, executed=True, result=result)

        elif action == "double_click":
            result = _click(
                x=parameters.get("x"),
                y=parameters.get("y"),
                button="left",
                clicks=2,
                image=parameters.get("image")
            )
            return _action_result(action, executed=True, result=result)

        elif action == "right_click":
            result = _click(
                x=parameters.get("x"),
                y=parameters.get("y"),
                button="right",
                clicks=1
            )
            return _action_result(action, executed=True, result=result)

        elif action == "move":
            result = _move_mouse(
                x=int(parameters.get("x", 0)),
                y=int(parameters.get("y", 0)),
                duration=float(parameters.get("duration", 0.3))
            )
            return _action_result(action, executed=True, result=result)

        elif action == "drag":
            result = _drag(
                x1=int(parameters.get("x1", 0)),
                y1=int(parameters.get("y1", 0)),
                x2=int(parameters.get("x2", 0)),
                y2=int(parameters.get("y2", 0)),
                duration=float(parameters.get("duration", 0.5)),
            )
            return _action_result(action, executed=True, result=result)

        elif action == "mouse_down":
            button = str(parameters.get("button", "left"))
            if button not in {"left", "right", "middle"}:
                raise ValueError("Mouse button must be left, right, or middle.")
            _pg().mouseDown(button=button)
            _HELD_BUTTONS.add(button)
            return _action_result(action, executed=True, result={"button": button, "held": True})

        elif action == "mouse_up":
            button = str(parameters.get("button", "left"))
            if button not in {"left", "right", "middle"}:
                raise ValueError("Mouse button must be left, right, or middle.")
            _pg().mouseUp(button=button)
            _HELD_BUTTONS.discard(button)
            return _action_result(action, executed=True, result={"button": button, "held": False})

        elif action == "hotkey":
            keys = parameters.get("keys", "")
            if isinstance(keys, str):
                keys = [k.strip() for k in keys.split("+")]
            _STOP_REQUESTED.clear()
            return _action_result(action, executed=True, result=_hotkey(*keys))

        elif action == "press":
            _STOP_REQUESTED.clear()
            return _action_result(action, executed=True, result=_press(parameters.get("key", "enter")))

        elif action == "scroll":
            if parameters.get("x") is not None and parameters.get("y") is not None:
                _move_mouse(int(parameters["x"]), int(parameters["y"]), duration=0)
            result = _scroll(
                direction=parameters.get("direction", "down"),
                amount=int(parameters.get("amount", 3))
            )
            return _action_result(action, executed=True, result=result)

        elif action == "copy":
            return _action_result(action, executed=True, result=_clipboard_copy(), verified=True)

        elif action == "paste":
            result = _clipboard_set(parameters.get("text", ""))
            return _action_result(
                action,
                executed=result.startswith("Pasted:"),
                result=result,
            )

        elif action in {"screenshot", "capture_screen"}:
            result = _screenshot(parameters.get("path"))
            return _action_result(
                action,
                executed=True,
                result={"path": result},
                verified=Path(result).is_file(),
            )

        elif action in {"screen_info", "get_screen_info"}:
            return _action_result(action, executed=True, result=_screen_info(), verified=True)

        elif action in {"active_window", "get_active_window"}:
            return _action_result(action, executed=True, result=_active_window(), verified=True)

        elif action in {"find_ui_elements", "ui_elements"}:
            elements = _find_ui_elements()
            return _action_result(action, executed=True, result=elements, verified=True)

        elif action == "wait_for_visual_change":
            result = _wait_for_visual_change(
                timeout=float(parameters.get("timeout", 10)),
                threshold=float(parameters.get("threshold", 3)),
            )
            return _action_result(
                action,
                executed=True,
                result=result,
                verified=bool(result.get("changed")),
            )

        elif action == "verify_action":
            result = _verify_action(parameters.get("expected", ""))
            return _action_result(
                action,
                executed=True,
                result=result,
                verified=bool(result.get("verified")),
            )

        elif action == "stop":
            return _action_result(action, executed=True, result=_stop_all_input_actions(), verified=True)

        elif action == "enable_emergency_stop":
            return _action_result(action, executed=True, result=_set_emergency_hotkey(True), verified=True)

        elif action == "disable_emergency_stop":
            return _action_result(action, executed=True, result=_set_emergency_hotkey(False), verified=True)

        elif action == "wait":
            result = _wait(float(parameters.get("seconds", 1.0)))
            return _action_result(action, executed=True, result=result)

        elif action == "wait_image":
            result = _wait_for_image(
                parameters.get("image", ""),
                timeout=int(parameters.get("timeout", 10))
            )
            return _action_result(
                action,
                executed=True,
                result=result,
                verified=result.startswith("Image found at"),
            )

        elif action == "clear_field":
            return _action_result(action, executed=True, result=_clear_field())

        elif action == "focus_window":
            result = _focus_window(parameters.get("title", ""))
            succeeded = result.startswith("Focused window:")
            return _action_result(
                action,
                executed=succeeded,
                result=result,
                verified=succeeded,
                error="" if succeeded else result,
            )

        elif action in ("list_windows", "windows", "what_is_open"):
            return _action_result(action, executed=True, result=_list_windows(), verified=True)

        elif action == "screen_size":
            return _action_result(action, executed=True, result=_get_screen_size(), verified=True)

        elif action == "screen_describe":
            raise RuntimeError(
                "Screen-image analysis is disabled: NIANG IA never sends screenshots to Gemini."
            )

        elif action == "screen_find":
            raise RuntimeError(
                "Visual screen search is disabled: NIANG IA never sends screenshots to Gemini."
            )

        elif action == "screen_click":
            raise RuntimeError(
                "Visual screen clicking is disabled: NIANG IA never sends screenshots to Gemini."
            )

        elif action == "random_data":
            data_type = parameters.get("type", "name")
            result    = generate_random_data(data_type)
            _log(f"[ComputerControl] Random {data_type} generated")
            return _action_result(action, executed=True, result=result, verified=True)

        elif action == "user_data":
            field   = parameters.get("field", "name")
            profile = _load_user_profile()
            value   = profile.get(field, "")
            if not value:
                return _action_result(
                    action,
                    executed=False,
                    error=f"No saved user value exists for '{field}'; no substitute was generated.",
                )
            return _action_result(action, executed=True, result=value, verified=True)

        else:
            return _action_result(
                action,
                executed=False,
                error=f"Unknown computer_control action: '{action}'",
            )

    except Exception as e:
        _log(f"[ComputerControl] Error: {e}")
        return _action_result(action, executed=False, error=f"{type(e).__name__}: {e}")
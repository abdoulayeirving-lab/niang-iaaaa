"""Local Windows window discovery and guarded UI automation."""

from __future__ import annotations

import ctypes
import json
import os
import re
import time
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from typing import Any


_SW_RESTORE = 9
_SW_MINIMIZE = 6
_GW_OWNER = 4
_WM_CLOSE = 0x0010
_OCR = None


class WindowsDesktopError(RuntimeError):
    """A Windows desktop operation could not be completed safely."""


def _user32():
    if os.name != "nt":
        raise WindowsDesktopError("Windows desktop control is available only on Windows.")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    return user32


@contextmanager
def _physical_dpi_context():
    if os.name != "nt":
        yield
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    set_context = getattr(user32, "SetThreadDpiAwarenessContext", None)
    if set_context is None:
        yield
        return
    set_context.argtypes = [ctypes.c_void_p]
    set_context.restype = ctypes.c_void_p
    previous = set_context(ctypes.c_void_p(-4))
    if not previous:
        error = ctypes.get_last_error()
        raise WindowsDesktopError(
            f"Could not enable physical-pixel window coordinates (Windows error {error})."
        )
    try:
        yield
    finally:
        set_context(previous)


def _send_unicode_text(text: str) -> None:
    dword = wintypes.DWORD
    word = wintypes.WORD
    ulong_ptr = ctypes.c_size_t

    class KeyboardInput(ctypes.Structure):
        _fields_ = [
            ("virtual_key", word),
            ("scan_code", word),
            ("flags", dword),
            ("time", dword),
            ("extra_info", ulong_ptr),
        ]

    class MouseInput(ctypes.Structure):
        _fields_ = [
            ("x", ctypes.c_int32),
            ("y", ctypes.c_int32),
            ("data", dword),
            ("flags", dword),
            ("time", dword),
            ("extra_info", ulong_ptr),
        ]

    class HardwareInput(ctypes.Structure):
        _fields_ = [("message", dword), ("low_param", word), ("high_param", word)]

    class InputUnion(ctypes.Union):
        _fields_ = [
            ("mouse", MouseInput),
            ("keyboard", KeyboardInput),
            ("hardware", HardwareInput),
        ]

    class Input(ctypes.Structure):
        _fields_ = [("type", dword), ("value", InputUnion)]

    key_events = []
    encoded = text.encode("utf-16-le")
    for offset in range(0, len(encoded), 2):
        scan_code = int.from_bytes(encoded[offset:offset + 2], "little")
        key_events.extend((
            Input(1, InputUnion(keyboard=KeyboardInput(0, scan_code, 0x0004, 0, 0))),
            Input(1, InputUnion(keyboard=KeyboardInput(0, scan_code, 0x0006, 0, 0))),
        ))
    if not key_events:
        return
    events = (Input * len(key_events))(*key_events)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = [dword, ctypes.POINTER(Input), ctypes.c_int]
    user32.SendInput.restype = dword
    sent = int(user32.SendInput(len(events), events, ctypes.sizeof(Input)))
    if sent != len(events):
        error = ctypes.get_last_error()
        raise WindowsDesktopError(
            f"Windows accepted {sent} of {len(events)} text input events (error {error})."
        )


def _process_details(pid: int) -> dict[str, Any]:
    try:
        import psutil
    except ImportError:
        return {"process_name": None, "parent_pid": None, "process_state": None}
    try:
        process = psutil.Process(pid)
        parent = process.parent()
        return {
            "process_name": process.name(),
            "parent_pid": parent.pid if parent else None,
            "process_state": process.status(),
        }
    except (OSError, RuntimeError, psutil.Error):
        return {"process_name": None, "parent_pid": None, "process_state": None}


def _window_record(
    hwnd: int,
    user32,
    process_details_cache: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not user32.IsWindow(hwnd):
        return None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    length = max(0, user32.GetWindowTextLengthW(hwnd))
    title = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title, length + 1)
    class_name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_name, len(class_name))
    rectangle = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
        bounds = None
    else:
        bounds = {
            "left": rectangle.left,
            "top": rectangle.top,
            "width": max(0, rectangle.right - rectangle.left),
            "height": max(0, rectangle.bottom - rectangle.top),
        }
    visible = bool(user32.IsWindowVisible(hwnd))
    owner = user32.GetWindow(hwnd, _GW_OWNER)
    owner_pid = int(pid.value)
    if process_details_cache is None:
        details = _process_details(owner_pid)
    else:
        if owner_pid not in process_details_cache:
            process_details_cache[owner_pid] = _process_details(owner_pid)
        details = process_details_cache[owner_pid]
    return {
        "hwnd": int(hwnd),
        "title": title.value.strip(),
        "pid": owner_pid,
        **details,
        "class_name": class_name.value,
        "visible": visible,
        "minimized": bool(user32.IsIconic(hwnd)),
        "owner_hwnd": int(owner) if owner else None,
        "role": "secondary" if owner else "main",
        "bounds": bounds,
    }


class WindowsDesktopAgent:
    """Combines native window APIs, UI Automation, OCR, and input fallbacks."""

    def list_windows(
        self,
        *,
        pid: int | None = None,
        include_children: bool = True,
        include_hidden: bool = True,
        include_untitled: bool = False,
    ) -> list[dict[str, Any]]:
        user32 = _user32()
        windows: list[dict[str, Any]] = []
        process_details_cache: dict[int, dict[str, Any]] = {}
        process_ids = {int(pid)} if pid is not None else None
        if pid is not None and include_children:
            try:
                import psutil
            except ImportError:
                psutil = None
            if psutil is not None:
                try:
                    process_ids.update(
                        child.pid for child in psutil.Process(int(pid)).children(recursive=True)
                    )
                except (psutil.Error, OSError, RuntimeError):
                    pass
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def visit(hwnd, _):
            try:
                if process_ids is not None:
                    owner_pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
                    if int(owner_pid.value) not in process_ids:
                        return True
                if not include_hidden and not user32.IsWindowVisible(hwnd):
                    return True
                record = _window_record(int(hwnd), user32, process_details_cache)
                if record is None:
                    return True
                if not include_untitled and not record["title"]:
                    return True
                windows.append(record)
            except (OSError, ValueError):
                return True
            return True

        with _physical_dpi_context():
            if not user32.EnumWindows(visit, 0):
                error = ctypes.get_last_error()
                if error:
                    raise WindowsDesktopError(f"EnumWindows failed with Windows error {error}.")
        return windows

    def window(self, *, hwnd: int | str | None = None, pid: int | None = None, title: str | None = None) -> dict:
        if hwnd is not None:
            try:
                handle = int(str(hwnd), 0)
            except ValueError as exc:
                raise WindowsDesktopError("hwnd must be a decimal or 0x-prefixed integer.") from exc
            with _physical_dpi_context():
                match = _window_record(handle, _user32())
            if match is None:
                raise WindowsDesktopError("The requested window handle is not open in this desktop session.")
            return match
        windows = self.list_windows(pid=pid, include_hidden=True, include_untitled=True)
        requested = str(title or "").strip().casefold()
        if requested:
            exact = [item for item in windows if item["title"].casefold() == requested]
            matches = exact or [
                item for item in windows
                if requested in item["title"].casefold()
            ]
            if len(matches) != 1:
                reason = "not found" if not matches else f"ambiguous ({len(matches)} matches)"
                raise WindowsDesktopError(f"Window title {title!r} is {reason}.")
            return matches[0]
        if pid is not None:
            candidates = [
                item for item in windows
                if item["visible"] and item["role"] == "main" and item["title"]
            ]
            if candidates:
                return max(
                    candidates,
                    key=lambda item: (
                        item["bounds"]["width"] * item["bounds"]["height"]
                        if item["bounds"] else 0
                    ),
                )
        raise WindowsDesktopError("Specify a window handle, unique title, or process ID.")

    def process_tree(self, pid: int) -> list[dict[str, Any]]:
        try:
            import psutil
        except ImportError as exc:
            raise WindowsDesktopError("psutil is required to inspect process children.") from exc
        try:
            root = psutil.Process(int(pid))
            processes = [root, *root.children(recursive=True)]
        except (psutil.Error, ValueError) as exc:
            raise WindowsDesktopError(f"Could not inspect process {pid}: {exc}") from exc
        result = []
        for process in processes:
            try:
                result.append({
                    "pid": process.pid,
                    "parent_pid": process.ppid(),
                    "process_name": process.name(),
                    "state": process.status(),
                    "create_time": process.create_time(),
                })
            except (psutil.Error, OSError):
                continue
        return result

    def controls(self, hwnd: int, *, backend: str = "uia", limit: int = 200) -> list[dict]:
        if backend not in {"uia", "win32"}:
            raise WindowsDesktopError("UI Automation backend must be 'uia' or 'win32'.")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise WindowsDesktopError("Control limit must be from 1 to 500.")
        try:
            from pywinauto import Desktop
        except ImportError as exc:
            raise WindowsDesktopError("pywinauto is required to inspect Windows controls.") from exc
        try:
            root = Desktop(backend=backend).window(handle=int(hwnd)).wrapper_object()
            descendants = root.descendants()
        except Exception as exc:
            raise WindowsDesktopError(f"{backend} control discovery failed: {exc}") from exc
        result = []
        for control in descendants[:limit]:
            try:
                info = control.element_info
                rectangle = control.rectangle()
                runtime_id = getattr(info, "runtime_id", None)
                if runtime_id is not None and not isinstance(runtime_id, (str, int, float, bool)):
                    runtime_id = list(runtime_id)
                result.append({
                    "name": str(getattr(info, "name", "") or control.window_text())[:200],
                    "role": str(getattr(info, "control_type", "") or ""),
                    "automation_id": str(getattr(info, "automation_id", "") or ""),
                    "runtime_id": runtime_id,
                    "class_name": str(getattr(info, "class_name", "") or ""),
                    "enabled": _safe_control_bool(control, "is_enabled"),
                    "visible": _safe_control_bool(control, "is_visible"),
                    "bounds": {
                        "left": rectangle.left,
                        "top": rectangle.top,
                        "width": rectangle.width(),
                        "height": rectangle.height(),
                    },
                    "backend": backend,
                })
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                continue
        return result

    def inspect(self, *, hwnd: int | str, use_ocr: bool = True) -> dict:
        window = self.window(hwnd=hwnd)
        if window["visible"] and not window["minimized"]:
            window = self._activate_visible_window(window["hwnd"])
        controls = {}
        errors = {}
        for backend in ("uia", "win32"):
            try:
                controls[backend] = self.controls(window["hwnd"], backend=backend)
            except WindowsDesktopError as exc:
                controls[backend] = []
                errors[backend] = str(exc)
        text = []
        if use_ocr and window["visible"] and not window["minimized"]:
            window = self.window(hwnd=window["hwnd"])
            frame, origin = self._capture(window)
            text = self._read_ocr(frame, origin)
        return {
            "window": window,
            "controls": controls,
            "ocr_text": text,
            "local_only": True,
            "backend_errors": errors,
        }

    def activate(self, hwnd: int | str) -> dict:
        window = self.window(hwnd=hwnd)
        user32 = _user32()
        handle = window["hwnd"]
        if window["minimized"]:
            user32.ShowWindow(handle, _SW_RESTORE)
        requested = bool(user32.SetForegroundWindow(handle))
        time.sleep(0.1)
        focused = int(user32.GetForegroundWindow() or 0) == handle
        if not focused:
            try:
                from pywinauto import Application

                Application(backend="uia").connect(handle=handle).top_window().set_focus()
                time.sleep(0.1)
                focused = int(user32.GetForegroundWindow() or 0) == handle
            except Exception:
                pass
        return {
            "window": self.window(hwnd=handle),
            "requested": requested,
            "focused": focused,
        }

    def _activate_visible_window(self, hwnd: int) -> dict:
        for attempt in range(3):
            result = self.activate(hwnd)
            if result["focused"]:
                return result["window"]
            if attempt < 2:
                time.sleep(0.1)
        raise WindowsDesktopError("The selected window could not be verified in the foreground.")

    def minimize(self, hwnd: int | str) -> dict:
        window = self.window(hwnd=hwnd)
        _user32().ShowWindow(window["hwnd"], _SW_MINIMIZE)
        time.sleep(0.1)
        updated = self.window(hwnd=window["hwnd"])
        return {"window": updated, "verified": updated["minimized"]}

    def close(self, hwnd: int | str, timeout_seconds: float = 3) -> dict:
        window = self.window(hwnd=hwnd)
        posted = bool(_user32().PostMessageW(window["hwnd"], _WM_CLOSE, 0, 0))
        deadline = time.monotonic() + max(0.1, min(float(timeout_seconds), 10))
        while time.monotonic() < deadline:
            if not _user32().IsWindow(window["hwnd"]):
                return {"hwnd": window["hwnd"], "close_requested": posted, "verified": True}
            time.sleep(0.05)
        return {"hwnd": window["hwnd"], "close_requested": posted, "verified": False}

    def screenshot(self, hwnd: int | str, path: str | None = None) -> dict:
        window = self._activate_visible_window(self.window(hwnd=hwnd)["hwnd"])
        window = self.window(hwnd=window["hwnd"])
        frame, _ = self._capture(window)
        destination = Path(path).expanduser() if path else (
            Path.home() / "Pictures" / "NIANG_IA_Screenshots"
            / f"window_{window['hwnd']}_{int(time.time() * 1000)}.png"
        )
        destination = destination.resolve()
        try:
            destination.relative_to(Path.home().resolve())
        except ValueError as exc:
            raise WindowsDesktopError("Screenshots must be saved inside the current user's home folder.") from exc
        if destination.suffix.casefold() != ".png":
            raise WindowsDesktopError("Window screenshots must use a .png extension.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        import cv2

        if not cv2.imwrite(str(destination), frame):
            raise WindowsDesktopError("The local screenshot could not be written.")
        return {
            "hwnd": window["hwnd"],
            "path": str(destination),
            "saved_locally": True,
            "uploaded": False,
        }

    def click(
        self,
        hwnd: int | str,
        *,
        name: str | None = None,
        automation_id: str | None = None,
        x: int | None = None,
        y: int | None = None,
    ) -> dict:
        window = self.window(hwnd=hwnd)
        if name or automation_id:
            control, backend = self._find_control(
                window["hwnd"], name=name, automation_id=automation_id
            )
            window = self._activate_visible_window(window["hwnd"])
            before_controls = self.controls(window["hwnd"], backend=backend)
            before_frame = self._capture(window)[0] if window["visible"] and not window["minimized"] else None
            invoke = getattr(control, "iface_invoke", None)
            if invoke is not None:
                invoke.Invoke()
            else:
                control.click_input()
            time.sleep(0.2)
            after_controls = self.controls(window["hwnd"], backend=backend)
            changed = before_controls != after_controls
            if before_frame is not None:
                try:
                    after_frame = self._capture(self.window(hwnd=window["hwnd"]))[0]
                    changed = changed or _images_changed(before_frame, after_frame)
                except WindowsDesktopError:
                    pass
            return {
                "target": name or automation_id,
                "backend": backend,
                "verified": changed,
                "method": "control-pattern" if invoke is not None else "accessible-control",
            }
        if x is None and y is None and name:
            raise WindowsDesktopError("A Tkinter visual click requires an OCR target or explicit coordinates.")
        if x is None or y is None:
            raise WindowsDesktopError("Specify a unique accessible control or both click coordinates.")
        window = self._activate_visible_window(window["hwnd"])
        self._validate_point(window, x, y)
        import pyautogui

        before, _ = self._capture(window)
        pyautogui.click(int(x), int(y))
        time.sleep(0.2)
        after, _ = self._capture(window)
        changed = _images_changed(before, after)
        return {
            "x": int(x),
            "y": int(y),
            "method": "screen-coordinate-fallback",
            "verified": changed,
        }

    def click_text(self, hwnd: int | str, text: str) -> dict:
        if not isinstance(text, str) or not text.strip():
            raise WindowsDesktopError("A visible text label is required for OCR-based clicking.")
        window = self.window(hwnd=hwnd)
        window = self._activate_visible_window(window["hwnd"])
        window = self.window(hwnd=window["hwnd"])
        before, origin = self._capture(window)
        matches = self._matching_text(self._read_ocr(before, origin), text)
        if len(matches) != 1:
            reason = "not found" if not matches else f"ambiguous ({len(matches)} matches)"
            raise WindowsDesktopError(f"Visible text {text!r} is {reason}.")
        event = matches[0]
        x, y, width, height = event["bounds"]
        target_x, target_y = x + width // 2, y + height // 2
        import pyautogui

        pyautogui.click(target_x, target_y)
        time.sleep(0.2)
        if not _user32().IsWindow(window["hwnd"]):
            return {
                "target": text,
                "coordinates": {"x": target_x, "y": target_y},
                "method": "local-ocr-coordinate-fallback",
                "verified": True,
                "window_closed": True,
            }
        after, after_origin = self._capture(self.window(hwnd=window["hwnd"]))
        changed = _images_changed(before, after)
        before_text = [item["text"] for item in self._read_ocr(before, origin)]
        after_text = [item["text"] for item in self._read_ocr(after, after_origin)]
        return {
            "target": text,
            "coordinates": {"x": target_x, "y": target_y},
            "method": "local-ocr-coordinate-fallback",
            "verified": changed or before_text != after_text,
        }

    def type_text(
        self,
        hwnd: int | str,
        text: str,
        *,
        name: str | None = None,
        automation_id: str | None = None,
        x: int | None = None,
        y: int | None = None,
    ) -> dict:
        if not isinstance(text, str) or len(text) > 10_000:
            raise WindowsDesktopError("Text must be a string of at most 10,000 characters.")
        window = self.window(hwnd=hwnd)
        if name or automation_id:
            window = self._activate_visible_window(window["hwnd"])
            control, backend = self._find_control(
                window["hwnd"], name=name, automation_id=automation_id,
                roles={"Edit", "Document", "ComboBox"},
            )
            control.set_edit_text(text)
            try:
                verified = control.get_value() == text
            except (AttributeError, NotImplementedError, RuntimeError):
                verified = control.window_text() == text
            return {
                "target": name or automation_id,
                "backend": backend,
                "verified": verified,
                "method": "value-pattern",
            }
        if x is None or y is None:
            raise WindowsDesktopError(
                "The target has no accessible edit control; specify screen coordinates for this Tkinter fallback."
            )
        window = self._activate_visible_window(window["hwnd"])
        self._validate_point(window, x, y)
        import pyautogui

        pyautogui.click(int(x), int(y))
        time.sleep(0.1)
        if os.name == "nt":
            _send_unicode_text(text)
        else:
            pyautogui.write(text, interval=0.01)
        deadline = time.monotonic() + 2
        visible_text = ""
        while True:
            frame, origin = self._capture(self.window(hwnd=window["hwnd"]))
            visible_text = " ".join(event["text"] for event in self._read_ocr(frame, origin))
            expected_text = _compact_text(text)
            if (
                expected_text
                and expected_text in _compact_text(visible_text)
            ) or time.monotonic() >= deadline:
                break
            time.sleep(0.15)
        return {
            "method": "screen-coordinate-fallback",
            "verified": text.casefold() in visible_text.casefold(),
        }

    def press(self, hwnd: int | str, keys: str) -> dict:
        window = self.window(hwnd=hwnd)
        values = [part.strip().casefold() for part in str(keys or "").split("+")]
        allowed = {
            "alt", "ctrl", "shift", "win", "enter", "tab", "esc", "space",
            "backspace", "delete", "home", "end", "up", "down", "left", "right",
            "pageup", "pagedown", "f1", "f2", "f3", "f4", "f5", "f6", "f7",
            "f8", "f9", "f10", "f11", "f12", "a", "c", "v", "x", "z", "y",
        }
        if not values or any(value not in allowed for value in values):
            raise WindowsDesktopError("The requested keyboard shortcut contains an unsupported key.")
        window = self._activate_visible_window(window["hwnd"])
        import pyautogui

        before, _ = self._capture(window)
        pyautogui.hotkey(*values)
        time.sleep(0.2)
        after, _ = self._capture(window)
        return {"keys": values, "verified": _images_changed(before, after)}

    def scroll(self, hwnd: int | str, amount: int, x: int | None = None, y: int | None = None) -> dict:
        window = self.window(hwnd=hwnd)
        if type(amount) is not int or not -100 <= amount <= 100:
            raise WindowsDesktopError("Scroll amount must be an integer from -100 to 100.")
        if (x is None) != (y is None):
            raise WindowsDesktopError("Provide both coordinates or neither.")
        window = self._activate_visible_window(window["hwnd"])
        import pyautogui

        before, _ = self._capture(window)
        if x is not None:
            self._validate_point(window, x, y)
            pyautogui.moveTo(int(x), int(y))
        else:
            bounds = window.get("bounds")
            if bounds:
                center_x = int(bounds["left"] + bounds["width"] / 2)
                center_y = int(bounds["top"] + bounds["height"] / 2)
                pyautogui.moveTo(center_x, center_y)
        # Scroll in repeated notches; a single pyautogui.scroll(1) moves
        # almost nothing in most apps.
        notches = max(1, min(10, abs(int(amount))))
        direction = 1 if int(amount) >= 0 else -1
        amount_value = int(amount)
        for _ in range(notches):
            pyautogui.scroll(direction * max(1, abs(amount_value) // notches))
            time.sleep(0.05)
        time.sleep(0.2)
        method = "wheel"
        after, _ = self._capture(window)
        changed = _images_changed(before, after)
        if not changed:
            # Some windows ignore the mouse wheel; fall back to Page keys.
            fallback_key = "pagedown" if amount_value < 0 else "pageup"
            steps = max(1, min(5, abs(amount_value)))
            for _ in range(steps):
                pyautogui.press(fallback_key)
                time.sleep(0.1)
            time.sleep(0.2)
            after, _ = self._capture(window)
            changed = _images_changed(before, after)
            if changed:
                method = "keyboard"
        return {"amount": amount, "verified": changed, "method": method}

    def verify_text(self, hwnd: int | str, expected: str) -> dict:
        if not isinstance(expected, str) or not expected.strip():
            raise WindowsDesktopError("Expected text must not be empty.")
        deadline = time.monotonic() + 1
        while True:
            observed = self.inspect(hwnd=hwnd)
            accessible = [
                str(control.get("name", ""))
                for values in observed["controls"].values()
                for control in values
            ]
            accessible_text = "\n".join(accessible)
            ocr_text = "\n".join(
                item["text"] for item in _group_ocr_lines(observed["ocr_text"])
            )
            verified = (
                expected.casefold() in (accessible_text + "\n" + ocr_text).casefold()
                or _compact_text(expected) in _compact_text(ocr_text)
            )
            if verified or time.monotonic() >= deadline:
                return {
                    "expected": expected,
                    "verified": verified,
                    "window": observed["window"],
                    "local_only": True,
                }
            time.sleep(0.15)

    def _find_control(
        self,
        hwnd: int,
        *,
        name: str | None,
        automation_id: str | None,
        roles: set[str] | None = None,
    ):
        errors = []
        wanted_name = str(name or "").strip().casefold()
        wanted_id = str(automation_id or "").strip()
        for backend in ("uia", "win32"):
            try:
                from pywinauto import Desktop

                root = Desktop(backend=backend).window(handle=hwnd).wrapper_object()
                matches = []
                for control in root.descendants():
                    info = control.element_info
                    control_name = str(getattr(info, "name", "") or control.window_text()).strip()
                    control_id = str(getattr(info, "automation_id", "") or "")
                    role = str(getattr(info, "control_type", "") or "")
                    if roles and role not in roles:
                        continue
                    if wanted_id and control_id == wanted_id:
                        matches.append(control)
                    elif wanted_name and control_name.casefold() == wanted_name:
                        matches.append(control)
                if len(matches) == 1:
                    return matches[0], backend
                if len(matches) > 1:
                    raise WindowsDesktopError(
                        f"Accessible control {name or automation_id!r} is ambiguous ({len(matches)} matches)."
                    )
            except WindowsDesktopError:
                raise
            except Exception as exc:
                errors.append(f"{backend}: {exc}")
        detail = f" Backend errors: {'; '.join(errors)}" if errors else ""
        raise WindowsDesktopError(
            f"Accessible control {name or automation_id!r} was not found.{detail}"
        )

    @staticmethod
    def _validate_point(window: dict, x: int, y: int) -> None:
        bounds = window.get("bounds")
        if not bounds or not (
            bounds["left"] <= int(x) < bounds["left"] + bounds["width"]
            and bounds["top"] <= int(y) < bounds["top"] + bounds["height"]
        ):
            raise WindowsDesktopError("Pointer coordinates must be inside the selected window bounds.")

    @staticmethod
    def _capture(window: dict):
        if not window["visible"] or window["minimized"]:
            raise WindowsDesktopError("Restore and show the selected window before capturing its screen.")
        try:
            import cv2
            import mss
            import numpy as np
        except ImportError as exc:
            raise WindowsDesktopError("mss and OpenCV are required for local desktop capture.") from exc
        bounds = window["bounds"]
        if not bounds or bounds["width"] <= 0 or bounds["height"] <= 0:
            raise WindowsDesktopError("The selected window has no capturable screen rectangle.")
        with mss.MSS() as screens:
            monitor = screens.monitors[0]
            raw = screens.grab(monitor)
        desktop = np.frombuffer(raw.raw, dtype=np.uint8).reshape(raw.height, raw.width, 4)
        desktop = cv2.cvtColor(desktop, cv2.COLOR_BGRA2BGR)
        origin_x, origin_y = int(monitor["left"]), int(monitor["top"])
        x1 = max(0, bounds["left"] - origin_x)
        y1 = max(0, bounds["top"] - origin_y)
        x2 = min(raw.width, bounds["left"] + bounds["width"] - origin_x)
        y2 = min(raw.height, bounds["top"] + bounds["height"] - origin_y)
        if x2 <= x1 or y2 <= y1:
            raise WindowsDesktopError("The selected window is outside the current display capture.")
        return desktop[y1:y2, x1:x2].copy(), (origin_x + x1, origin_y + y1)

    @staticmethod
    def _read_ocr(frame, origin: tuple[int, int]) -> list[dict]:
        global _OCR
        if _OCR is None:
            from vision.ocr_engine import OCRConfig, OCREngine

            _OCR = OCREngine(OCRConfig(languages="eng", min_confidence=30, scale=1.0))
        events = _OCR.extract(frame)
        if _OCR.error:
            raise WindowsDesktopError(_OCR.error)
        ox, oy = origin
        return [
            {
                "text": event.label,
                "confidence": round(float(event.confidence), 3),
                "bounds": (
                    int(event.bbox[0] + ox),
                    int(event.bbox[1] + oy),
                    int(event.bbox[2]),
                    int(event.bbox[3]),
                ),
                "source": "local-ocr",
            }
            for event in events
            if event.label and event.bbox
        ]

    @staticmethod
    def _matching_text(events: list[dict], expected: str) -> list[dict]:
        target = re.sub(r"\s+", " ", expected.strip()).casefold()
        grouped = _group_ocr_lines(events)
        exact = [
            event for event in grouped
            if re.sub(r"\s+", " ", event["text"].strip()).casefold() == target
        ]
        return exact or [
            event for event in grouped
            if target in re.sub(r"\s+", " ", event["text"].strip()).casefold()
        ]


def _safe_control_bool(control, method: str) -> bool | None:
    try:
        return bool(getattr(control, method)())
    except (AttributeError, OSError, RuntimeError):
        return None


def _group_ocr_lines(events: list[dict]) -> list[dict]:
    rows: list[dict[str, Any]] = []
    for event in sorted(
        events,
        key=lambda item: (
            item["bounds"][1] + item["bounds"][3] / 2,
            item["bounds"][0],
        ),
    ):
        x, y, width, height = event["bounds"]
        center = y + height / 2
        row = next(
            (
                candidate for candidate in rows
                if abs(center - candidate["center"]) <= max(8, height * 0.6)
            ),
            None,
        )
        if row is None:
            rows.append({
                "center": center,
                "words": [(x, event["text"])],
                "x1": x,
                "y1": y,
                "x2": x + width,
                "y2": y + height,
            })
        else:
            row["words"].append((x, event["text"]))
            row["x1"] = min(row["x1"], x)
            row["y1"] = min(row["y1"], y)
            row["x2"] = max(row["x2"], x + width)
            row["y2"] = max(row["y2"], y + height)
    return [
        {
            "text": " ".join(text for _, text in sorted(row["words"])),
            "bounds": (
                row["x1"],
                row["y1"],
                row["x2"] - row["x1"],
                row["y2"] - row["y1"],
            ),
        }
        for row in rows
    ]


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _images_changed(before, after) -> bool:
    import cv2

    if before.shape != after.shape:
        return True
    return float(cv2.absdiff(before, after).mean()) >= 1.0


_DEFAULT_DESKTOP_AGENT = WindowsDesktopAgent()


def windows_desktop_control(parameters: dict) -> str:
    args = dict(parameters or {})
    action = str(args.get("action", "")).strip().lower()
    agent = _DEFAULT_DESKTOP_AGENT
    try:
        if action in {"window_list", "list_windows"}:
            result = agent.list_windows(
                pid=args.get("pid"),
                include_hidden=bool(args.get("include_hidden", True)),
                include_untitled=bool(args.get("include_untitled", False)),
            )
            verified = True
        elif action == "window_observe":
            target = agent.window(
                hwnd=args.get("hwnd"), pid=args.get("pid"), title=args.get("title")
            )
            result = agent.inspect(hwnd=target["hwnd"], use_ocr=bool(args.get("use_ocr", True)))
            verified = True
        elif action == "window_activate":
            target = agent.window(
                hwnd=args.get("hwnd"), pid=args.get("pid"), title=args.get("title")
            )
            result = agent.activate(target["hwnd"])
            verified = result["focused"]
        elif action == "window_minimize":
            target = agent.window(
                hwnd=args.get("hwnd"), pid=args.get("pid"), title=args.get("title")
            )
            result = agent.minimize(target["hwnd"])
            verified = result["verified"]
        elif action == "window_close":
            target = agent.window(
                hwnd=args.get("hwnd"), pid=args.get("pid"), title=args.get("title")
            )
            result = agent.close(target["hwnd"])
            verified = result["verified"]
        elif action == "window_screenshot":
            target = agent.window(
                hwnd=args.get("hwnd"), pid=args.get("pid"), title=args.get("title")
            )
            result = agent.screenshot(target["hwnd"], path=args.get("path"))
            verified = True
        elif action == "window_click":
            target = agent.window(
                hwnd=args.get("hwnd"), pid=args.get("pid"), title=args.get("title")
            )
            if args.get("text"):
                result = agent.click_text(target["hwnd"], args["text"])
            else:
                result = agent.click(
                    target["hwnd"],
                    name=args.get("name"),
                    automation_id=args.get("automation_id"),
                    x=args.get("x"),
                    y=args.get("y"),
                )
            verified = result.get("verified", False)
        elif action == "window_type":
            target = agent.window(
                hwnd=args.get("hwnd"), pid=args.get("pid"), title=args.get("title")
            )
            result = agent.type_text(
                target["hwnd"], args.get("text", ""),
                name=args.get("name"),
                automation_id=args.get("automation_id"),
                x=args.get("x"),
                y=args.get("y"),
            )
            verified = result["verified"]
        elif action == "window_press":
            target = agent.window(
                hwnd=args.get("hwnd"), pid=args.get("pid"), title=args.get("title")
            )
            result = agent.press(target["hwnd"], args.get("keys", ""))
            verified = result["verified"]
        elif action == "window_scroll":
            target = agent.window(
                hwnd=args.get("hwnd"), pid=args.get("pid"), title=args.get("title")
            )
            result = agent.scroll(
                target["hwnd"],
                args.get("amount", -3),
                x=args.get("x"),
                y=args.get("y"),
            )
            verified = result["verified"]
        elif action == "window_verify":
            target = agent.window(
                hwnd=args.get("hwnd"), pid=args.get("pid"), title=args.get("title")
            )
            result = agent.verify_text(target["hwnd"], args.get("expected", ""))
            verified = result["verified"]
        else:
            raise WindowsDesktopError(f"Unsupported Windows desktop action: {action or '(empty)'}")
        return json.dumps({
            "action": action,
            "executed": True,
            "verified": bool(verified),
            "result": result,
            "local_only": True,
            "error": None,
        }, ensure_ascii=False)
    except (WindowsDesktopError, OSError, ValueError, TypeError) as exc:
        return json.dumps({
            "action": action,
            "executed": False,
            "verified": False,
            "result": None,
            "local_only": True,
            "error": str(exc),
        }, ensure_ascii=False)

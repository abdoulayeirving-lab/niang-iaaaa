"""Windows window tracking (native Win32 API, no screenshots required).

Window enumeration is cheap enough to run a few times per second, which makes
it the backbone of "which application am I looking at?" even when the pixel
pipeline is idle.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import threading
from dataclasses import dataclass, field
from typing import Any

from ctypes import wintypes


@dataclass(slots=True)
class WindowInfo:
    """A top-level window."""

    hwnd: int
    title: str = ""
    pid: int = 0
    process_name: str = ""
    class_name: str = ""
    visible: bool = False
    minimized: bool = False
    foreground: bool = False
    bounds: dict[str, int] | None = None
    role: str = "main"

    def to_dict(self) -> dict[str, Any]:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "pid": self.pid,
            "process_name": self.process_name,
            "class_name": self.class_name,
            "visible": self.visible,
            "minimized": self.minimized,
            "foreground": self.foreground,
            "bounds": dict(self.bounds) if self.bounds else None,
            "role": self.role,
        }

    def label(self) -> str:
        if self.process_name and self.title:
            return f"{self.process_name} — {self.title}"
        return self.title or self.process_name or self.class_name or str(self.hwnd)


@contextlib.contextmanager
def _dpi_context():
    """Return physical-pixel coordinates for the current thread."""
    if os.name != "nt":
        yield
        return
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
    except Exception:
        yield
        return
    set_context = getattr(user32, "SetThreadDpiAwarenessContext", None)
    if set_context is None:
        yield
        return
    set_context.argtypes = [ctypes.c_void_p]
    set_context.restype = ctypes.c_void_p
    previous = set_context(ctypes.c_void_p(-4))
    try:
        yield
    finally:
        if previous:
            try:
                set_context(previous)
            except Exception:
                pass


def _user32() -> Any:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetForegroundWindow.restype = wintypes.HWND
    return user32


class WindowTracker:
    """Enumerates top-level windows and tracks focus changes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._previous: dict[int, WindowInfo] = {}
        self._process_cache: dict[int, str] = {}
        self._error: str | None = None

    # ── Errors ──────────────────────────────────────────────────────────────
    @property
    def error(self) -> str | None:
        return self._error

    @property
    def supported(self) -> bool:
        return os.name == "nt"

    # ── Enumeration ─────────────────────────────────────────────────────────
    def snapshot(
        self,
        *,
        include_hidden: bool = False,
        include_untitled: bool = False,
    ) -> list[WindowInfo]:
        """Return the current top-level windows."""
        if os.name != "nt":
            self._error = "Window tracking is only available on Windows."
            return []
        try:
            user32 = _user32()
        except Exception as exc:
            self._error = f"Windows API unavailable: {exc}"
            return []

        foreground = self.foreground_hwnd()
        results: list[WindowInfo] = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        with self._lock:
            cache = self._process_cache

        @callback_type
        def visit(hwnd, _lparam):
            try:
                if not user32.IsWindow(hwnd):
                    return True
                visible = bool(user32.IsWindowVisible(hwnd))
                if not visible and not include_hidden:
                    return True
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                length = max(0, user32.GetWindowTextLengthW(hwnd))
                title_buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title_buffer, length + 1)
                title = title_buffer.value.strip()
                if not title and not include_untitled:
                    return True
                class_buffer = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
                rectangle = wintypes.RECT()
                bounds = None
                if user32.GetWindowRect(hwnd, ctypes.byref(rectangle)):
                    bounds = {
                        "left": int(rectangle.left),
                        "top": int(rectangle.top),
                        "width": max(0, int(rectangle.right) - int(rectangle.left)),
                        "height": max(0, int(rectangle.bottom) - int(rectangle.top)),
                    }
                owner = user32.GetWindow(hwnd, 4)  # GW_OWNER
                process_name = self._process_name(int(pid.value), cache)
                results.append(
                    WindowInfo(
                        hwnd=int(hwnd),
                        title=title,
                        pid=int(pid.value),
                        process_name=process_name,
                        class_name=class_buffer.value,
                        visible=visible,
                        minimized=bool(user32.IsIconic(hwnd)),
                        foreground=int(hwnd) == foreground,
                        bounds=bounds,
                        role="secondary" if owner else "main",
                    )
                )
            except (OSError, ValueError):
                return True
            return True

        try:
            with _dpi_context():
                user32.EnumWindows(visit, 0)
        except Exception as exc:
            self._error = f"Window enumeration failed: {exc}"
            return []
        self._error = None
        return results

    def foreground_hwnd(self) -> int:
        if os.name != "nt":
            return 0
        try:
            user32 = _user32()
            return int(user32.GetForegroundWindow() or 0)
        except Exception:
            return 0

    def foreground(self) -> WindowInfo | None:
        """Return the focused top-level window, if any."""
        for window in self.snapshot():
            if window.foreground:
                return window
        return None

    # ── Diffing ─────────────────────────────────────────────────────────────
    def diff(self, current: list[WindowInfo]) -> dict[str, list[dict[str, Any]]]:
        """Compare the current window list with the previous one."""
        previous = self._previous
        current_map = {window.hwnd: window for window in current}
        opened = [
            current_map[hwnd].to_dict()
            for hwnd in current_map
            if hwnd not in previous
        ]
        closed = [
            previous[hwnd].to_dict()
            for hwnd in previous
            if hwnd not in current_map
        ]
        focused_before = next(
            (item.hwnd for item in previous.values() if item.foreground), 0
        )
        focused_after = next(
            (window.hwnd for window in current if window.foreground), 0
        )
        self._previous = current_map
        return {
            "opened": opened,
            "closed": closed,
            "focus_changed": focused_before != focused_after,
            "focused_hwnd": focused_after,
            "previous_focused_hwnd": focused_before,
        }

    def remember(self, windows: list[WindowInfo]) -> None:
        """Prime the diff baseline without reporting a change."""
        with self._lock:
            self._previous = {window.hwnd: window for window in windows}

    # ── Process names ───────────────────────────────────────────────────────
    @staticmethod
    def _process_name(pid: int, cache: dict[int, str]) -> str:
        if pid in cache:
            return cache[pid]
        name = ""
        try:
            import psutil

            name = psutil.Process(pid).name()
        except Exception:
            name = ""
        cache[pid] = name
        return name


__all__ = ["WindowTracker", "WindowInfo"]

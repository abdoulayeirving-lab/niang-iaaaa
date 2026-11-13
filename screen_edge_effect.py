# screen_edge_effect.py
# NIANG IA — blue screen-edge activation effect (Windows).
#
# When the wake word ("Hey Niang") is heard, the four edges of the desktop
# light up in electric blue before the holographic sphere appears.
#
# Implementation notes
# --------------------
# · A borderless Tk Toplevel is placed over the whole virtual screen
#   (all monitors). It is a "click-through" overlay: the window procedure
#   answers HTTRANSPARENT to WM_NCHITTEST, so the mouse and the keyboard
#   keep working on the applications underneath. The window never takes the
#   focus (WS_EX_NOACTIVATE) and never blocks the desktop.
# · The glow is rendered with NumPy into small RGBA images (Pillow) — one
#   band per screen edge — and drawn on a colour-key canvas. The centre of
#   the screen is never painted: the desktop stays completely visible.
# · The animation runs on `after` timers inside the existing Tk loop, so the
#   wake-listener thread never touches the overlay directly (every call is
#   marshalled onto the Tk thread by the UI dispatcher).
# · Multi-monitor and resolution changes are supported: the monitor
#   rectangles are re-read on every frame and the overlay is re-placed when
#   they change.

from __future__ import annotations

import ctypes
import math
import time
import tkinter as tk
from ctypes import wintypes

try:
    import numpy as np
except Exception:                                    # pragma: no cover
    np = None

try:
    from PIL import Image, ImageTk
    _PIL = True
except Exception:                                    # pragma: no cover
    _PIL = False

# ── Windows constants ───────────────────────────────────────────────────────
GWL_EXSTYLE  = -20
GWL_WNDPROC  = -4
WS_EX_LAYERED     = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE  = 0x08000000
WS_EX_TOOLWINDOW  = 0x00000080
WS_EX_TOPMOST     = 0x00000008
SWP_NOSIZE  = 0x0001
SWP_NOMOVE  = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST = -1
GA_ROOT = 2
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1

user32 = ctypes.windll.user32

try:                                                 # 64-bit safe accessors
    _LONG_PTR = ctypes.c_ssize_t
    user32.GetWindowLongPtrW.restype = _LONG_PTR
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongPtrW.restype = _LONG_PTR
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, _LONG_PTR]
except Exception:                                    # pragma: no cover
    pass

# Keep a reference to every installed window procedure (never let it die).
_WNDPROCS: list = []

# ── Look & feel ─────────────────────────────────────────────────────────────
KEY_COLOR  = "#000001"          # colour key => those pixels are invisible
CORE_RGB   = (110, 233, 255)    # cyan core of the halo
EDGE_RGB   = (10, 95, 255)      # electric blue body of the halo
SPREAD     = 9.0                # halo thickness (tight: no fog on the desktop)
CORE_WIDTH = 1.1                # thickness of the bright inner line
BAND       = 22                 # depth of the rendered halo band (inward)
RENDER_SCALE = 0.5              # bands rendered at half resolution, then scaled

# Crisp vector frame (drawn with canvas lines: perfectly sharp)
CORE_COLOR  = "#6FE9FF"         # the neon line itself (vivid cyan)
INNER_COLOR = "#1E6BFF"         # thin second line, slightly inside
BRACKET_COLOR = "#CFF7FF"       # corner brackets
INSET       = 12                # inset of the second line
BRACKET     = 62                # length of a corner bracket
EDGE_INSET  = 1.5               # keeps the whole neon line on screen

# Timeline (ms)
T_APPEAR    = 200               # 0-200 ms    : the frame appears
T_PROPAGATE = 900               # 200-900 ms  : the light travels around the edges
T_PULSE     = 1600              # 900-1600 ms : pulsing
T_STABLE    = 2200              # 1600-2200   : stabilised
LISTEN_ALPHA = 0.45             # soft glow kept while NIANG IA listens
THINK_ALPHA  = 0.85             # brighter glow while NIANG IA thinks


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def list_monitors():
    """Return the list of monitor rectangles (physical pixels)."""
    found = []
    proc_type = ctypes.WINFUNCTYPE(
        ctypes.c_bool, wintypes.HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def callback(hmon, hdc, rect, data):
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        try:
            if user32.GetMonitorInfoW(hmon, ctypes.byref(info)):
                r = info.rcMonitor
                found.append((r.left, r.top, r.right, r.bottom))
        except Exception:
            pass
        return True

    try:
        user32.EnumDisplayMonitors(None, None, proc_type(callback), 0)
    except Exception:
        pass
    if not found:
        try:
            found.append((0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)))
        except Exception:
            found.append((0, 0, 1920, 1080))
    return found


def _virtual_bbox(monitors):
    x0 = min(m[0] for m in monitors)
    y0 = min(m[1] for m in monitors)
    x1 = max(m[2] for m in monitors)
    y1 = max(m[3] for m in monitors)
    return x0, y0, x1 - x0, y1 - y0


def _make_click_through(hwnd):
    """Subclass the window procedure so every click goes to the windows below.

    A colour-keyed layered window is normally click-through only on its
    transparent pixels; the glowing frame would still catch the mouse.
    Answering HTTRANSPARENT to WM_NCHITTEST makes the whole overlay
    invisible to the pointer.
    """
    if not hwnd:
        return None
    try:
        old_addr = user32.GetWindowLongPtrW(hwnd, GWL_WNDPROC)
        if not old_addr:
            return None
        WNDPROC = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, ctypes.c_uint,
            ctypes.c_size_t, ctypes.c_ssize_t)
        old_proc = WNDPROC(old_addr)

        def _proc(h, msg, wparam, lparam):
            if msg == WM_NCHITTEST:
                return HTTRANSPARENT
            return old_proc(h, msg, wparam, lparam)

        proc = WNDPROC(_proc)
        _WNDPROCS.append((proc, old_proc))
        user32.SetWindowLongPtrW(hwnd, GWL_WNDPROC,
                                 ctypes.cast(proc, ctypes.c_void_p).value)
        return proc
    except Exception:
        return None


class ScreenEdgeEffect:
    """Neon frame drawn around the screen edges on wake-word detection."""

    def __init__(self, root, dispatch=None, on_error=None):
        self.root = root
        self._dispatch = dispatch or (lambda fn: root.after(0, fn))
        self._on_error = on_error
        self._win = None            # the overlay Toplevel
        self._canvas = None
        self._photos = []           # keep the Tk images alive
        self._items = []            # canvas item ids (halo bitmaps)
        self._line_items = []       # canvas item ids (crisp vector frame)
        self._job = None
        self._t0 = 0.0
        self._state = "idle"
        self._target_alpha = 0.0
        self._geo = None            # (x, y, w, h) of the overlay
        self._monitors = []
        self._last_prop = -1.0
        self._alive = True
        self._click_through = False

    # ── Public API (thread-safe: always marshalled onto the Tk thread) ──────
    def show_activation_effect(self):
        """Full sequence: appear -> propagate -> pulse -> stabilise."""
        self._dispatch(self._show_activation_effect)

    def set_listening_effect(self):
        """Soft steady glow while NIANG IA is listening."""
        self._dispatch(self._set_listening_effect)

    def set_thinking_effect(self):
        """Brighter, faster pulse while NIANG IA is thinking."""
        self._dispatch(self._set_thinking_effect)

    def hide_activation_effect(self):
        """Fade the frame out and remove the overlay."""
        self._dispatch(self._hide_activation_effect)

    def on_state(self, state: str):
        """Hook called by the UI when NIANG IA changes state."""
        state = (state or "").upper()
        if state == "LISTENING":
            self.set_listening_effect()
        elif state in ("THINKING", "PROCESSING"):
            self.set_thinking_effect()
        elif state == "SLEEPING":
            self.hide_activation_effect()

    # ── Tk-thread implementations ───────────────────────────────────────────
    def _show_activation_effect(self):
        self._alive = True
        self._state = "activation"
        self._t0 = time.monotonic()
        self._last_prop = -1.0
        self._ensure_window()
        if self._win is None:
            return
        self._apply_geometry(force=True)
        self._render_frame(progress=0.0, intensity=1.0)
        self._set_window_alpha(0.20)
        self._show_window()
        self._schedule(16)

    def _set_listening_effect(self):
        if self._state == "activation":
            return
        self._state = "listening"
        self._target_alpha = LISTEN_ALPHA
        if self._win is None:
            return
        self._ensure_window()
        self._apply_geometry(force=True)
        self._render_frame(progress=1.0, intensity=1.0)
        self._show_window()
        if self._job is None:
            self._schedule(16)

    def _set_thinking_effect(self):
        if self._state == "activation":
            return
        self._state = "thinking"
        self._target_alpha = THINK_ALPHA
        if self._win is None:
            return
        self._ensure_window()
        self._apply_geometry(force=True)
        self._render_frame(progress=1.0, intensity=1.0)
        self._show_window()
        if self._job is None:
            self._schedule(16)

    def _hide_activation_effect(self):
        self._state = "idle"
        self._target_alpha = 0.0
        if self._win is None:
            return
        self._fade_out()

    # ── Overlay window ──────────────────────────────────────────────────────
    def _ensure_window(self):
        if self._win is not None:
            return
        if not _PIL or np is None:
            return
        try:
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            try:
                win.wm_attributes("-toolwindow", True)
            except Exception:
                pass
            win.configure(bg=KEY_COLOR)
            try:
                win.attributes("-transparentcolor", KEY_COLOR)
            except Exception:
                pass
            canvas = tk.Canvas(win, bg=KEY_COLOR, highlightthickness=0,
                               bd=0, takefocus=0)
            canvas.pack(fill="both", expand=True)
            self._win = win
            self._canvas = canvas
        except Exception as exc:
            self._fail(exc)
            self._win = None
            self._canvas = None

    def _hwnd(self):
        try:
            hwnd = self._win.winfo_id()
            root = user32.GetAncestor(hwnd, GA_ROOT)
            return root or hwnd
        except Exception:
            return None

    def _apply_ex_styles(self):
        """Layered + click-through + no-activate. Must run AFTER the window is
        mapped: setting WS_EX_LAYERED on an unmapped window breaks its
        rendering."""
        hwnd = self._hwnd()
        if not hwnd:
            return
        try:
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                style | WS_EX_LAYERED | WS_EX_TRANSPARENT |
                WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)
        except Exception as exc:
            self._fail(exc)
        if not self._click_through:
            self._click_through = _make_click_through(hwnd) is not None

    def _apply_geometry(self, force=False):
        """Place the overlay over the whole virtual screen (all monitors)."""
        monitors = list_monitors()
        bbox = _virtual_bbox(monitors)
        if not force and bbox == self._geo and monitors == self._monitors:
            return
        self._monitors = monitors
        self._geo = bbox
        x, y, w, h = bbox
        try:
            self._win.geometry(f"{w}x{h}{x:+d}{y:+d}")
        except Exception:
            pass
        hwnd = self._hwnd()
        if hwnd:
            try:
                user32.SetWindowPos(hwnd, HWND_TOPMOST, x, y, w, h,
                                    SWP_NOACTIVATE | SWP_SHOWWINDOW)
            except Exception as exc:
                self._fail(exc)
        try:
            self._canvas.configure(width=w, height=h)
        except Exception:
            pass

    def _show_window(self):
        hwnd = self._hwnd()
        try:
            self._win.deiconify()
            self._win.lift()
        except Exception:
            pass
        if hwnd:
            try:
                user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                                    SWP_NOACTIVATE | SWP_SHOWWINDOW |
                                    SWP_NOMOVE | SWP_NOSIZE)
            except Exception:
                pass
        # the extended styles must be applied once the window is on screen
        self._apply_ex_styles()

    def _set_window_alpha(self, value):
        try:
            self._win.attributes("-alpha", max(0.0, min(1.0, value)))
        except Exception:
            pass

    def _destroy(self):
        self._cancel()
        self._photos = []
        self._items = []
        self._line_items = []
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:
                pass
        self._win = None
        self._canvas = None
        self._click_through = False

    # ── Rendering ───────────────────────────────────────────────────────────
    def _band_alpha(self, length, depth, u_values):
        """Alpha profile of one edge band (length x depth) plus its
        perimeter parameter."""
        d = depth[:, None]                       # distance from the edge
        u = u_values[None, :]                    # perimeter parameter
        glow = np.exp(-d / SPREAD)
        core = np.exp(-d / CORE_WIDTH)
        alpha = 0.80 * glow + 0.80 * core
        return alpha

    def _render_frame(self, progress: float, intensity: float = 1.0):
        """Draw the neon frame: a tight halo + a crisp vector frame."""
        if self._canvas is None or self._geo is None:
            return
        try:
            self._render_halo(progress, intensity)
            self._render_frame_lines(progress, intensity)
        except Exception as exc:
            self._fail(exc)

    def _render_halo(self, progress: float, intensity: float = 1.0):
        """Soft halo behind the crisp frame (bitmap, updated only when needed)."""
        if self._canvas is None or self._geo is None:
            return
        if abs(progress - self._last_prop) < 0.02 and self._items:
            return
        self._last_prop = progress
        try:
            photos = []
            for (mx0, my0, mx1, my1) in self._monitors:
                mw = max(1, mx1 - mx0)
                mh = max(1, my1 - my0)
                photos.append(self._make_band(mw, mx0, my0, "h", 0.00, 0.25,
                                              False, False, progress, intensity))
                photos.append(self._make_band(mh, mx1 - BAND, my0, "v", 0.25, 0.50,
                                              False, True, progress, intensity))
                photos.append(self._make_band(mw, mx1 - mw, my1 - BAND, "h", 0.50,
                                              0.75, True, True, progress, intensity))
                photos.append(self._make_band(mh, mx0, my1 - mh, "v", 0.75, 1.00,
                                              True, False, progress, intensity))
            for index, entry in enumerate(photos):
                if entry is None:
                    continue
                photo, px, py = entry
                if index < len(self._items):
                    try:
                        self._canvas.itemconfigure(self._items[index], image=photo)
                        self._canvas.coords(self._items[index], px, py)
                    except Exception:
                        self._items = self._items[:index]
                else:
                    item = self._canvas.create_image(px, py, image=photo,
                                                     anchor="nw")
                    self._items.append(item)
            self._photos = [e[0] for e in photos if e is not None]
        except Exception as exc:
            self._fail(exc)

    def _sweep_segments(self, monitor, progress):
        """Parts of the perimeter already lit by the travelling light."""
        mx0, my0, mx1, my1 = monitor
        w = max(1, mx1 - mx0)
        h = max(1, my1 - my0)
        segs = []
        p = progress / 0.25
        if p > 0:
            segs.append(((mx0, my0), (mx0 + min(1.0, p) * w, my0)))
        p = (progress - 0.25) / 0.25
        if p > 0:
            segs.append(((mx1, my0), (mx1, my0 + min(1.0, p) * h)))
        p = (progress - 0.5) / 0.25
        if p > 0:
            segs.append(((mx1, my1), (mx1 - min(1.0, p) * w, my1)))
        p = (progress - 0.75) / 0.25
        if p > 0:
            segs.append(((mx0, my1), (mx0, my1 - min(1.0, p) * h)))
        return segs

    def _render_frame_lines(self, progress: float, intensity: float = 1.0):
        """Crisp neon frame drawn with canvas lines (sharp, no blur)."""
        canvas = self._canvas
        if canvas is None or self._geo is None:
            return
        try:
            for item in self._line_items:
                try:
                    canvas.delete(item)
                except Exception:
                    pass
            self._line_items = []
            x0, y0 = self._geo[0], self._geo[1]

            def add(coords, color, width):
                if len(coords) < 4:
                    return
                pts = [coords[0] - x0, coords[1] - y0,
                       coords[2] - x0, coords[3] - y0]
                try:
                    self._line_items.append(
                        canvas.create_line(*pts, fill=color, width=width,
                                           capstyle="butt"))
                except Exception:
                    pass

            for monitor in self._monitors:
                mx0, my0, mx1, my1 = monitor
                # The neon line is drawn slightly INSIDE the screen: a line
                # exactly on the border would be half cut off by the screen
                # edge and the frame would look incomplete.
                top_y = my0 + EDGE_INSET
                bot_y = my1 - EDGE_INSET
                lef_x = mx0 + EDGE_INSET
                rig_x = mx1 - EDGE_INSET
                # corner brackets first (they appear as the light reaches them)
                corners = [
                    (mx0, my0, mx0 + BRACKET, top_y, lef_x, my0, lef_x,
                     my0 + BRACKET, 0.0),
                    (mx1, my0, mx1 - BRACKET, top_y, rig_x, my0, rig_x,
                     my0 + BRACKET, 0.25),
                    (mx1, my1, mx1 - BRACKET, bot_y, rig_x, my1, rig_x,
                     my1 - BRACKET, 0.5),
                    (mx0, my1, mx0 + BRACKET, bot_y, lef_x, my1, lef_x,
                     my1 - BRACKET, 0.75),
                ]
                for (ax, ay, bx, by, cx, cy, dx, dy, gate) in corners:
                    if progress < gate:
                        continue
                    add((ax, ay, bx, by), BRACKET_COLOR, 3)
                    add((cx, cy, dx, dy), BRACKET_COLOR, 3)
                # the neon line itself, drawn as the light travels (on top)
                for (a, b) in self._sweep_segments(monitor, progress):
                    if abs(a[1] - b[1]) < 0.5:            # horizontal edge
                        y = top_y if a[1] <= my0 + 1 else bot_y
                        add((a[0], y, b[0], y), CORE_COLOR, 3)
                    else:                                 # vertical edge
                        x = lef_x if a[0] <= mx0 + 1 else rig_x
                        add((x, a[1], x, b[1]), CORE_COLOR, 3)
                # second thin line, once the frame is complete
                if progress >= 0.999:
                    add((mx0 + INSET, my0 + INSET, mx1 - INSET, my0 + INSET),
                        INNER_COLOR, 1)
                    add((mx0 + INSET, my1 - INSET, mx1 - INSET, my1 - INSET),
                        INNER_COLOR, 1)
                    add((mx0 + INSET, my0 + INSET, mx0 + INSET, my1 - INSET),
                        INNER_COLOR, 1)
                    add((mx1 - INSET, my0 + INSET, mx1 - INSET, my1 - INSET),
                        INNER_COLOR, 1)
        except Exception as exc:
            self._fail(exc)

    def _make_band(self, length, origin_x, origin_y, axis, u_start, u_end,
                   reverse_u, flip_depth, progress, intensity):
        """Render one edge band and return the Tk image (or None)."""
        depth = BAND
        scale = RENDER_SCALE
        try:
            if axis == "h":
                wl = max(8, int(length * scale))      # columns = along the edge
                wd = max(4, int(depth * scale))       # rows    = depth
                pos = (np.arange(wl) + 0.5) * (length / wl)
                dist = (np.arange(wd) + 0.5) * (depth / wd)
                if flip_depth:
                    dist = depth - dist
                alpha = (0.80 * np.exp(-dist[:, None] / SPREAD) +
                         0.80 * np.exp(-dist[:, None] / CORE_WIDTH))   # (wd,1)
                tint = np.clip(dist[:, None] / (SPREAD * 1.4), 0.0, 1.0)
                u = u_start + (u_end - u_start) * (pos / max(1.0, length))
                if reverse_u:
                    u = u_start + (u_end - u_start) * (1.0 - pos / max(1.0, length))
                sweep = np.clip((progress - u[None, :]) / 0.06, 0.0, 1.0)  # (1,wl)
                fade = np.clip(1.0 - dist[:, None] / max(1.0, depth), 0.0, 1.0)
            else:
                wl = max(4, int(depth * scale))       # columns = depth
                wd = max(8, int(length * scale))      # rows    = along the edge
                pos = (np.arange(wd) + 0.5) * (length / wd)
                dist = (np.arange(wl) + 0.5) * (depth / wl)
                if flip_depth:
                    dist = depth - dist
                alpha = (0.80 * np.exp(-dist[None, :] / SPREAD) +
                         0.80 * np.exp(-dist[None, :] / CORE_WIDTH))   # (1,wl)
                tint = np.clip(dist[None, :] / (SPREAD * 1.4), 0.0, 1.0)
                u = u_start + (u_end - u_start) * (pos / max(1.0, length))
                if reverse_u:
                    u = u_start + (u_end - u_start) * (1.0 - pos / max(1.0, length))
                sweep = np.clip((progress - u[:, None]) / 0.06, 0.0, 1.0)  # (wd,1)
                fade = np.clip(1.0 - dist[None, :] / max(1.0, depth), 0.0, 1.0)
            sweep = sweep * sweep * (3.0 - 2.0 * sweep)
            fade = fade * fade * (3.0 - 2.0 * fade)
            alpha = np.clip(alpha * sweep * intensity * fade, 0.0, 1.0)
            rgb = np.empty((wd, wl, 3), dtype=np.float32)
            for c in range(3):
                rgb[..., c] = CORE_RGB[c] * (1 - tint) + EDGE_RGB[c] * tint
            data = np.empty((wd, wl, 4), dtype=np.uint8)
            data[..., 0] = rgb[..., 0].astype(np.uint8)
            data[..., 1] = rgb[..., 1].astype(np.uint8)
            data[..., 2] = rgb[..., 2].astype(np.uint8)
            data[..., 3] = (alpha * 255).astype(np.uint8)
            img = Image.fromarray(data, "RGBA")
            if axis == "h":
                img = img.resize((length, depth), Image.BILINEAR)
            else:
                img = img.resize((depth, length), Image.BILINEAR)
            photo = ImageTk.PhotoImage(img)
            return (photo, origin_x - self._geo[0], origin_y - self._geo[1])
        except Exception as exc:
            self._fail(exc)
            return None

    # ── Animation loop ──────────────────────────────────────────────────────
    def _schedule(self, delay):
        self._cancel()
        try:
            self._job = self.root.after(delay, self._tick)
        except Exception:
            self._job = None

    def _cancel(self):
        if self._job is not None:
            try:
                self.root.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _tick(self):
        self._job = None
        if not self._alive or self._state == "idle":
            return
        now = time.monotonic()
        elapsed = (now - self._t0) * 1000.0

        # geometry may have changed (resolution / monitor moved)
        self._apply_geometry()
        # keep the overlay on top and click-through
        self._apply_ex_styles()

        if self._state == "activation":
            if elapsed < T_APPEAR:
                k = elapsed / T_APPEAR
                # the frame is already drawn: the appearance is done with the
                # window opacity (free), no need to re-render the images
                if self._last_prop < 0:
                    self._last_prop = 0.10
                    self._render_frame(progress=0.10, intensity=1.0)
                self._set_window_alpha(0.20 + 0.80 * k * k)
            elif elapsed < T_PROPAGATE:
                p = min(1.0, (elapsed - T_APPEAR) / (T_PROPAGATE - T_APPEAR))
                self._set_window_alpha(1.0)
                if abs(p - self._last_prop) > 0.05:
                    self._last_prop = p
                    self._render_frame(progress=p, intensity=1.0)
            elif elapsed < T_PULSE:
                # the travelling light must complete its tour before the
                # pulsing phase, otherwise a part of the frame stays dark
                if self._last_prop < 0.999:
                    self._last_prop = 1.0
                    self._render_frame(progress=1.0, intensity=1.0)
                k = (elapsed - T_PROPAGATE) / (T_PULSE - T_PROPAGATE)
                self._set_window_alpha(0.72 + 0.28 * abs(math.sin(k * math.pi * 3)))
            elif elapsed < T_STABLE:
                k = (elapsed - T_PULSE) / (T_STABLE - T_PULSE)
                self._set_window_alpha(1.0 - 0.25 * k)
            else:
                self._state = "listening"
                self._target_alpha = LISTEN_ALPHA
                self._set_window_alpha(LISTEN_ALPHA)
        elif self._state == "listening":
            k = (now - self._t0) % 3.2
            breath = 0.86 + 0.14 * math.sin(k * 2.0)
            self._set_window_alpha(self._target_alpha * breath)
        elif self._state == "thinking":
            k = (now - self._t0) % 1.1
            self._set_window_alpha(self._target_alpha *
                                   (0.72 + 0.28 * abs(math.sin(k * math.pi * 3.2))))

        self._schedule(16)

    # ── Fade out ────────────────────────────────────────────────────────────
    def _fade_out(self):
        start = time.monotonic()
        base = self._target_alpha
        try:
            base = float(self._win.attributes("-alpha"))
        except Exception:
            pass

        def step():
            if self._win is None:
                return
            now = time.monotonic()
            k = min(1.0, (now - start) / 0.55)
            try:
                self._win.attributes("-alpha", max(0.0, base * (1.0 - k)))
            except Exception:
                pass
            if k >= 1.0:
                self._destroy()
                return
            try:
                self.root.after(20, step)
            except Exception:
                self._destroy()

        try:
            self.root.after(0, step)
        except Exception:
            self._destroy()

    # ── Error handling ──────────────────────────────────────────────────────
    def _fail(self, exc):
        if self._on_error:
            try:
                self._on_error(exc)
            except Exception:
                pass


# ── Module level API (as required by the specification) ─────────────────────
_effect = None


def configure(root, dispatch=None, on_error=None):
    """Create the global effect instance (call once, on the Tk thread)."""
    global _effect
    _effect = ScreenEdgeEffect(root, dispatch=dispatch, on_error=on_error)
    return _effect


def get_effect():
    return _effect


def show_activation_effect():
    if _effect is not None:
        _effect.show_activation_effect()


def set_listening_effect():
    if _effect is not None:
        _effect.set_listening_effect()


def set_thinking_effect():
    if _effect is not None:
        _effect.set_thinking_effect()


def hide_activation_effect():
    if _effect is not None:
        _effect.hide_activation_effect()

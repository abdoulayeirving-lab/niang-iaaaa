import os, json, time, math, random, threading
import tkinter as tk
from tkinter import filedialog, messagebox
from collections import deque
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageOps
import tkinter.font as tkfont
import sys
from i18n import tr
from pathlib import Path
from vision.arcade import VisionArcade
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR   = get_base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"
INSTALLER_API_KEY_FILE = CONFIG_DIR / "installer_gemini_key.txt"
THEME_FILE = CONFIG_DIR / "ui_theme.json"

SYSTEM_NAME = "NIANG IA"
INTRO_END   = 5.8      # seconds: end of the startup animation (click / key skips it)
MODEL_BADGE = "NIANG IA"

# ── High-DPI awareness: crisp text on 125% / 150% laptop scaling ───────────
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ── Themes ──────────────────────────────────────────────────────────────────
# Each theme: UI colors + RGB tuples for the orb / halos.
THEMES = {
    # Palette taken from the "NIANG IA – Pub 30 s" video (cyan HUD on black,
    # glass panels rgba(0,229,255,.07), magenta chromatic glitch).
    "cyber": {
        "name": "CYBER",
        "bg": "#000000", "pri": "#00e5ff", "mid": "#0098ab",
        "dim": "#0a3a44", "dimmer": "#03161c",
        "acc": "#ff2bd6", "acc2": "#7df3ff",
        "text": "#eaffff", "panel": "#021b23",
        "green": "#00ff9c", "red": "#ff3b55", "mutcol": "#ff3b55",
        "hdr": "#000000", "input": "#03252e", "inp_border": "#0a6a78",
        "halo": (0, 229, 255), "halo_mut": (255, 59, 85),
        "orb": (0, 229, 255), "scan2": (255, 43, 214),
    },
    "ocean": {
        "name": "OCEAN",
        "bg": "#01060f", "pri": "#38bdf8", "mid": "#0e7490",
        "dim": "#0a3a55", "dimmer": "#031a2e",
        "acc": "#f97316", "acc2": "#fde047",
        "text": "#bae6fd", "panel": "#02101c",
        "green": "#4ade80", "red": "#f87171", "mutcol": "#fb7185",
        "hdr": "#020b16", "input": "#02111f", "inp_border": "#0a3a55",
        "halo": (56, 189, 248), "halo_mut": (251, 113, 133),
        "orb": (7, 89, 133), "scan2": (251, 146, 60),
    },
    "aurora": {
        "name": "AURORA",
        "bg": "#010b07", "pri": "#4ade80", "mid": "#16a34a",
        "dim": "#0b4f2c", "dimmer": "#032316",
        "acc": "#facc15", "acc2": "#fde047",
        "text": "#bbf7d0", "panel": "#02150c",
        "green": "#4ade80", "red": "#f87171", "mutcol": "#fb7185",
        "hdr": "#02130a", "input": "#02170d", "inp_border": "#0b4f2c",
        "halo": (74, 222, 128), "halo_mut": (244, 63, 94),
        "orb": (5, 80, 45), "scan2": (250, 204, 21),
    },
    "sunset": {
        "name": "SUNSET",
        "bg": "#0d0306", "pri": "#fb923c", "mid": "#9a3412",
        "dim": "#5b1e0b", "dimmer": "#2a0d06",
        "acc": "#f472b6", "acc2": "#fde047",
        "text": "#fed7aa", "panel": "#17070a",
        "green": "#4ade80", "red": "#f87171", "mutcol": "#fb7185",
        "hdr": "#15080a", "input": "#1c0a0c", "inp_border": "#5b1e0b",
        "halo": (251, 146, 60), "halo_mut": (251, 113, 133),
        "orb": (120, 45, 20), "scan2": (253, 224, 71),
    },
}


def _load_theme_name() -> str:
    try:
        if THEME_FILE.exists():
            data = json.loads(THEME_FILE.read_text(encoding="utf-8"))
            name = str(data.get("theme", "cyber")).strip()
            if name in THEMES:
                return name
    except Exception:
        pass
    return "cyber"


def _save_theme_name(name: str) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        THEME_FILE.write_text(json.dumps({"theme": name}, indent=2),
                              encoding="utf-8")
    except Exception:
        pass


# ── Drawing helpers (video look: glass panels, rounded "pill" buttons) ──────
def _hex_rgb(h):
    if isinstance(h, (tuple, list)):          # theme "halo"/"scan2" are RGB tuples
        return tuple(int(v) for v in h[:3])
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _blend(c1, c2, k):
    """Mix two #rrggbb colours (k=0 → c1, k=1 → c2). Poor man's alpha for Tk."""
    k = max(0.0, min(1.0, k))
    a, b = _hex_rgb(c1), _hex_rgb(c2)
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


def _round_poly(c, x1, y1, x2, y2, r, **kw):
    r = max(1, min(r, (x2 - x1) // 2, (y2 - y1) // 2))
    pts = [x1 + r, y1, x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y1 + r, x2, y2 - r, x2, y2 - r, x2, y2, x2 - r, y2, x2 - r, y2,
           x1 + r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y2 - r, x1, y1 + r,
           x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


class PillButton(tk.Canvas):
    """Rounded glass button like the cards / CTA of the video.

    style="outline": translucent cyan fill + cyan border (hover → brighter)
    style="solid"  : filled cyan pill with dark text (the "Essayez NIANG IA" CTA)
    Colours always come from the live theme (app.col) so theme switching works.
    API is a subset of tk.Button: configure(text=, state=, command=).
    """
    _IGNORED = {"fg", "foreground", "bg", "background", "activebackground",
                "activeforeground", "highlightbackground", "highlightcolor",
                "relief", "borderwidth", "bd"}

    def __init__(self, parent, app, text="", command=None, style="outline",
                 anchor="center", font=("Segoe UI", 9, "bold"), height=30,
                 radius=None, width=10):
        tk.Canvas.__init__(self, parent, height=height, width=width,
                           highlightthickness=0, bd=0, cursor="hand2")
        self._app = app
        self._text = text
        self._command = command
        self._style = style
        self._anchor = anchor
        self._font = font
        self._radius = radius
        self._state = "normal"
        self._hover = False
        self.bind("<Configure>", lambda e: self._redraw())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonRelease-1>", self._on_click)
        self._redraw()

    def configure(self, cnf=None, **kw):
        if cnf:
            kw.update(cnf)
        if "text" in kw:
            self._text = kw.pop("text")
        if "command" in kw:
            self._command = kw.pop("command")
        if "state" in kw:
            self._state = kw.pop("state")
            tk.Canvas.configure(self, cursor="hand2" if self._state != "disabled" else "arrow")
        for k in list(kw):
            if k in self._IGNORED:
                kw.pop(k)
        if kw:
            tk.Canvas.configure(self, **kw)
        self._redraw()

    config = configure

    def refresh(self):
        self._redraw()

    def _on_enter(self, _e=None):
        self._hover = True
        self._redraw()

    def _on_leave(self, _e=None):
        self._hover = False
        self._redraw()

    def _on_click(self, e):
        if self._state == "disabled" or not self._command:
            return
        if 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self._command()

    def _redraw(self):
        try:
            if not self.winfo_exists():
                return
            col = self._app.col
            w = max(self.winfo_width(), 24)
            h = max(self.winfo_height(), 16)
            try:
                parent_bg = self.master.cget("bg")
            except Exception:
                parent_bg = col["bg"]
            tk.Canvas.configure(self, bg=parent_bg)
            self.delete("all")
            hov = self._hover and self._state != "disabled"
            if self._state == "disabled":
                fill, border, fg = col["panel"], col["dim"], col["dim"]
            elif self._style == "solid":
                fill = col["text"] if hov else col["pri"]
                border, fg = fill, "#001a20"
            elif self._style == "danger":
                danger = col.get("mutcol", "#ff3b55")
                fill = _blend(col["input"], danger, .30) if hov else col["input"]
                border = danger if hov else _blend(col["mid"], danger, .55)
                fg = "#ffffff" if hov else danger
            else:
                fill = _blend(col["input"], col["pri"], .22) if hov else col["input"]
                border = col["pri"] if hov else col["mid"]
                fg = "#ffffff" if hov else col["text"]
            r = self._radius if self._radius is not None else h // 2
            _round_poly(self, 1, 1, w - 1, h - 1, r, fill=fill, outline=border, width=1)
            if self._anchor == "w":
                self.create_text(min(r, 14) + 6, h // 2, text=self._text, fill=fg,
                                 font=self._font, anchor="w")
            else:
                self.create_text(w // 2, h // 2, text=self._text, fill=fg,
                                 font=self._font)
        except tk.TclError:
            pass


class KaizumiUI:
    def __init__(self, face_path, size=None):
        self.root = TkinterDnD.Tk() if TkinterDnD else tk.Tk()
        self.root.title("NIANG IA")
        self.root.resizable(True, True)

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        W  = min(sw, 1000)
        H  = min(sh, 840)
        if sw < 1100 or sh < 760:
            W = min(max(sw - 40, 720), 980)
            H = min(max(sh - 60, 560), 820)
        self.root.geometry(f"{W}x{H}+{(sw-W)//2}+{(sh-H)//2}")
        self.root.configure(bg="#000000")
        self.root.minsize(520, 420)

        self.W = W
        self.H = H

        # DPI-scaled fonts: crisp on high-DPI laptop displays
        try:
            dpi = self.root.winfo_fpixels("1i")
            self.root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass

        self.FACE_SZ = min(int(H * 0.40), 360)
        self.FCX     = W // 2
        self.FCY     = int(H * 0.11) + self.FACE_SZ // 2

        # ── State ────────────────────────────────────────────────────────────
        self.speaking     = False
        self.muted        = False          # Mute flag — main.py reads it
        self._mic_listening = False        # permanent mic indicator (wake word)
        self._mic_level   = None           # live mic RMS 0..1 from the listener
        self._base_alpha  = 1.0            # 1.0 = opaque, < 1.0 = semi-transparent
        self.silent_mode  = False          # Text-only mode: keep transcript, suppress TTS
        self.scale        = 1.0
        self.target_scale = 1.0
        self.halo_a       = 60.0
        self.target_halo  = 60.0
        self.last_t       = time.time()
        self.tick         = 0
        self.scan_angle   = 0.0
        self.scan2_angle  = 180.0
        self.rings_spin   = [0.0, 120.0, 240.0]
        self.pulse_r      = [0.0, self.FACE_SZ * 0.26, self.FACE_SZ * 0.52]
        self.status_text  = "INITIALISATION"
        self.status_blink = True

        self._state = "INITIALISING"

        # Video-style HUD state (ring phases, particles, waveform level)
        self._t_start   = time.time()
        self._intro_done = False
        self._prev_now  = self._t_start
        self._ph_arc    = 0.0
        self._ph_dash   = 0.0
        self._ph_tick   = 0.0
        self._lv        = 0.15
        self._bd_key    = None
        self._bd_tk     = None
        self._font_cache = {}
        self._cache_keys = {}
        rng = random.Random(7)
        self._particles = [
            {"a": rng.random() * math.tau, "far": 600 + rng.random() * 900,
             "off": (i % 4) * 16, "sp": (.05 + rng.random() * .15) * (1 if i % 2 else -1),
             "s": 1 + rng.random() * 2.2}
            for i in range(110)
        ]

        self.typing_queue = deque()
        self.is_typing    = False
        self._ui_deferred = deque()
        self._main_thread = threading.current_thread()

        # Persona / connection info (updated by main.py)
        self.persona_mode  = "normal"
        self.persona_mood  = "calm"
        self.persona_voice = "Aoede"
        self.connected     = False
        self.connecting    = False
        self.last_event    = ""
        self._batt_cache   = None
        self._batt_ts      = 0.0

        self.on_text_command = None
        self.on_agent_start = None
        self.on_agent_cancel = None
        self.on_application_close = None
        self._agent_window = None
        self._agent_task_id = None
        self._agent_history_task_id = None
        self._agent_history_count = 0
        self._agent_screenshot_path = None
        self._agent_screenshot_image = None
        self._agent_refresh_after = None
        self._diagnostics_window = None
        self._diagnostics_output = None
        self._diagnostics_status = None
        self._diagnostics_busy = False
        self._diagnostics_cancel_event = None
        self._diagnostics_last_report = None
        self._diagnostics_buttons = []
        self._diagnostics_stop_button = None
        self.on_files_selected = None
        self.on_clear_documents = None
        self.on_voiceover_requested = None
        self._selected_paths = []
        self._file_row_widgets = []
        self._drop_leave_after = None
        self._drop_pulse_after = None
        self._drop_pulse_index = 0
        self._drop_hud_visible = False
        self._voiceover_path = None
        self._voiceover_alias_open = False
        self._voiceover_window = None
        self._analysis_report = ""
        self._update_check_in_progress = False
        self.on_whatsapp_call_control = None
        self.vision_mode = "STANDBY"
        self.vision_signal = "En attente de la caméra"
        self.live_camera_active = False
        self.whatsapp_call_status = "DÉSACTIVÉ — appel manuel"
        self.vision_preview_open = False
        self._preview_window = None
        self._preview_label = None
        self._preview_image = None
        self.arcade_open = False
        self._arcade_window = None
        self._arcade_label = None
        self._arcade_image = None
        self._arcade = VisionArcade()
        self._deck_buttons = []

        self._theme = _load_theme_name()
        self.col    = dict(THEMES[self._theme])
        self.root.configure(bg=self.col["bg"])

        self._face_pil         = None
        self._has_face         = False
        self._face_scale_cache = None
        self._load_face(face_path)

        # ── Canvas (background animation) ────────────────────────────────────
        self.bg = tk.Canvas(self.root, width=W, height=H,
                            bg=self.col["bg"], highlightthickness=0)
        self.bg.place(x=0, y=0)
        # ── Drag the holographic sphere with the mouse ───────────────────────
        self._drag_active = False
        self._drag_off = (0, 0)
        self.bg.bind("<ButtonPress-1>", self._on_orb_press)
        self.bg.bind("<B1-Motion>", self._on_orb_drag)
        self.bg.bind("<ButtonRelease-1>", self._on_orb_release)

        # ── JARVIS command deck ────────────────────────────────────────────
        # This is intentionally built from native Tk widgets so it remains
        # lightweight and works together with the existing animated canvas.
        self._build_command_deck()
        self._build_file_drop_area()

        # ── Log area ─────────────────────────────────────────────────────────
        LW = max(320, W - 440) if W >= 900 else int(W * 0.72)
        LH = int(H * 0.11)
        LOG_Y = H - LH - int(H * 0.13)
        self.log_frame = tk.Frame(self.root, bg=self.col["panel"],
                                  highlightbackground=self.col["mid"],
                                  highlightthickness=1)
        self.log_frame.place(x=(W - LW) // 2, y=LOG_Y, width=LW, height=LH)
        self.log_text = tk.Text(self.log_frame, fg=self.col["text"],
                                bg=self.col["panel"],
                                insertbackground=self.col["text"], borderwidth=0,
                                wrap="word", font=("Segoe UI", 10), padx=10, pady=6,
                                highlightthickness=0)
        self.log_text.pack(fill="both", expand=True)
        self.log_text.configure(state="disabled")
        self._style_log_tags()

        # ── Keyboard input ────────────────────────────────────────────────────
        # Keep the footer controls below the input even on compact windows.
        INPUT_Y = min(LOG_Y + LH + 6, H - 112)
        self._build_input_bar(LW, INPUT_Y)

        # ── Mute button ───────────────────────────────────────────────────────
        self._build_mute_button()

        # ── Hotkeys ───────────────────────────────────────────────────────────
        self.root.bind("<F4>", lambda e: self._toggle_mute())
        self.root.bind("<F6>", lambda e: self._toggle_silent_mode())
        self.root.bind("<F5>", lambda e: self.cycle_theme())
        self.root.bind("<Control-o>", self._open_file_dialog)
        self.root.bind("<Control-Shift-v>", self._open_voiceover)
        self.root.bind("<Control-Shift-s>", self._export_analysis_report)
        self._input_text.bind("<Control-Button-1>", self._open_file_dialog)
        if DND_FILES:
            drop_targets = [self.root]
            pending = list(self.root.winfo_children())
            while pending:
                target = pending.pop()
                drop_targets.append(target)
                pending.extend(target.winfo_children())
            for target in drop_targets:
                target.drop_target_register(DND_FILES)
                target.dnd_bind("<<DropEnter>>", self._on_drop_enter)
                target.dnd_bind("<<DropLeave>>", self._on_drop_leave)
                target.dnd_bind("<<Drop>>", self._on_drop)

        # Re-layout widgets when the window is resized
        self.root.bind("<Configure>", self._on_configure)
        self.root.bind("<Button-1>", self._finish_intro, add="+")
        self.root.bind("<Key>", self._finish_intro, add="+")
        self._hide_main_widgets()      # revealed when the startup animation ends
        self._relayout()
        self.write_log(
            "SYS: Fichier : Ctrl+O · voix off : Ctrl+Maj+V · exporter le rapport : Ctrl+Maj+S."
        )

        # ── API key ───────────────────────────────────────────────────────────
        self._api_key_ready = self._api_keys_exist()
        if not self._api_key_ready:
            self._show_setup_ui()

        self._animate()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)

    # ── Theme ────────────────────────────────────────────────────────────────

    def set_theme(self, name: str):
        if name not in THEMES:
            return
        self._theme = name
        self.col    = dict(THEMES[name])
        _save_theme_name(name)
        self._safe_ui(self._apply_theme_ui)

    def cycle_theme(self):
        names = list(THEMES.keys())
        idx   = names.index(self._theme)
        self.set_theme(names[(idx + 1) % len(names)])
        self.write_log(f"SYS: Theme → {THEMES[self._theme]['name']}.")

    def _style_log_tags(self):
        """Chat 'bubbles' of the video: small cyan label (VOUS / NIANG IA) + light text."""
        t = self.log_text
        t.tag_config("you", foreground=self.col["text"])
        t.tag_config("ai",  foreground=self.col["text"])
        t.tag_config("sys", foreground=self.col["acc2"])
        t.tag_config("err", foreground=self.col["red"])
        t.tag_config("lbl_you", foreground=self.col["acc2"], font=("Segoe UI", 8, "bold"))
        t.tag_config("lbl_ai",  foreground=self.col["pri"],  font=("Segoe UI", 8, "bold"))

    def _apply_theme_ui(self):
        self.root.configure(bg=self.col["bg"])
        self.bg.configure(bg=self.col["bg"])
        self.log_frame.configure(bg=self.col["panel"],
                                 highlightbackground=self.col["mid"])
        self.log_text.configure(fg=self.col["text"], bg=self.col["panel"])
        self._style_log_tags()
        self._file_card.configure(bg=self.col["panel"], highlightbackground=self.col["mid"])
        self._file_rows.configure(bg=self.col["panel"])
        self._file_progress.configure(bg=self.col["panel"])
        self._drop_overlay.configure(bg=self.col["panel"], highlightbackground=self.col["pri"])
        self._drop_icon.configure(bg=self.col["panel"], fg=self.col["pri"])
        self._drop_label.configure(bg=self.col["panel"], fg=self.col["pri"])
        if self._selected_paths:
            self._refresh_file_card()
        self._draw_mute_button()
        self._update_button.refresh()
        self._draw_silent_button()
        self._refresh_input_style()
        self._apply_deck_theme()

    def _refresh_input_style(self):
        try:
            self._input_text.configure(fg=self.col["text"],
                                       bg=self.col["input"],
                                       insertbackground=self.col["text"],
                                       highlightbackground=self.col["inp_border"],
                                       highlightcolor=self.col["pri"])
            self._clear_btn.refresh()
            self._send_btn.refresh()
        except Exception:
            pass

    def _build_command_deck(self):
        """Build the live control surface around the central Kaizumi core."""
        self._left_deck = tk.Frame(self.root, bg=self.col["panel"],
                                   highlightbackground=self.col["mid"], highlightthickness=1)
        self._right_deck = tk.Frame(self.root, bg=self.col["panel"],
                                    highlightbackground=self.col["mid"], highlightthickness=1)
        self._deck_title(self._left_deck, "COMMANDES", self.col["pri"])
        self._deck_title(self._right_deck, "VISION", self.col["acc2"])

        self._deck_label(self._left_deck, "ACTIONS RAPIDES")
        self._deck_button(self._left_deck, "AGENT AUTONOME", "__open_agent__")
        self._deck_button(self._left_deck, "DIAGNOSTIC DU PC", "__open_pc_diagnostics__")
        self._deck_button(self._left_deck, "JEUX DE VISION", "__open_arcade__")
        for label, command in [
            ("RÉSUMÉ DU JOUR", "give me my daily briefing"),
            ("ÉTAT DU SYSTÈME", "show system status"),
            (
                "DÉCRIRE L’ÉCRAN",
                "look at my screen and describe the windows, icons, buttons, images, and everything visible",
            ),
            ("MODE CONCENTRATION", "start focus mode"),
        ]:
            self._deck_button(self._left_deck, label, command)
        self._deck_label(self._left_deck, "APPEL WHATSAPP IA (MANUEL)")
        self._whatsapp_call_status_label = tk.Label(
            self._left_deck,
            text=self.whatsapp_call_status,
            anchor="w",
            justify="left",
            wraplength=170,
            bg=self.col["panel"],
            fg=self.col["dim"],
            font=("Consolas", 8, "bold"),
        )
        self._whatsapp_call_status_label.pack(fill="x", padx=12, pady=(0, 6))
        for label, action in [
            ("COUPER LE SON DE L’IA", "mute"),
            ("RÉACTIVER LE SON DE L’IA", "resume"),
            ("ARRÊTER LE SON DE L’IA", "stop"),
        ]:
            self._call_deck_button(self._left_deck, label, action)

        self._deck_label(self._right_deck, "CONTRÔLE DE LA CAMÉRA")
        self._deck_button(self._right_deck, "APERÇU DE LA CAMÉRA", "__open_preview__")
        for label, mode in [("CONTRÔLE PAR GESTES", "gesture"), ("DÉTECTION D’OBJETS", "objects"),
                            ("SOURIS GESTUELLE", "air_mouse"),
                            ("VOLUME PAR GESTES", "volume"), ("POSTURE", "posture"),
                            ("SUIVI DES MOUVEMENTS", "motion")]:
            self._deck_button(self._right_deck, label, f"start vision {mode}", mode)
        self._deck_button(self._right_deck, "DÉMARRER L’ENREGISTREMENT", "__record_start__")
        self._deck_button(self._right_deck, "ARRÊTER L’ENREGISTREMENT", "__record_stop__")
        self._deck_button(self._right_deck, "ARRÊTER LA VISION", "stop vision", "STANDBY")
        self._deck_label(self._right_deck, "ANALYSES PONCTUELLES")
        for label, command in [("CAPTURER UNE IMAGE", "take a camera snapshot"),
                                ("COMPTER LES VISAGES", "count faces in front of the camera"),
                                ("LIRE UN CODE QR", "read a QR code with the camera"),
                                ("LIRE LE TEXTE", "read text with the camera"),
                                ("SUPPRIMER L’ARRIÈRE-PLAN", "remove the background from the camera subject"),
                                ("DÉCRIRE LA SCÈNE", "describe everything visible to the camera")]:
            self._deck_button(self._right_deck, label, command)
        self._vision_status = tk.Label(self._right_deck, text="● VEILLE", anchor="w",
                                       bg=self.col["panel"], fg=self.col["green"],
                                       font=("Consolas", 9, "bold"))
        self._vision_status.pack(fill="x", padx=12, pady=(10, 8))
        self._live_camera_status = tk.Label(
            self._right_deck,
            text="● CAMÉRA EN DIRECT : NON",
            anchor="w",
            bg=self.col["panel"],
            fg=self.col["dim"],
            font=("Consolas", 9, "bold"),
        )
        self._live_camera_status.pack(fill="x", padx=12, pady=(0, 8))
        self._deck_label(self._right_deck, "MODULES DE VISION LOCALE")
        for text in ("REPÉRAGE DES MAINS   PRÊT", "ANALYSE DE LA POSTURE   PRÊTE", "SCAN QR / VISAGE   PRÊT"):
            self._deck_label(self._right_deck, text, compact=True)
        self._vision_signal_label = tk.Label(self._right_deck, text=self.vision_signal,
                                              anchor="w", justify="left", wraplength=170,
                                              bg=self.col["panel"], fg=self.col["text"],
                                              font=("Consolas", 8))
        self._vision_signal_label.pack(fill="x", padx=12, pady=(10, 12))

    def _deck_title(self, parent, text, color):
        tk.Label(parent, text=text, anchor="w", bg=self.col["panel"], fg=color,
                 font=("Segoe UI", 10, "bold")).pack(fill="x", padx=12, pady=(12, 8))

    def _deck_label(self, parent, text, compact=False):
        tk.Label(parent, text=text, anchor="w", bg=self.col["panel"], fg=self.col["dim"],
                 font=("Consolas", 8 if compact else 8, "bold")).pack(fill="x", padx=12,
                 pady=(5 if compact else 10, 3))

    def _deck_button(self, parent, text, command, mode=None):
        btn = PillButton(parent, self, text="▸  " + tr(text), anchor="w",
                         command=lambda: self._deck_command(command, mode),
                         font=("Segoe UI", 8, "bold"), height=30, radius=10)
        btn.pack(fill="x", padx=10, pady=3)
        self._deck_buttons.append(btn)

    def _call_deck_button(self, parent, text, command):
        btn = PillButton(parent, self, text="▸  " + tr(text), anchor="w",
                         command=lambda: self._call_deck_command(command),
                         font=("Segoe UI", 8, "bold"), height=30, radius=10)
        btn.pack(fill="x", padx=10, pady=3)
        self._deck_buttons.append(btn)

    def _call_deck_command(self, command):
        self.write_log("SYS: Commande de contrôle de l’appel WhatsApp IA demandée.")
        if command in {"mute", "stop"} and self.on_whatsapp_call_control:
            threading.Thread(
                target=self.on_whatsapp_call_control,
                args=(command,),
                daemon=True,
            ).start()
            return
        if command == "resume":
            command = "resume WhatsApp call audio"
        if self.on_text_command:
            threading.Thread(
                target=self.on_text_command,
                args=(command,),
                daemon=True,
            ).start()

    def _deck_command(self, command, mode=None):
        if command == "__open_agent__":
            self.open_agent_panel()
            return
        if command == "__open_pc_diagnostics__":
            self.open_pc_diagnostics_panel()
            return
        if command == "__open_preview__":
            self.open_vision_preview()
            return
        if command == "__open_arcade__":
            self.open_vision_arcade()
            return
        if command in ("__record_start__", "__record_stop__"):
            self.write_log(
                "SYS: " + (
                    "Démarrage de l’enregistrement demandé."
                    if command == "__record_start__"
                    else "Arrêt de l’enregistrement demandé."
                )
            )
            if self.on_text_command:
                text = "start recording" if command == "__record_start__" else "stop recording"
                threading.Thread(target=self.on_text_command, args=(text,), daemon=True).start()
            return
        self.vision_mode = (mode or self.vision_mode).upper()
        self._safe_ui(self._refresh_deck_status)
        command_labels = {
            "give me my daily briefing": "Résumé du jour",
            "show system status": "État du système",
            "look at my screen and describe the windows, icons, buttons, images, and everything visible": "Décrire l’écran",
            "start focus mode": "Mode concentration",
            "mute": "Couper le son de l’IA",
            "resume": "Réactiver le son de l’IA",
            "resume WhatsApp call audio": "Réactiver le son de l’appel WhatsApp",
            "stop": "Arrêter le son de l’IA",
            "stop vision": "Arrêter la vision",
            "start vision gesture": "Démarrer le contrôle par gestes",
            "start vision objects": "Démarrer la détection d’objets",
            "start vision air_mouse": "Démarrer la souris gestuelle",
            "start vision volume": "Démarrer le contrôle du volume par gestes",
            "start vision posture": "Démarrer l’analyse de la posture",
            "start vision motion": "Démarrer le suivi des mouvements",
            "take a camera snapshot": "Capturer une image",
            "count faces in front of the camera": "Compter les visages",
            "read a QR code with the camera": "Lire un code QR",
            "read text with the camera": "Lire le texte",
            "remove the background from the camera subject": "Supprimer l’arrière-plan",
            "describe everything visible to the camera": "Décrire la scène",
        }
        self.write_log("SYS: Commande sélectionnée : " + command_labels.get(command, self._translate_status(command)))
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(command,), daemon=True).start()

    def open_agent_panel(self):
        if self._agent_window is not None and self._agent_window.winfo_exists():
            self._agent_window.deiconify()
            self._agent_window.lift()
            self._refresh_agent_panel()
            return

        window = tk.Toplevel(self.root)
        window.title("NIANG IA — Agent autonome")
        window.geometry("760x700")
        window.minsize(620, 560)
        window.configure(bg=self.col["bg"])
        self._agent_window = window

        tk.Label(
            window,
            text="VOTRE MISSION",
            anchor="w",
            bg=self.col["bg"],
            fg=self.col["pri"],
            font=("Consolas", 10, "bold"),
        ).pack(fill="x", padx=12, pady=(12, 4))
        self._agent_mission = tk.Text(
            window,
            height=3,
            wrap="word",
            bg=self.col["input"],
            fg=self.col["text"],
            insertbackground=self.col["text"],
            relief="flat",
        )
        self._agent_mission.pack(fill="x", padx=12)

        controls = tk.Frame(window, bg=self.col["bg"])
        controls.pack(fill="x", padx=12, pady=8)
        self._agent_start_button = tk.Button(
            controls,
            text=tr("▶ DÉMARRER"),
            command=self._start_agent_mission,
            bg=self.col["input"],
            fg=self.col["green"],
            relief="flat",
        )
        self._agent_start_button.pack(side="left", padx=(0, 6))
        self._agent_stop_button = tk.Button(
            controls,
            text=tr("■ ARRÊTER"),
            command=self._stop_agent_mission,
            bg=self.col["input"],
            fg=self.col["red"],
            relief="flat",
            state="disabled",
        )
        self._agent_stop_button.pack(side="left")
        self._agent_resume_button = tk.Button(
            controls,
            text=tr("↻ REPRENDRE"),
            command=self._resume_agent_mission,
            bg=self.col["input"],
            fg=self.col["pri"],
            relief="flat",
            state="disabled",
        )
        self._agent_resume_button.pack(side="left", padx=(6, 0))
        self._agent_status_label = tk.Label(
            controls,
            text="Inactif",
            anchor="w",
            bg=self.col["bg"],
            fg=self.col["text"],
            font=("Consolas", 9),
        )
        self._agent_status_label.pack(side="left", fill="x", expand=True, padx=10)

        tk.Label(
            window,
            text="ÉTAPES ET ACTIONS (le navigateur Playwright MCP s’ouvre dans sa propre fenêtre)",
            anchor="w",
            bg=self.col["bg"],
            fg=self.col["pri"],
            font=("Consolas", 9, "bold"),
        ).pack(fill="x", padx=12, pady=(4, 3))
        self._agent_history_text = tk.Text(
            window,
            height=18,
            wrap="word",
            state="disabled",
            bg=self.col["panel"],
            fg=self.col["text"],
            relief="flat",
        )
        self._agent_history_text.pack(fill="both", expand=True, padx=12)
        self._agent_screenshot_label = tk.Label(
            window,
            text="Aucune capture d’écran",
            bg=self.col["panel"],
            fg=self.col["dim"],
        )
        self._agent_screenshot_label.pack(fill="x", padx=12, pady=5)
        screenshot_controls = tk.Frame(window, bg=self.col["bg"])
        screenshot_controls.pack(fill="x", padx=12, pady=(0, 8))
        tk.Button(
            screenshot_controls,
            text=tr("OUVRIR LA CAPTURE"),
            command=self._open_agent_screenshot,
            bg=self.col["input"],
            fg=self.col["text"],
            relief="flat",
        ).pack(side="left")

        tk.Label(
            window,
            text="RAPPORT FINAL",
            anchor="w",
            bg=self.col["bg"],
            fg=self.col["pri"],
            font=("Consolas", 9, "bold"),
        ).pack(fill="x", padx=12, pady=(4, 3))
        self._agent_report_text = tk.Text(
            window,
            height=5,
            wrap="word",
            state="disabled",
            bg=self.col["panel"],
            fg=self.col["text"],
            relief="flat",
        )
        self._agent_report_text.pack(fill="x", padx=12, pady=(0, 12))

        def close_panel():
            if self._agent_refresh_after is not None:
                try:
                    self.root.after_cancel(self._agent_refresh_after)
                except tk.TclError:
                    pass
                self._agent_refresh_after = None
            self._agent_window = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_panel)
        self._refresh_agent_panel()

    def open_pc_diagnostics_panel(self):
        if self._diagnostics_window is not None and self._diagnostics_window.winfo_exists():
            self._diagnostics_window.deiconify()
            self._diagnostics_window.lift()
            return

        window = tk.Toplevel(self.root)
        window.title("NIANG IA — Diagnostic du PC")
        window.geometry("860x720")
        window.minsize(680, 560)
        window.configure(bg=self.col["bg"])
        self._diagnostics_window = window

        tk.Label(
            window,
            text="DIAGNOSTIC DU PC",
            anchor="w",
            bg=self.col["bg"],
            fg=self.col["pri"],
            font=("Consolas", 12, "bold"),
        ).pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(
            window,
            text=(
                "Les analyses ne réparent pas Windows et ne touchent pas aux fichiers personnels. "
                "SFC/DISM peuvent écrire dans leurs journaux Windows. Les réparations exigent "
                "une confirmation et ne contournent jamais l’UAC."
            ),
            anchor="w",
            justify="left",
            wraplength=820,
            bg=self.col["bg"],
            fg=self.col["dim"],
            font=("Consolas", 9),
        ).pack(fill="x", padx=12, pady=(0, 8))

        actions_frame = tk.Frame(window, bg=self.col["bg"])
        actions_frame.pack(fill="x", padx=12)
        actions = [
            ("Analyser mon PC", "overview"),
            ("Vérifier les pilotes", "drivers"),
            ("Vérifier Windows", "windows"),
            ("Diagnostiquer les performances", "performance"),
            ("Détecter les erreurs", "errors"),
            ("Vérifier le réseau", "network"),
            ("Vérifier les services", "services"),
            ("Vérifier les fichiers système", "system_files"),
        ]
        self._diagnostics_buttons = []
        for index, (label, category) in enumerate(actions):
            button = tk.Button(
                actions_frame,
                text=tr(label),
                command=lambda selected=category: self._start_pc_diagnostic(selected),
                bg=self.col["input"],
                fg=self.col["text"],
                relief="flat",
                wraplength=190,
            )
            button.grid(row=index // 4, column=index % 4, sticky="ew", padx=3, pady=3)
            self._diagnostics_buttons.append(button)
        for column in range(4):
            actions_frame.grid_columnconfigure(column, weight=1)

        controls = tk.Frame(window, bg=self.col["bg"])
        controls.pack(fill="x", padx=12, pady=(5, 8))
        tk.Button(
            controls,
            text=tr("Proposer des réparations"),
            command=self._show_pc_repair_options,
            bg=self.col["input"],
            fg=self.col["acc2"],
            relief="flat",
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            controls,
            text=tr("Historique des diagnostics"),
            command=self._show_pc_diagnostic_history,
            bg=self.col["input"],
            fg=self.col["text"],
            relief="flat",
        ).pack(side="left")
        tk.Button(
            controls,
            text=tr("Historique des réparations"),
            command=self._show_pc_repair_history,
            bg=self.col["input"],
            fg=self.col["acc2"],
            relief="flat",
        ).pack(side="left", padx=(6, 0))
        self._diagnostics_stop_button = tk.Button(
            controls,
            text=tr("Arrêter"),
            command=self._stop_pc_diagnostic,
            bg=self.col["input"],
            fg=self.col["red"],
            relief="flat",
            state="disabled",
        )
        self._diagnostics_stop_button.pack(side="right")

        repair_frame = tk.Frame(window, bg=self.col["panel"])
        repair_frame.pack(fill="x", padx=12, pady=(0, 8))
        tk.Label(
            repair_frame,
            text="RÉPARATIONS DISPONIBLES — chaque action demande une confirmation",
            anchor="w",
            bg=self.col["panel"],
            fg=self.col["acc2"],
            font=("Consolas", 9, "bold"),
        ).pack(fill="x", padx=8, pady=(6, 3))
        for label, action in (
            ("Vider le cache DNS", "flush_dns"),
            ("Réparer les fichiers système (SFC)", "sfc_scannow"),
            ("Réparer le magasin Windows (DISM)", "dism_restore_health"),
        ):
            button = tk.Button(
                repair_frame,
                text=tr(label),
                command=lambda selected=action: self._request_pc_repair(selected),
                bg=self.col["input"],
                fg=self.col["text"],
                relief="flat",
            )
            button.pack(side="left", padx=4, pady=(2, 6))
            self._diagnostics_buttons.append(button)

        self._diagnostics_status = tk.Label(
            window,
            text="Prêt — aucune analyse en cours.",
            anchor="w",
            bg=self.col["bg"],
            fg=self.col["text"],
            font=("Consolas", 9),
        )
        self._diagnostics_status.pack(fill="x", padx=12, pady=(0, 5))

        output_frame = tk.Frame(window, bg=self.col["panel"])
        output_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        output_scroll = tk.Scrollbar(output_frame)
        output_scroll.pack(side="right", fill="y")
        self._diagnostics_output = tk.Text(
            output_frame,
            wrap="word",
            state="disabled",
            bg=self.col["panel"],
            fg=self.col["text"],
            relief="flat",
            yscrollcommand=output_scroll.set,
        )
        self._diagnostics_output.pack(side="left", fill="both", expand=True)
        output_scroll.configure(command=self._diagnostics_output.yview)

        def close_panel():
            self._stop_pc_diagnostic()
            self._diagnostics_window = None
            self._diagnostics_output = None
            self._diagnostics_status = None
            self._diagnostics_stop_button = None
            self._diagnostics_buttons = []
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_panel)

    def _set_pc_diagnostics_output(self, text):
        output = self._diagnostics_output
        if output is None:
            return
        output.configure(state="normal")
        output.delete("1.0", "end")
        output.insert("1.0", text)
        output.configure(state="disabled")

    def _set_pc_diagnostics_busy(self, busy, status):
        self._diagnostics_busy = busy
        if self._diagnostics_status is not None:
            self._diagnostics_status.configure(text=status)
        for button in self._diagnostics_buttons:
            button.configure(state="disabled" if busy else "normal")
        if self._diagnostics_stop_button is not None:
            self._diagnostics_stop_button.configure(state="normal" if busy else "disabled")

    def _start_pc_diagnostic(self, category):
        if self._diagnostics_busy:
            return
        from actions.windows_diagnostics import run_diagnostic

        cancel_event = threading.Event()
        self._diagnostics_cancel_event = cancel_event
        category_label = {
            "overview": "générale",
            "drivers": "des pilotes",
            "windows": "de Windows",
            "performance": "des performances",
            "errors": "des erreurs",
            "network": "du réseau",
            "services": "des services",
            "system_files": "des fichiers système",
        }.get(category, category)
        self._set_pc_diagnostics_busy(True, f"Analyse {category_label} en cours…")
        self._set_pc_diagnostics_output("Collecte des résultats locaux…")

        def worker():
            try:
                report = run_diagnostic(category, cancel_event=cancel_event)
                text = json.dumps(report, ensure_ascii=False, indent=2)
                status = (
                    f"Analyse terminée — état : {report['status']}; "
                    f"{len(report['findings'])} problème(s) candidat(s)."
                )
                self.root.after(0, lambda: self._finish_pc_diagnostics(report, text, status))
            except Exception as exc:
                message = str(exc)
                self.root.after(0, lambda: self._finish_pc_diagnostics_error(message))

        threading.Thread(target=worker, name="NIANG-PC-Diagnostics", daemon=True).start()

    def _finish_pc_diagnostics(self, report, text, status):
        self._diagnostics_last_report = report
        self._diagnostics_cancel_event = None
        self._set_pc_diagnostics_busy(False, status)
        self._set_pc_diagnostics_output(text)

    def _finish_pc_diagnostics_error(self, message):
        self._diagnostics_cancel_event = None
        self._set_pc_diagnostics_busy(False, "Analyse interrompue ou en erreur.")
        self._set_pc_diagnostics_output(f"Analyse non terminée : {message}")

    def _stop_pc_diagnostic(self):
        event = self._diagnostics_cancel_event
        if event is not None:
            event.set()
            if self._diagnostics_status is not None:
                self._diagnostics_status.configure(
                    text="Arrêt demandé — une commande déjà lancée peut nécessiter un instant pour se fermer."
                )

    def _show_pc_repair_options(self):
        report = self._diagnostics_last_report
        if not report:
            messagebox.showinfo(
                "Proposer des réparations",
                "Lancez d’abord une analyse. Les résultats servent à déterminer si une réparation est appropriée.",
                parent=self._diagnostics_window,
            )
            return
        proposals = report.get("repair_proposals") or []
        summary = "\n".join(
            f"• {self._translate_status(item.get('severity', 'inconnu').upper())} — {item.get('problem', '')}\n"
            f"  Confiance : {item.get('confidence', 'suspicion')} "
            f"({item.get('confidence_score', 0)} / 100), récurrence : "
            f"{item.get('recurrence_count', 0)}\n"
            f"  Cause possible : {item.get('likely_cause', 'non déterminée')}\n"
            f"  Réparation proposée : {item.get('proposed_repair', 'aucune')}\n"
            f"  Risque : {item.get('risk', 'inconnu')}\n"
            f"  Autorisation individuelle obligatoire : oui"
            for item in proposals[:8]
        )
        if not summary:
            summary = "Aucun problème candidat n’a été identifié par ces contrôles."
        messagebox.showinfo(
            "Proposition — aucune réparation automatique",
            summary
            + "\n\nRéparations fixes disponibles : cache DNS, SFC ou DISM. "
            "Aucune ne sera lancée automatiquement. Choisissez une action distincte "
            "et confirmez son exécution; SFC/DISM exigent un processus déjà administrateur "
            "et un point de restauration vérifié.",
            parent=self._diagnostics_window,
        )

    def _request_pc_repair(self, action):
        if self._diagnostics_busy:
            return
        from actions.windows_repair import perform_repair, repair_description

        description = repair_description(action)
        extra_risk = (
            "\n\nCette opération peut modifier des composants ou fichiers Windows. "
            "Elle peut durer longtemps. Si NIANG IA n’est pas déjà exécuté avec les "
            "permissions nécessaires, elle s’arrêtera sans ouvrir l’UAC."
            if action != "flush_dns"
            else "\n\nCette opération efface le cache DNS local; elle ne télécharge rien."
        )
        if not messagebox.askyesno(
            "Autoriser la réparation ?",
            description + extra_risk + "\n\nAutorisez-vous cette opération précise ?",
            parent=self._diagnostics_window,
        ):
            return

        cancel_event = threading.Event()
        self._diagnostics_cancel_event = cancel_event
        self._set_pc_diagnostics_busy(True, f"Réparation en cours : {action}…")
        self._set_pc_diagnostics_output(
            "Commande autorisée par l’utilisateur. Vérification du résultat en cours…"
        )

        def worker():
            try:
                result = perform_repair(
                    action,
                    approved=True,
                    cancel_event=cancel_event,
                    diagnostic_associated=str(
                        (self._diagnostics_last_report or {}).get("timestamp_utc", "")
                    )[:200],
                    problem=action,
                )
                text = json.dumps(result, ensure_ascii=False, indent=2)
                status = (
                    f"Réparation : {result.get('status', 'état inconnu')} — "
                    f"{result.get('reason') or 'consultez le résultat et sa vérification.'}"
                )
                self.root.after(0, lambda: self._finish_pc_diagnostics_error(status))
                self.root.after(0, lambda: self._set_pc_diagnostics_output(text))
            except Exception as exc:
                message = str(exc)
                self.root.after(0, lambda: self._finish_pc_diagnostics_error(message))

        threading.Thread(target=worker, name="NIANG-PC-Repair", daemon=True).start()

    def _show_pc_repair_history(self):
        from actions.windows_repair_history import repair_history_text

        try:
            text = repair_history_text()
        except Exception as exc:
            messagebox.showerror(
                "Historique des réparations",
                f"Impossible de lire l’historique local : {exc}",
                parent=self._diagnostics_window,
            )
            return
        self._set_pc_diagnostics_output(
            text if text != "[]" else "Aucune réparation enregistrée."
        )

    def _show_pc_diagnostic_history(self):
        from actions.windows_diagnostics import history_text

        try:
            text = history_text()
        except Exception as exc:
            messagebox.showerror(
                "Historique des diagnostics",
                f"Impossible de lire l’historique local : {exc}",
                parent=self._diagnostics_window,
            )
            return
        self._set_pc_diagnostics_output(text if text != "[]" else "Aucun diagnostic enregistré.")

    def _start_agent_mission(self):
        goal = self._agent_mission.get("1.0", "end-1c").strip()
        if not goal:
            self._agent_status_label.configure(text="Saisissez une mission.")
            return
        if self._agent_task_id:
            self._agent_status_label.configure(text="Une mission est déjà en cours.")
            return
        if not self.on_agent_start:
            self._agent_status_label.configure(text="Le moteur de l’agent n’est pas disponible.")
            return
        try:
            self._agent_task_id = self.on_agent_start(goal)
            self._agent_history_task_id = None
            self._agent_history_count = 0
            self._agent_start_button.configure(state="disabled")
            self._agent_stop_button.configure(state="normal")
            self.write_log("SYS: Mission de l’agent démarrée.")
            self._refresh_agent_panel()
        except Exception as exc:
            self._agent_status_label.configure(text=f"Échec : {str(exc)[:160]}")
            self.write_log(f"ERR: Démarrage de l’agent impossible : {exc}")

    def _stop_agent_mission(self):
        task_id = self._agent_task_id
        if not task_id or not self.on_agent_cancel:
            return
        try:
            if self.on_agent_cancel(task_id):
                self._agent_status_label.configure(text="Arrêt demandé…")
            else:
                self._agent_status_label.configure(text="Aucune mission en cours.")
        except Exception as exc:
            self._agent_status_label.configure(text=f"Arrêt impossible : {str(exc)[:120]}")
            self.write_log(f"ERR: Arrêt de l’agent impossible : {exc}")

    def _resume_agent_mission(self):
        from tkinter import messagebox

        try:
            from agent.task_queue import get_queue
            queue = get_queue()
            previous = queue.latest_interrupted()
            if not previous:
                self._agent_status_label.configure(text="Aucune mission interrompue.")
                return
            history = previous.get("action_history", [])
            approved = messagebox.askyesno(
                "Reprise avec vérification",
                "La mission interrompue sera replanifiée. Les actions précédentes "
                "ne seront pas rejouées automatiquement, mais leurs effets peuvent "
                "déjà exister. NIANG IA devra vérifier l’état actuel ; toute action "
                "impossible à vérifier devra être arrêtée.\n\n"
                f"Actions enregistrées : {len(history)}\n"
                "Continuer ?",
                parent=self.root,
            )
            if not approved:
                return
            self._agent_task_id = queue.resume_interrupted(
                previous["task_id"],
                user_confirmed=True,
                approval_callback=self.request_agent_approval,
            )
            self._agent_history_task_id = None
            self._agent_history_count = 0
            self._agent_start_button.configure(state="disabled")
            self._agent_stop_button.configure(state="normal")
            self._agent_resume_button.configure(state="disabled")
            self._agent_status_label.configure(text="Reprise en cours…")
            self._refresh_agent_panel()
        except Exception as exc:
            self._agent_status_label.configure(
                text=f"Reprise impossible : {str(exc)[:120]}"
            )
            self.write_log(f"ERR: Reprise de l'agent impossible: {exc}")

    def request_agent_approval(self, tool: str, parameters: dict, description: str) -> bool:
        from tkinter import messagebox

        prompt = (
            f"Action sensible :\n\n{description}\n\n"
            "Autorisez-vous cette action uniquement ? Toute autre action sensible "
            "nécessitera une nouvelle confirmation."
        )
        if threading.current_thread() is self._main_thread:
            return messagebox.askyesno(
                "Confirmation requise — NIANG IA",
                prompt,
                parent=self.root,
            )

        decision = {"approved": False}
        completed = threading.Event()

        def ask():
            try:
                decision["approved"] = messagebox.askyesno(
                    "Confirmation requise — NIANG IA",
                    prompt,
                    parent=self.root,
                )
            except Exception as exc:
                self.write_log(f"ERR: Demande de confirmation impossible: {exc}")
            finally:
                completed.set()

        try:
            self.root.after(0, ask)
        except tk.TclError as exc:
            self.write_log(f"ERR: Interface fermee pendant la confirmation: {exc}")
            return False
        if not completed.wait(timeout=300):
            self.write_log(f"ERR: Confirmation expirée pour {tool} ; action refusée.")
            return False
        return decision["approved"]

    def _refresh_agent_panel(self):
        window = self._agent_window
        if window is None or not window.winfo_exists():
            return
        task_id = self._agent_task_id
        try:
            from agent.task_queue import get_queue
            interrupted = get_queue().latest_interrupted()
        except Exception as exc:
            interrupted = None
            self._agent_status_label.configure(
                text=f"Impossible de lire les missions interrompues : {str(exc)[:80]}"
            )
        self._agent_resume_button.configure(
            state=(
                "normal"
                if interrupted and not task_id
                else "disabled"
            )
        )
        if not task_id and interrupted:
            interrupted_id = interrupted["task_id"]
            self._agent_status_label.configure(
                text=f"Mission interrompue [{interrupted_id}] — vérification requise."
            )
            if self._agent_history_task_id != interrupted_id:
                self._agent_history_task_id = interrupted_id
                self._agent_history_count = 0
                self._agent_history_text.configure(state="normal")
                self._agent_history_text.delete("1.0", tk.END)
                self._agent_report_text.configure(state="normal")
                self._agent_report_text.delete("1.0", tk.END)
                self._agent_report_text.insert(
                    tk.END,
                    f"Mission : {interrupted.get('goal', '')}\n"
                    f"{interrupted.get('error', '')}",
                )
                self._agent_report_text.configure(state="disabled")
            history = interrupted.get("action_history", [])
            for action in history[self._agent_history_count:]:
                self._agent_history_text.configure(state="normal")
                self._agent_history_text.insert(
                    tk.END,
                    f"[{action.get('number', '?')}] "
                    f"{self._translate_status(action.get('status', 'unknown').upper())} "
                    f"{action.get('tool', '')}: "
                    f"{action.get('description', '')}\n"
                    f"{action.get('result', '')}\n\n",
                )
                self._agent_history_text.see(tk.END)
                self._agent_history_text.configure(state="disabled")
                self._show_agent_screenshot(action.get("result", ""))
            self._agent_history_count = len(history)
        if task_id:
            try:
                from agent.task_queue import get_queue
                status = get_queue().get_status(task_id)
            except Exception as exc:
                self._agent_status_label.configure(
                    text=f"Impossible de lire l’état : {str(exc)[:100]}"
                )
                status = None
            if status:
                phase = status.get("phase", status.get("status", "running"))
                progress = f"{status.get('completed_steps', 0)}/{status.get('total_steps', 0)}"
                current = status.get("current_step", "")
                self._agent_status_label.configure(
                    text=f"{self._translate_status(status.get('status', phase).upper())} {progress} {current}"[:180]
                )
                if self._agent_history_task_id != task_id:
                    self._agent_history_task_id = task_id
                    self._agent_history_count = 0
                    self._agent_history_text.configure(state="normal")
                    self._agent_history_text.delete("1.0", tk.END)
                    self._agent_history_text.configure(state="disabled")
                    self._agent_report_text.configure(state="normal")
                    self._agent_report_text.delete("1.0", tk.END)
                    self._agent_report_text.configure(state="disabled")
                history = status.get("action_history", [])
                for action in history[self._agent_history_count:]:
                    self._agent_history_text.configure(state="normal")
                    self._agent_history_text.insert(
                        tk.END,
                        f"[{action.get('number', '?')}] {self._translate_status(action.get('status', 'unknown').upper())} "
                        f"{action.get('tool', '')}: {action.get('description', '')}\n"
                        f"{action.get('result', '')}\n\n",
                    )
                    self._agent_history_text.see(tk.END)
                    self._agent_history_text.configure(state="disabled")
                    self._show_agent_screenshot(action.get("result", ""))
                self._agent_history_count = len(history)

                if status.get("status") in {
                    "completed", "partial", "failed", "action_unknown", "cancelled", "interrupted",
                }:
                    result = status.get("result") or status.get("error") or "Mission terminée."
                    self._agent_report_text.configure(state="normal")
                    self._agent_report_text.delete("1.0", tk.END)
                    self._agent_report_text.insert(tk.END, str(result))
                    self._agent_report_text.configure(state="disabled")
                    self._agent_start_button.configure(state="normal")
                    self._agent_stop_button.configure(state="disabled")
                    self._agent_task_id = None
            elif self._agent_task_id:
                self._agent_status_label.configure(text="Mission introuvable.")
        if self._agent_window is not None and self._agent_window.winfo_exists():
            self._agent_refresh_after = self.root.after(500, self._refresh_agent_panel)

    def _show_agent_screenshot(self, result: str):
        import re

        match = re.search(r"Screenshot saved:\s*(.+)", str(result))
        if not match:
            return
        path = Path(match.group(1).strip().strip('"'))
        if not path.is_file():
            return
        try:
            image = Image.open(path).convert("RGB")
            image.thumbnail((560, 220), Image.Resampling.LANCZOS)
            self._agent_screenshot_image = ImageTk.PhotoImage(image)
            self._agent_screenshot_label.configure(
                image=self._agent_screenshot_image,
                text=str(path),
                compound="top",
            )
            self._agent_screenshot_path = path
        except Exception as exc:
            self.write_log(f"ERR: Apercu de capture impossible: {exc}")

    def _open_agent_screenshot(self):
        path = self._agent_screenshot_path
        if not path or not path.is_file():
            self.write_log("ERR: Aucune capture d'ecran disponible.")
            return
        try:
            os.startfile(str(path))
        except (AttributeError, OSError) as exc:
            self.write_log(f"ERR: Ouverture de capture impossible: {exc}")

    def _refresh_deck_status(self):
        if hasattr(self, "_vision_status"):
            color = self.col["green"] if self.vision_mode != "STANDBY" else self.col["dim"]
            self._vision_status.configure(text="● " + self._translate_status(self.vision_mode), fg=color,
                                          bg=self.col["panel"])
        if hasattr(self, "_vision_signal_label"):
            self._vision_signal_label.configure(text=self.vision_signal,
                                                bg=self.col["panel"], fg=self.col["text"])
        if hasattr(self, "_live_camera_status"):
            active = self.live_camera_active
            self._live_camera_status.configure(
                text=f"● CAMÉRA EN DIRECT : {'ACTIVE' if active else 'INACTIVE'}",
                bg=self.col["panel"],
                fg=self.col["red"] if active else self.col["dim"],
            )
        if hasattr(self, "_whatsapp_call_status_label"):
            active = any(
                state in self.whatsapp_call_status
                for state in ("CONNECTED", "LISTENING", "SPEAKING")
            )
            self._whatsapp_call_status_label.configure(
                text=self._translate_status(self.whatsapp_call_status),
                bg=self.col["panel"],
                fg=self.col["red"] if active else self.col["dim"],
            )

    @staticmethod
    def _translate_status(text):
        translations = {
            "STANDBY": "VEILLE",
            "ONLINE": "EN LIGNE",
            "OFFLINE": "HORS LIGNE",
            "CONNECTED": "CONNECTÉ",
            "LISTENING": "À L’ÉCOUTE",
            "SPEAKING": "PARLE",
            "PROCESSING": "TRAITEMENT EN COURS",
            "THINKING": "RÉFLEXION EN COURS",
            "GESTURE": "GESTES",
            "OBJECTS": "OBJETS",
            "AIR_MOUSE": "SOURIS GESTUELLE",
            "VOLUME": "VOLUME",
            "POSTURE": "POSTURE",
            "MOTION": "MOUVEMENTS",
            "RUNNING": "EN COURS",
            "COMPLETED": "TERMINÉE",
            "PARTIAL": "PARTIELLE",
            "FAILED": "ÉCHEC",
            "CANCELLED": "ANNULÉE",
            "INTERRUPTED": "INTERROMPUE",
            "ACTION_UNKNOWN": "ACTION INCONNUE",
            "PENDING": "EN ATTENTE",
            "UNKNOWN": "INCONNU",
            "CRITICAL": "CRITIQUE",
            "HIGH": "ÉLEVÉ",
            "MEDIUM": "MOYEN",
            "LOW": "FAIBLE",
            "IDLE": "INACTIF",
            "PREPARING": "PRÉPARATION",
            "ON_HOLD": "EN PAUSE",
            "ENDING": "ARRÊT EN COURS",
        }
        translated = str(text or "")
        for source, target in translations.items():
            translated = translated.replace(source, target)
        for source, target in {
            "LIVE CAMERA: frames are streamed to Gemini": "Caméra en direct : les images sont transmises à Gemini",
            "Live camera is off": "La caméra en direct est désactivée",
            "Live camera stopped: Gemini session disconnected": "Caméra en direct arrêtée : session Gemini déconnectée",
            "Awaiting camera input": "En attente de la caméra",
            "NIANG IA microphone input and playback are paused.": "Le microphone et la lecture audio de NIANG IA sont en pause.",
            "NIANG IA call audio resumed.": "Le son de l’appel de NIANG IA a repris.",
            "Stopping NIANG IA audio; WhatsApp remains under your control.": "Arrêt du son de NIANG IA ; WhatsApp reste sous votre contrôle.",
            "NIANG IA is speaking to the call.": "NIANG IA parle pendant l’appel.",
            "Listening to the WhatsApp call audio.": "Écoute du son de l’appel WhatsApp.",
            "The AI response was interrupted.": "La réponse de l’IA a été interrompue.",
        }.items():
            translated = translated.replace(source, target)
        return translated

    def set_vision_signal(self, text: str):
        """Publish the latest local CV observation to the command deck."""
        self.vision_signal = self._translate_status(text or "En attente de la caméra")[:120]
        self._safe_ui(self._refresh_deck_status)

    def set_live_camera_status(self, active: bool):
        """Show whether webcam frames are currently being sent to Gemini."""
        self.live_camera_active = bool(active)
        self._safe_ui(self._refresh_deck_status)

    def set_whatsapp_call_status(self, state: str, detail: str):
        """Display NIANG IA's audio state without implying WhatsApp call state."""
        self.whatsapp_call_status = f"{state}: {detail}"[:160]
        self._safe_ui(self._refresh_deck_status)

    def set_vision_detections(self, events):
        """Show a compact object summary from the active detector."""
        labels_fr = {
            "person": "personne", "bicycle": "vélo", "car": "voiture",
            "motorcycle": "moto", "airplane": "avion", "bus": "bus",
            "train": "train", "truck": "camion", "boat": "bateau",
            "traffic light": "feu de circulation", "fire hydrant": "borne incendie",
            "stop sign": "panneau stop", "parking meter": "horodateur", "bench": "banc",
            "bird": "oiseau", "cat": "chat", "dog": "chien", "horse": "cheval",
            "sheep": "mouton", "cow": "vache", "elephant": "éléphant", "bear": "ours",
            "zebra": "zèbre", "giraffe": "girafe", "backpack": "sac à dos",
            "umbrella": "parapluie", "handbag": "sac à main", "tie": "cravate",
            "suitcase": "valise", "frisbee": "disque volant", "skis": "skis",
            "snowboard": "planche à neige", "sports ball": "ballon",
            "kite": "cerf-volant", "baseball bat": "batte de baseball",
            "baseball glove": "gant de baseball", "skateboard": "planche à roulettes",
            "surfboard": "planche de surf", "tennis racket": "raquette de tennis",
            "bottle": "bouteille", "wine glass": "verre à vin", "cup": "tasse",
            "fork": "fourchette", "knife": "couteau", "spoon": "cuillère", "bowl": "bol",
            "banana": "banane", "apple": "pomme", "sandwich": "sandwich",
            "orange": "orange", "broccoli": "brocoli", "carrot": "carotte",
            "hot dog": "hot-dog", "pizza": "pizza", "donut": "beignet", "cake": "gâteau",
            "chair": "chaise", "couch": "canapé", "potted plant": "plante en pot",
            "bed": "lit", "dining table": "table", "toilet": "toilettes",
            "tv": "télévision", "laptop": "ordinateur portable", "mouse": "souris",
            "remote": "télécommande", "keyboard": "clavier", "cell phone": "téléphone portable",
            "microwave": "micro-ondes", "oven": "four", "toaster": "grille-pain",
            "sink": "évier", "refrigerator": "réfrigérateur", "book": "livre",
            "clock": "horloge", "vase": "vase", "scissors": "ciseaux",
            "teddy bear": "ours en peluche", "hair drier": "sèche-cheveux",
            "toothbrush": "brosse à dents",
        }
        counts = {}
        for event in events or []:
            label = str(getattr(event, "label", "objet"))
            label = labels_fr.get(label.lower(), label)
            counts[label] = counts.get(label, 0) + 1
        if counts:
            summary = "OBJETS : " + ", ".join(
                f"{count}× {label}" for label, count in counts.items()
            )
            self.set_vision_signal(summary)

    def open_vision_preview(self):
        """Open a live preview fed by the existing vision camera thread."""
        if self._preview_window is not None and self._preview_window.winfo_exists():
            self._preview_window.lift()
            return
        win = tk.Toplevel(self.root)
        win.title("NIANG IA — Aperçu de la vision · Floutage privé")
        win.configure(bg=self.col["bg"])
        win.geometry("700x560")
        win.resizable(True, True)
        label = tk.Label(win, text="En attente d’images de la caméra…", bg=self.col["bg"],
                         fg=self.col["text"], font=("Consolas", 11))
        label.pack(fill="both", expand=True, padx=12, pady=12)
        self._preview_window = win
        self._preview_label = label
        self.vision_preview_open = True

        def close():
            self.vision_preview_open = False
            self._preview_window = None
            self._preview_label = None
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", close)

    def set_vision_frame(self, frame):
        """Receive one privacy-filtered BGR frame from the camera thread."""
        if not self.vision_preview_open or frame is None:
            return
        self._safe_ui(self._render_vision_frame, frame)

    def open_vision_arcade(self):
        if self._arcade_window is not None and self._arcade_window.winfo_exists():
            self._arcade_window.lift()
            return
        win = tk.Toplevel(self.root)
        win.title("NIANG IA — Jeux de vision · Vision locale")
        win.configure(bg=self.col["bg"])
        win.geometry("1100x760")
        win.minsize(900, 620)
        try:
            win.state("zoomed")
        except tk.TclError:
            pass
        toolbar = tk.Frame(win, bg=self.col["panel"])
        toolbar.pack(fill="x", padx=10, pady=10)
        for label, game in [("FILTRE VISAGE", "face_filter"),
                            ("PONG GESTUEL", "gesture_pong"),
                            ("CHASSE AUX ORBES", "orb_hunt"),
                            ("PIERRE-FEUILLE-CISEAUX", "rps"),
                            ("CRÉATEUR DE FORMES", "shape_creator"),
                            ("LE SOL EST EN LAVE", "floor_lava"),
                            ("EXPLORATEUR PLANÉTAIRE", "planet_explorer"),
                            ("TOURBILLON", "whirlpool"),
                            ("DÉFENSE LASER", "laser_defense"),
                            ("ARPÉGIATEUR", "arpeggiator")]:
            tk.Button(toolbar, text=tr(label), command=lambda g=game: self._start_arcade_game(g),
                      bg=self.col["input"], fg=self.col["text"], activebackground=self.col["pri"],
                      activeforeground=self.col["bg"], relief="flat", font=("Consolas", 9, "bold"),
                      cursor="hand2").pack(side="left", padx=3, ipady=7)
        label = tk.Label(win, text="En attente d’images de la caméra…", bg=self.col["bg"],
                         fg=self.col["text"], font=("Consolas", 11))
        label.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._arcade_window, self._arcade_label = win, label
        self.arcade_open = True
        self._start_arcade_game("face_filter")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command,
                             args=("start vision gesture",), daemon=True).start()

        def close():
            self.arcade_open = False
            self._arcade_window = None
            self._arcade_label = None
            self._arcade.stop()
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", close)

    def _start_arcade_game(self, game):
        self._arcade.start(game)
        self.write_log("SYS: Jeux de vision → " + game)

    def set_arcade_signal(self, gesture: str, x: float = 0.5):
        if not self.arcade_open:
            return
        self._safe_ui(self._apply_arcade_signal, gesture, x)

    def set_arcade_pose(self, arms_raised: bool, lean: float = 0.0):
        if not self.arcade_open:
            return
        self._safe_ui(self._arcade.on_pose, arms_raised, lean)

    def _apply_arcade_signal(self, gesture, x):
        self._arcade.on_gesture(gesture, x)

    def set_arcade_frame(self, frame):
        if not self.arcade_open or frame is None:
            return
        self._safe_ui(self._render_arcade_frame, frame)

    def _render_arcade_frame(self, frame):
        if self._arcade_label is None:
            return
        try:
            import cv2
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            target_w = max(420, self._arcade_label.winfo_width() - 24)
            target_h = max(300, self._arcade_label.winfo_height() - 24)
            image = ImageOps.fit(image, (target_w, target_h), method=Image.Resampling.LANCZOS,
                                 centering=(0.5, 0.5))
            draw = ImageDraw.Draw(image)
            state = self._arcade.state
            hud_h = max(88, image.height // 8)
            title_font = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", max(18, image.width // 55))
            msg_font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", max(15, image.width // 72))
            draw.rectangle((0, 0, image.width, hud_h), fill="#001520", outline="#00d4ff", width=3)
            game_names = {
                "face_filter": "FILTRE VISAGE",
                "gesture_pong": "PONG GESTUEL",
                "rps": "PIERRE-FEUILLE-CISEAUX",
                "shape_creator": "CRÉATEUR DE FORMES",
                "orb_hunt": "CHASSE AUX ORBES",
                "floor_lava": "LE SOL EST EN LAVE",
                "planet_explorer": "EXPLORATION PLANÉTAIRE",
                "whirlpool": "TOURBILLON",
                "laser_defense": "DÉFENSE LASER",
                "arpeggiator": "ARPÉGIATEUR",
                "idle": "VEILLE",
            }
            draw.text(
                (24, 14),
                f"{game_names.get(state.game, state.game)}   POINTS {state.score}   VIES {state.lives}",
                      fill="#8ffcff", font=title_font, stroke_width=2, stroke_fill="#001520")
            extra = f"  MANCHE {state.rounds}  SÉRIE {state.streak}" if state.rounds else ""
            draw.text((24, 14 + title_font.size + 8), state.message + extra,
                      fill="#ffcc00", font=msg_font, stroke_width=1, stroke_fill="#001520")
            if state.game == "floor_lava":
                draw.rectangle((0, int(image.height * 0.82), image.width, image.height), fill="#8b1900")
                draw.text((24, int(image.height * 0.86)), "LAVE", fill="#ffcc00", font=title_font)
            elif state.game == "planet_explorer":
                cx, cy = int(image.width * 0.72), int(image.height * 0.55)
                draw.ellipse((cx - 100, cy - 100, cx + 100, cy + 100), outline="#38bdf8", width=5)
                px = cx - 100 + int(state.planet_x * 200)
                draw.line((cx, cy, px, cy - 130), fill="#ffcc00", width=3)
            elif state.game == "laser_defense":
                x = int(state.hand_x * image.width)
                draw.line((x, image.height - 30, x, 80), fill="#ff3366", width=4)
            elif state.game == "arpeggiator":
                for i, note in enumerate(("C", "D", "E", "G", "A")):
                    x = 30 + i * 70
                    bar = 35 if note == state.note else 15
                    draw.rectangle((x, image.height - 50 - bar, x + 42, image.height - 50), fill="#00d4ff")
                    draw.text((x + 12, image.height - 42), note, fill="#001520", font=msg_font)
            elif state.game == "shape_creator":
                cx, cy = int(state.hand_x * image.width), int(image.height * 0.55)
                if state.shape == "circle":
                    draw.ellipse((cx - 45, cy - 45, cx + 45, cy + 45), outline="#00d4ff", width=5)
                elif state.shape == "square":
                    draw.rectangle((cx - 45, cy - 45, cx + 45, cy + 45), outline="#00d4ff", width=5)
                else:
                    draw.polygon((cx, cy - 55, cx - 55, cy + 45, cx + 55, cy + 45), outline="#00d4ff")
            elif state.game == "orb_hunt":
                cx, cy = int(state.target_x * image.width), int(image.height * 0.55)
                radius = max(24, 48 - state.level * 2)
                draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                             fill="#ff4fd8", outline="#fff3ff", width=4)
                draw.ellipse((cx - radius // 3, cy - radius // 3,
                              cx + radius // 3, cy + radius // 3), fill="#ffe66d")
            self._arcade_image = ImageTk.PhotoImage(image)
            self._arcade_label.configure(image=self._arcade_image, text="")
        except Exception:
            pass

    def _render_vision_frame(self, frame):
        if self._preview_label is None:
            return
        try:
            import cv2
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = Image.fromarray(rgb)
            target_w = max(320, self._preview_label.winfo_width() - 24)
            target_h = max(240, self._preview_label.winfo_height() - 24)
            image = ImageOps.contain(image, (target_w, target_h), method=Image.Resampling.LANCZOS)
            self._preview_image = ImageTk.PhotoImage(image)
            self._preview_label.configure(image=self._preview_image, text="")
        except Exception:
            pass

    def _apply_deck_theme(self):
        for deck in (getattr(self, "_left_deck", None), getattr(self, "_right_deck", None)):
            if deck is not None:
                deck.configure(bg=self.col["panel"], highlightbackground=self.col["mid"])
                for widget in deck.winfo_children():
                    if isinstance(widget, PillButton):
                        continue
                    try:
                        widget.configure(bg=self.col["panel"])
                    except tk.TclError:
                        pass
        for btn in getattr(self, "_deck_buttons", []):
            btn.refresh()
        self._refresh_deck_status()

    def _check_for_updates(self):
        if self._update_check_in_progress:
            return
        self._update_check_in_progress = True
        self._update_button.configure(state="disabled", text=tr("VÉRIFICATION…"))

        def worker():
            try:
                from app_update import CURRENT_VERSION, check_for_update
                update = check_for_update(CURRENT_VERSION)
                self.root.after(0, self._finish_update_check, update, None)
            except Exception as exc:
                self.root.after(0, self._finish_update_check, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_update_check(self, update, error):
        self._update_check_in_progress = False
        self._update_button.configure(state="normal", text=tr("↻ MISE À JOUR"))
        if error:
            self.write_log(f"ERR: Vérification des mises à jour impossible : {error}")
            messagebox.showerror(
                "Mise à jour NIANG IA",
                f"Impossible de vérifier les mises à jour GitHub.\n\n{error}",
                parent=self.root,
            )
            return
        if update is None:
            from app_update import CURRENT_VERSION
            self._update_button.configure(text=tr("NIANG IA À JOUR"))
            self.root.after(5000, self._reset_update_button)
            self.write_log("SYS: NIANG IA est déjà à jour.")
            return

        self._update_button.configure(text=tr("VERSION ") + update.version)
        self.write_log(f"SYS: Mise à jour NIANG IA {update.version} disponible.")
        if messagebox.askyesno(
            "Mise à jour disponible",
            f"NIANG IA {update.version} est disponible.\n\n"
            "Télécharger et vérifier l'installateur officiel dans votre dossier "
            "Téléchargements ?",
            parent=self.root,
        ):
            self._download_update(update)

    def _download_update(self, update):
        self._update_button.configure(state="disabled", text=tr("TÉLÉCHARGEMENT ") + "0 %")

        def report_progress(percent):
            try:
                self.root.after(0, self._set_update_download_progress, percent)
            except tk.TclError:
                pass

        def worker():
            try:
                from app_update import download_update
                installer = download_update(update, progress=report_progress)
                self.root.after(0, self._finish_update_download, installer, None)
            except Exception as exc:
                self.root.after(0, self._finish_update_download, None, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _set_update_download_progress(self, percent):
        self._update_button.configure(text=f"{tr('TÉLÉCHARGEMENT ')}{percent} %")

    def _finish_update_download(self, installer, error):
        self._update_button.configure(state="normal", text=tr("↻ MISE À JOUR"))
        if error:
            self.write_log(f"ERR: Téléchargement de la mise à jour impossible : {error}")
            messagebox.showerror(
                "Téléchargement impossible",
                f"L'installateur n'a pas été téléchargé ou vérifié.\n\n{error}",
                parent=self.root,
            )
            return

        self._update_button.configure(text=tr("INSTALLATEUR PRÊT"))
        self.root.after(8000, self._reset_update_button)
        self.write_log(f"SYS: Installateur vérifié téléchargé : {installer}")
        if messagebox.askyesno(
            "Installateur vérifié",
            f"L'installateur a été téléchargé et vérifié :\n{installer}\n\n"
            "Lancer maintenant l'installation ? NIANG IA se fermera pour permettre "
            "la mise à jour.",
            parent=self.root,
        ):
            self._launch_update_installer(installer)

    def _reset_update_button(self):
        try:
            if self._update_button.winfo_exists():
                self._update_button.configure(text=tr("↻ MISE À JOUR"))
        except tk.TclError:
            pass

    def _launch_update_installer(self, installer):
        try:
            import subprocess
            subprocess.Popen([str(installer)], close_fds=True)
        except OSError as exc:
            self.write_log(f"ERR: Lancement de l'installateur impossible : {exc}")
            messagebox.showerror(
                "Lancement impossible",
                f"Exécutez manuellement cet installateur :\n{installer}\n\n{exc}",
                parent=self.root,
            )
            return
        self.root.after(500, self._close_application)

    def _build_file_drop_area(self):
        self._file_card = tk.Frame(
            self.root, bg=self.col["panel"], highlightthickness=1,
            highlightbackground=self.col["mid"],
        )
        self._file_rows = tk.Frame(self._file_card, bg=self.col["panel"])
        self._file_rows.pack(fill="x", padx=8, pady=(6, 0))
        self._file_progress = tk.Label(
            self._file_card, text="", anchor="w", bg=self.col["panel"],
            fg=self.col["acc2"], font=("Consolas", 8), cursor="hand2",
        )
        self._file_progress.pack(fill="x", padx=8, pady=(2, 6))
        self._file_progress.bind("<Button-1>", self._retry_file_analysis)
        self._file_card.place_forget()

        self._drop_overlay = tk.Frame(
            self.root, bg=self.col["panel"], highlightthickness=2,
            highlightbackground=self.col["pri"],
        )
        self._drop_icon = tk.Label(
            self._drop_overlay, text="☁",
            bg=self.col["panel"], fg=self.col["pri"],
            font=("Segoe UI Symbol", 30),
        )
        self._drop_icon.pack(pady=(5, 0))
        self._drop_label = tk.Label(
            self._drop_overlay, text="Déposez vos fichiers n'importe où",
            bg=self.col["panel"], fg=self.col["pri"],
            font=("Segoe UI", 10),
        )
        self._drop_label.pack(pady=(0, 9))
        self._drop_overlay.place_forget()

    def _file_card_position(self):
        width = min(420, self.W - 32)
        height = max(60, 36 + len(self._selected_paths) * 22)
        log_y = self.H - int(self.H * 0.11) - int(self.H * 0.13)
        y = min(
            max(self.FCY + self.FACE_SZ // 2 + 20, int(self.H * 0.40)),
            max(100, log_y - height - 8),
        )
        return max(8, (self.W - width) // 2), y, width, height

    def _show_drop_overlay(self):
        self._drop_hud_visible = True
        self._draw_drop_hud()
        self._drop_overlay.place(
            x=max(8, (self.W - min(390, self.W - 32)) // 2),
            y=max(100, self.FCY + self.FACE_SZ // 2 + 54),
            width=min(390, self.W - 32),
            height=112,
        )
        self._drop_overlay.lift()
        if self._drop_pulse_after is None:
            self._pulse_drop_overlay()

    def _draw_drop_hud(self):
        self.bg.delete("drop-hud")
        inset = 7
        top = 76
        bottom = max(top + 1, self.H - 42)
        right = max(inset + 1, self.W - inset)
        color = self.col["pri"]
        self.bg.create_rectangle(
            inset, top, right, bottom,
            outline=color, width=1, dash=(3, 8),
            tags=("drop-hud", "drop-hud-border"),
        )
        length = 34
        corners = (
            (inset, top, inset + length, top, inset, top, inset, top + length),
            (right, top, right - length, top, right, top, right, top + length),
            (inset, bottom, inset + length, bottom, inset, bottom, inset, bottom - length),
            (right, bottom, right - length, bottom, right, bottom, right, bottom - length),
        )
        for x1, y1, x2, y2, x3, y3, x4, y4 in corners:
            self.bg.create_line(
                x1, y1, x2, y2, fill=color, width=3,
                tags=("drop-hud", "drop-hud-corners"),
            )
            self.bg.create_line(
                x3, y3, x4, y4, fill=color, width=3,
                tags=("drop-hud", "drop-hud-corners"),
            )

    def _pulse_drop_overlay(self):
        if not self._drop_hud_visible:
            self._drop_pulse_after = None
            return
        colors = (self.col["pri"], self.col["mid"], self.col["dim"], self.col["mid"])
        color = colors[self._drop_pulse_index % len(colors)]
        self._drop_pulse_index += 1
        self._drop_overlay.configure(highlightbackground=color)
        self.bg.itemconfigure("drop-hud-border", outline=color)
        self.bg.itemconfigure("drop-hud-corners", fill=color)
        self._drop_pulse_after = self.root.after(220, self._pulse_drop_overlay)

    def _on_drop_enter(self, event=None):
        if self._drop_leave_after is not None:
            self.root.after_cancel(self._drop_leave_after)
            self._drop_leave_after = None
        self._show_drop_overlay()
        return event.action if event and getattr(event, "action", None) else "copy"

    def _on_drop_leave(self, event=None):
        if self._drop_leave_after is not None:
            self.root.after_cancel(self._drop_leave_after)
        self._drop_leave_after = self.root.after(180, self._hide_drop_overlay)

    def _hide_drop_overlay(self):
        self._drop_leave_after = None
        self._drop_hud_visible = False
        self._drop_overlay.place_forget()
        self.bg.delete("drop-hud")
        if self._drop_pulse_after is not None:
            self.root.after_cancel(self._drop_pulse_after)
            self._drop_pulse_after = None

    def _on_drop(self, event):
        self._hide_drop_overlay()
        try:
            paths = self.root.tk.splitlist(event.data)
        except tk.TclError as exc:
            self.write_log(f"ERR: Impossible de lire les fichiers déposés : {exc}")
            return "break"
        self._handle_selected_files(paths)
        return "copy"

    def _open_file_dialog(self, event=None):
        from actions.intelligent_analysis import SUPPORTED_EXTENSIONS

        extensions = sorted(SUPPORTED_EXTENSIONS)
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title="Choisir des fichiers à analyser",
            filetypes=[
                ("Formats pris en charge", " ".join(f"*{ext}" for ext in extensions)),
                ("Tous les fichiers", "*.*"),
            ],
        )
        if paths:
            self._handle_selected_files(paths)
        return "break"

    def _handle_selected_files(self, paths):
        from actions.intelligent_analysis import (
            MAX_FILE_BYTES,
            MAX_FILES,
            SUPPORTED_EXTENSIONS,
        )

        accepted = []
        seen = {str(Path(path).resolve()).lower() for path in self._selected_paths}
        for raw_path in paths:
            path = Path(raw_path).expanduser()
            try:
                resolved = str(path.resolve(strict=True))
                if not path.is_file():
                    raise ValueError("ce chemin n'est pas un fichier")
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    raise ValueError(f"format non pris en charge ({path.suffix or 'sans extension'})")
                if path.stat().st_size > MAX_FILE_BYTES:
                    raise ValueError(f"fichier supérieur à {MAX_FILE_BYTES // (1024 * 1024)} Mo")
                if resolved.lower() in seen:
                    continue
                if len(self._selected_paths) + len(accepted) >= MAX_FILES:
                    raise ValueError(f"limite de {MAX_FILES} fichiers par session atteinte")
                accepted.append(resolved)
                seen.add(resolved.lower())
            except (OSError, ValueError) as exc:
                self.write_log(f"ERR: {path.name or raw_path} — {exc}")
        if not accepted:
            return

        self._selected_paths.extend(accepted)
        self.set_analysis_report("")
        self._refresh_file_card()
        self._set_file_status("Import local : validation des fichiers…")
        if self.on_files_selected:
            self.on_files_selected(list(self._selected_paths))
        else:
            self.write_log("ERR: Le service d'analyse des fichiers n'est pas disponible.")

    def _refresh_file_card(self):
        for widget in self._file_row_widgets:
            widget.destroy()
        self._file_row_widgets.clear()
        for path_text in self._selected_paths:
            path = Path(path_text)
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            size_text = f"{size / (1024 * 1024):.1f} Mo" if size >= 1024 * 1024 else f"{size / 1024:.0f} Ko"
            row = tk.Frame(self._file_rows, bg=self.col["panel"])
            row.pack(fill="x")
            label = tk.Label(
                row, text=f"{path.name} · {path.suffix[1:].upper()} · {size_text}",
                anchor="w", bg=self.col["panel"], fg=self.col["text"],
                font=("Consolas", 8),
            )
            label.pack(side="left", fill="x", expand=True)
            remove = tk.Button(
                row, text="×", command=lambda item=path_text: self._remove_imported_file(item),
                bg=self.col["panel"], fg=self.col["red"], activebackground=self.col["red"],
                activeforeground=self.col["bg"], relief="flat", borderwidth=0,
                font=("Segoe UI", 10, "bold"), cursor="hand2",
            )
            remove.pack(side="right")
            self._file_row_widgets.append(row)
        if self._selected_paths:
            x, y, width, _ = self._file_card_position()
            self._file_card.place(x=x, y=y, width=width)
            self._file_card.lift()
        else:
            self._file_card.place_forget()

    def _remove_imported_file(self, path):
        self._selected_paths = [item for item in self._selected_paths if item != path]
        self.set_analysis_report("")
        self._refresh_file_card()
        if self._selected_paths and self.on_files_selected:
            self.on_files_selected(list(self._selected_paths))
        else:
            if self.on_clear_documents:
                self.on_clear_documents()
            self.set_state(
                "MUTED" if self.muted else
                ("LISTENING" if self.connected else "ONLINE")
            )

    def _retry_file_analysis(self, event=None):
        if self._selected_paths and self.on_files_selected:
            self.set_analysis_report("")
            self.set_file_status("Nouvelle analyse en cours…")
            self.on_files_selected(list(self._selected_paths))
        return "break"

    def set_file_status(self, message, error=False):
        self._safe_ui(self._set_file_status, message, error)

    def set_analysis_report(self, report):
        self._safe_ui(self._set_analysis_report, report)

    def _set_analysis_report(self, report):
        self._analysis_report = str(report or "")

    def _export_analysis_report(self, event=None):
        if not self._analysis_report:
            self.write_log("ERR: Aucun rapport d'analyse à exporter.")
            return "break"
        destination = filedialog.asksaveasfilename(
            parent=self.root,
            title="Exporter le rapport NIANG IA",
            defaultextension=".txt",
            initialfile="niang-rapport.txt",
            filetypes=[("Rapport texte", "*.txt"), ("Markdown", "*.md")],
        )
        if destination:
            try:
                Path(destination).write_text(self._analysis_report, encoding="utf-8")
                self.write_log(f"SYS: Rapport exporté : {destination}")
            except OSError as exc:
                self.write_log(f"ERR: Export du rapport impossible : {exc}")
        return "break"

    def _set_file_status(self, message, error=False):
        if not self._selected_paths:
            return
        try:
            self._file_progress.configure(
                text=str(message),
                fg=self.col["red"] if error else self.col["acc2"],
            )
        except tk.TclError:
            pass

    def _open_voiceover(self, event=None):
        if self.on_voiceover_requested is None:
            self.write_log("ERR: Le service Gemini TTS n'est pas disponible.")
            return "break"
        if self._voiceover_window is not None and self._voiceover_window.winfo_exists():
            self._voiceover_window.lift()
            return "break"

        window = tk.Toplevel(self.root)
        self._voiceover_window = window
        window.title("NIANG IA · Voix off")
        window.configure(bg=self.col["bg"])
        window.geometry("620x610")
        window.minsize(500, 500)

        tk.Label(
            window, text="GÉNÉRATION DE VOIX OFF · GEMINI TTS",
            bg=self.col["bg"], fg=self.col["pri"], font=("Consolas", 12, "bold"),
        ).pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(
            window,
            text="Texte envoyé à Gemini TTS. Saisissez-le ici, ou laissez vide pour les documents sélectionnés.",
            bg=self.col["bg"], fg=self.col["text"], font=("Segoe UI", 9),
        ).pack(anchor="w", padx=16, pady=(0, 8))

        source_text = self._get_input().strip()
        text_box = tk.Text(
            window, height=13, wrap="word", bg=self.col["input"],
            fg=self.col["text"], insertbackground=self.col["text"],
            highlightthickness=1, highlightbackground=self.col["mid"],
            font=("Segoe UI", 10),
        )
        text_box.pack(fill="both", expand=True, padx=16, pady=4)
        if source_text:
            text_box.insert("1.0", source_text)

        options = tk.Frame(window, bg=self.col["bg"])
        options.pack(fill="x", padx=16, pady=6)

        def add_option(label, values, default, width=14):
            cell = tk.Frame(options, bg=self.col["bg"])
            cell.pack(side="left", padx=(0, 12))
            tk.Label(cell, text=label, bg=self.col["bg"], fg=self.col["text"],
                     font=("Consolas", 8)).pack(anchor="w")
            selected = tk.StringVar(window, value=default)
            menu = tk.OptionMenu(cell, selected, *values)
            menu.configure(
                width=width, bg=self.col["input"], fg=self.col["text"],
                activebackground=self.col["pri"], activeforeground=self.col["bg"],
                highlightthickness=0, relief="flat", font=("Consolas", 8),
            )
            menu["menu"].configure(
                bg=self.col["panel"], fg=self.col["text"],
                activebackground=self.col["pri"], activeforeground=self.col["bg"],
            )
            menu.pack()
            return selected

        voice = add_option(
            "VOIX", ["Kore", "Aoede", "Puck", "Charon", "Fenrir", "Leda", "Orus", "Zephyr"],
            "Kore", 12,
        )
        language = add_option("LANGUE", ["français", "anglais", "espagnol", "arabe"], "français", 12)
        pace = add_option("RYTHME", ["lent", "normal", "rapide"], "normal", 10)
        tone_cell = tk.Frame(options, bg=self.col["bg"])
        tone_cell.pack(side="left")
        tk.Label(tone_cell, text="TON", bg=self.col["bg"], fg=self.col["text"],
                 font=("Consolas", 8)).pack(anchor="w")
        tone = tk.Entry(
            tone_cell, width=14, bg=self.col["input"], fg=self.col["text"],
            insertbackground=self.col["text"], relief="flat",
        )
        tone.insert(0, "naturel")
        tone.pack()

        status = tk.Label(window, text="En attente", bg=self.col["bg"],
                          fg=self.col["acc2"], anchor="w", font=("Consolas", 9))
        status.pack(fill="x", padx=16, pady=4)
        controls = tk.Frame(window, bg=self.col["bg"])
        controls.pack(fill="x", padx=16, pady=(4, 14))
        generate = tk.Button(
            controls, text=tr("GÉNÉRER"), bg=self.col["panel"], fg=self.col["pri"],
            activebackground=self.col["pri"], activeforeground=self.col["bg"],
            relief="flat", highlightthickness=1, highlightbackground=self.col["mid"],
            cursor="hand2",
        )
        generate.pack(side="left")
        play = tk.Button(controls, text=tr("▶ LIRE"), command=self._play_voiceover,
                         bg=self.col["panel"], fg=self.col["text"], state="disabled")
        play.pack(side="left", padx=6)
        pause = tk.Button(controls, text=tr("Ⅱ PAUSE / REPRISE"), command=self._pause_voiceover,
                          bg=self.col["panel"], fg=self.col["text"], state="disabled")
        pause.pack(side="left")
        save = tk.Button(controls, text=tr("TÉLÉCHARGER WAV"), command=self._save_voiceover,
                         bg=self.col["panel"], fg=self.col["text"], state="disabled")
        save.pack(side="right")

        def finish(path, error):
            self._safe_ui(
                self._finish_voiceover, window, status, generate, play, pause, save,
                path, error,
            )

        def start_generation():
            generate.configure(state="disabled")
            for button in (play, pause, save):
                button.configure(state="disabled")
            if not self._stop_voiceover():
                self._set_voiceover_status(status, "Impossible d'arrêter l'audio précédent.")
                generate.configure(state="normal")
                return
            if self._voiceover_path:
                try:
                    Path(self._voiceover_path).unlink(missing_ok=True)
                except OSError as exc:
                    self._set_voiceover_status(status, f"Nettoyage audio impossible : {exc}")
                    generate.configure(state="normal")
                    return
            self._voiceover_path = None
            self._set_voiceover_status(status, "Envoi du texte et génération de l’audio…")
            text = text_box.get("1.0", "end-1c").strip()
            settings = {
                "voice": voice.get(),
                "language": {
                    "anglais": "English",
                    "espagnol": "español",
                    "arabe": "العربية",
                }.get(language.get(), language.get()),
                "pace": pace.get(),
                "tone": tone.get().strip() or "naturel",
            }
            self.on_voiceover_requested(
                text,
                settings,
                lambda message: self._safe_ui(self._set_voiceover_status, status, message),
                finish,
            )

        generate.configure(command=start_generation)

        def close_window():
            self._stop_voiceover()
            if self._voiceover_path:
                try:
                    Path(self._voiceover_path).unlink(missing_ok=True)
                except OSError as exc:
                    self.write_log(f"ERR: Nettoyage audio temporaire impossible : {exc}")
                self._voiceover_path = None
            self._voiceover_window = None
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close_window)
        return "break"

    @staticmethod
    def _set_voiceover_status(label, message):
        try:
            label.configure(text=message)
        except tk.TclError:
            pass

    def _finish_voiceover(self, window, status, generate, play, pause, save, path, error):
        try:
            if not window.winfo_exists():
                if path:
                    Path(path).unlink(missing_ok=True)
                return
            generate.configure(state="normal")
            if error:
                self._set_voiceover_status(status, f"Erreur : {error}")
                self.write_log(f"ERR: Génération TTS — {error}")
                return
            self._voiceover_path = path
            self._set_voiceover_status(status, f"Audio WAV prêt : {Path(path).name}")
            for button in (play, pause, save):
                button.configure(state="normal")
        except tk.TclError:
            if path:
                Path(path).unlink(missing_ok=True)

    def _mci(self, command):
        if sys.platform != "win32":
            raise RuntimeError("La lecture intégrée est disponible uniquement sous Windows.")
        import ctypes

        result = ctypes.windll.winmm.mciSendStringW(command, None, 0, 0)
        if result:
            message = ctypes.create_unicode_buffer(256)
            ctypes.windll.winmm.mciGetErrorStringW(result, message, len(message))
            raise RuntimeError(message.value or "Erreur de l’interface de contrôle multimédia de Windows.")

    def _play_voiceover(self):
        if not self._voiceover_path:
            return
        try:
            if self._voiceover_alias_open:
                self._mci("stop niangvoice")
                self._mci("close niangvoice")
            self._mci(f'open "{self._voiceover_path}" type waveaudio alias niangvoice')
            self._mci("play niangvoice")
            self._voiceover_alias_open = True
        except (OSError, RuntimeError) as exc:
            self.write_log(f"ERR: Lecture audio impossible : {exc}")

    def _pause_voiceover(self):
        try:
            if self._voiceover_alias_open:
                import ctypes
                status = ctypes.create_unicode_buffer(32)
                result = ctypes.windll.winmm.mciSendStringW(
                    "status niangvoice mode", status, len(status), 0,
                )
                if result:
                    raise RuntimeError("Impossible de lire l'état du lecteur audio.")
                command = "resume niangvoice" if status.value == "paused" else "pause niangvoice"
                self._mci(command)
            elif self._voiceover_path:
                self._play_voiceover()
        except (OSError, RuntimeError) as exc:
            self.write_log(f"ERR: Contrôle audio impossible : {exc}")

    def _stop_voiceover(self):
        if self._voiceover_alias_open:
            try:
                self._mci("stop niangvoice")
                self._mci("close niangvoice")
            except (OSError, RuntimeError) as exc:
                self.write_log(f"ERR: Arrêt audio impossible : {exc}")
                return False
            self._voiceover_alias_open = False
        return True

    def _save_voiceover(self):
        if not self._voiceover_path:
            return
        destination = filedialog.asksaveasfilename(
            parent=self.root, title="Enregistrer la voix off",
            defaultextension=".wav", initialfile="niang-voix-off.wav",
            filetypes=[("Audio WAV", "*.wav")],
        )
        if not destination:
            return
        try:
            import shutil
            shutil.copy2(self._voiceover_path, destination)
            self.write_log(f"SYS: Voix off enregistrée : {destination}")
        except OSError as exc:
            self.write_log(f"ERR: Enregistrement audio impossible : {exc}")

    def _on_stop_pressed(self):
        """Stop button: ask for confirmation, then shut NIANG IA down."""
        import tkinter.messagebox as mb
        try:
            answer = mb.askyesno(
                "Arrêter NIANG IA",
                "Voulez-vous vraiment arrêter NIANG IA ?\n\n"
                "L'écoute vocale, l'icône de la zone de notification et la "
                "session vocale seront fermées.",
                parent=self.root,
            )
        except Exception:
            answer = False
        if answer:
            self.write_log("SYS: Arrêt de NIANG IA demandé depuis l'interface.")
            self._close_application()

    def _on_close_request(self):
        """Window X button: hide to tray instead of quitting — NIANG IA keeps
        listening for the wake word. Real quit stays available via the tray
        menu, the Ctrl+Alt+Q hotkey or the 'Ferme NIANG IA' voice command."""
        if not self._api_key_ready:
            self._close_application()      # setup not done: exit for real
            return
        self.write_log(
            "SYS: Fenêtre masquée — NIANG IA reste actif en arrière-plan "
            "(icône dans la zone de notification). Dites « Réveille-toi » "
            "ou cliquez sur l'icône pour le rappeler.")
        visibility = getattr(self, "assistant_visibility", None)
        if visibility is not None:
            visibility.hide(animate=True, reason="")
            return
        self._safe_ui(self._hide_to_tray)

    def _hide_to_tray(self, step: int = 0):
        root = self.root
        value = 1.0 - (step + 1) / 10.0
        try:
            if value <= 0.02:
                root.attributes("-alpha", 1.0)
                root.withdraw()
                return
            root.attributes("-alpha", value)
        except Exception:
            root.withdraw()
            return
        root.after(18, lambda: self._hide_to_tray(step + 1))

    def _close_application(self):
        if self.on_application_close:
            try:
                self.on_application_close()
            except Exception as exc:
                self.write_log(f"ERR: Nettoyage des services agent impossible : {exc}")
        self._stop_voiceover()
        if self._voiceover_path:
            try:
                Path(self._voiceover_path).unlink(missing_ok=True)
            except OSError as exc:
                self.write_log(f"ERR: Nettoyage audio temporaire impossible : {exc}")
        os._exit(0)

    # ── Persona / connection (called from main.py) ───────────────────────────

    def set_persona(self, mode: str, mood: str, voice: str):
        self.persona_mode  = mode or "normal"
        self.persona_mood  = mood or "calm"
        self.persona_voice = voice or "Aoede"

    def set_connection(self, ok: bool):
        self.connected  = bool(ok)
        self.connecting = False

    def set_connecting(self, on: bool = True):
        self.connecting = bool(on)

    # ── Mute button ───────────────────────────────────────────────────────────

    def _build_mute_button(self):
        BTN_W, BTN_H = 110, 32
        BTN_X = 18
        BTN_Y = self.H - 70

        self._mute_canvas = tk.Canvas(
            self.root, width=BTN_W, height=BTN_H,
            bg=self.col["bg"], highlightthickness=0, cursor="hand2"
        )
        self._mute_canvas.place(x=BTN_X, y=BTN_Y)
        self._mute_canvas.bind("<Button-1>", lambda e: self._toggle_mute())
        self._draw_mute_button()

        self._silent_canvas = tk.Canvas(
            self.root, width=150, height=32,
            bg=self.col["bg"], highlightthickness=0, cursor="hand2"
        )
        self._silent_canvas.place(x=136, y=BTN_Y)
        self._silent_canvas.bind("<Button-1>", lambda e: self._toggle_silent_mode())
        self._draw_silent_button()

        self._update_button = PillButton(
            self.root, self, text=tr("↻ MISE À JOUR"),
            command=self._check_for_updates,
            font=("Segoe UI", 8, "bold"), height=32,
        )
        self._update_button.place(x=min(294, max(180, self.W - 210)), y=BTN_Y, width=140, height=32)

        # ── Stop button (visible way to shut NIANG IA down) ──────────────────
        self._stop_button = PillButton(
            self.root, self, text=tr("⏹ ARRÊTER"),
            command=self._on_stop_pressed,
            style="danger", font=("Segoe UI", 8, "bold"), height=32,
        )
        self._stop_button.place(x=max(18, self.W - 138), y=BTN_Y, width=120, height=32)

    def _draw_silent_button(self):
        c = getattr(self, "_silent_canvas", None)
        if c is None:
            return
        c.delete("all")
        active = self.silent_mode
        border = self.col["acc2"] if active else self.col["mid"]
        fill = "#06262e" if active else self.col["panel"]
        fg = self.col["acc2"] if active else self.col["text"]
        label = tr(" TEXTE SEUL") if active else tr(" VOIX ACTIVÉE")
        c.configure(bg=self.col["bg"])
        _round_poly(c, 1, 1, 149, 31, 15, outline=border, fill=fill, width=1)
        c.create_text(75, 16, text=f"▣{label}", fill=fg, font=("Segoe UI", 10, "bold"))

    def _toggle_silent_mode(self):
        self.silent_mode = not self.silent_mode
        self._draw_silent_button()
        self.set_state("TEXT-ONLY" if self.silent_mode else ("MUTED" if self.muted else "LISTENING"))
        self.write_log("SYS: Mode texte activé — NIANG IA répondra par écrit." if self.silent_mode
                       else "SYS: Sortie vocale réactivée.")

    def _draw_mute_button(self):
        c = self._mute_canvas
        c.delete("all")
        if self.muted:
            border = self.col["mutcol"]
            fill   = "#240009"
            icon   = "🔇"
            label  = tr(" MUET")
            fg     = self.col["mutcol"]
        else:
            border = self.col["mid"]
            fill   = self.col["panel"]
            icon   = "🎙"
            label  = tr(" EN DIRECT")
            fg     = self.col["green"]

        c.configure(bg=self.col["bg"])
        _round_poly(c, 1, 1, 109, 31, 15, outline=border, fill=fill, width=1)
        c.create_text(55, 16, text=f"{icon}{label}",
                      fill=fg, font=("Segoe UI", 10, "bold"))

    def _toggle_mute(self):
        self.muted = not self.muted
        self._draw_mute_button()
        if self.muted:
            self.set_state("MUTED")
            self.write_log("SYS: Microphone désactivé.")
        else:
            self.set_state("LISTENING")
            self.write_log("SYS: Microphone activé.")

    # ── Keyboard input ────────────────────────────────────────────────────────

    def _build_input_bar(self, lw: int, y: int):
        x0    = (self.W - lw) // 2
        BTN_W = 62
        CLR_W = 62
        INP_W = lw - BTN_W - CLR_W - 8

        self._input_text = tk.Text(
            self.root,
            fg=self.col["text"], bg=self.col["input"],
            insertbackground=self.col["text"],
            borderwidth=0,
            font=("Segoe UI", 10),
            wrap="word",
            height=2,
            padx=8, pady=4,
            highlightthickness=1,
            highlightbackground=self.col["inp_border"],
            highlightcolor=self.col["pri"],
        )
        self._input_text.place(x=x0, y=y, width=INP_W, height=46)
        self._input_text.bind("<Return>", self._on_input_submit)
        self._input_text.bind("<KP_Enter>", self._on_input_submit)
        self._input_text.bind("<Shift-Return>", self._on_newline)
        self._input_text.bind("<Shift-KP_Enter>", self._on_newline)
        self._input_text.bind("<Up>", self._on_hist_prev)
        self._input_text.bind("<Down>", self._on_hist_next)

        self._cmd_history = []
        self._hist_idx    = -1
        self._draft       = ""

        self._clear_btn = PillButton(
            self.root, self, text=tr("EFFACER"), command=self._on_clear_log,
            font=("Segoe UI", 9, "bold"), height=46, radius=14,
        )
        self._clear_btn.place(x=x0 + INP_W + 4, y=y, width=CLR_W, height=46)

        self._send_btn = PillButton(
            self.root, self, text=tr("ENVOYER ▸"), command=self._on_input_submit,
            style="solid", font=("Segoe UI", 9, "bold"), height=46, radius=14,
        )
        self._send_btn.place(x=x0 + INP_W + CLR_W + 8, y=y,
                             width=BTN_W, height=46)

    def _hide_main_widgets(self):
        for w in (self._left_deck, self._right_deck, self.log_frame, self._input_text,
                  self._clear_btn, self._send_btn, self._mute_canvas,
                  self._silent_canvas, self._update_button, self._stop_button):
            w.place_forget()

    def _finish_intro(self, event=None):
        """End the startup animation (called at INTRO_END, or on click / key)."""
        if self._intro_done:
            return
        T = time.time() - self._t_start
        if T < INTRO_END:
            self._t_start -= (INTRO_END - T)       # jump the clock to the final layout
        self._intro_done = True
        self._relayout()
        try:
            self._input_text.focus_set()
        except Exception:
            pass

    def _relayout(self):
        if not self._intro_done:
            return
        W, H = self.W, self.H
        is_compact = W < 900 or H < 700
        if is_compact:
            LW = max(260, int(W * 0.82))
            LH = max(70, int(H * 0.12))
            LOG_Y = max(30, H - LH - 90)
        else:
            LW = max(320, W - 440)
            LH = int(H * 0.11)
            LOG_Y = H - LH - int(H * 0.13)
        self.log_frame.place(x=(W - LW) // 2, y=LOG_Y, width=LW, height=LH)
        INPUT_Y = LOG_Y + LH + 6
        x0    = (W - LW) // 2
        BTN_W = 56 if is_compact else 62
        CLR_W = 56 if is_compact else 62
        INP_W = max(140, LW - BTN_W - CLR_W - 8)
        self._input_text.place(x=x0, y=INPUT_Y, width=INP_W, height=40 if is_compact else 46)
        self._clear_btn.place(x=x0 + INP_W + 4, y=INPUT_Y, width=CLR_W, height=40 if is_compact else 46)
        self._send_btn.place(x=x0 + INP_W + CLR_W + 8, y=INPUT_Y,
                             width=BTN_W, height=40 if is_compact else 46)
        footer_y = min(H - 38, INPUT_Y + 48)
        self._mute_canvas.place(x=18, y=footer_y)
        if getattr(self, "_silent_canvas", None) is not None:
            self._silent_canvas.place(x=136, y=footer_y)
        self._update_button.place(x=min(294, max(180, W - 210)), y=footer_y, width=126 if is_compact else 140, height=32)
        if getattr(self, "_stop_button", None) is not None:
            self._stop_button.place(x=max(18, W - 132), y=footer_y, width=114 if is_compact else 120, height=32)
        if W >= 900 and not is_compact:
            self._left_deck.place(x=16, y=96, width=184, height=max(260, H - 210))
            self._right_deck.place(x=W - 216, y=96, width=200, height=max(260, H - 210))
        else:
            self._left_deck.place_forget()
            self._right_deck.place_forget()
        if self._selected_paths:
            self._refresh_file_card()
        if self._drop_overlay.winfo_ismapped():
            self._show_drop_overlay()

    def _on_configure(self, event=None):
        if event is None or event.widget is not self.root:
            return
        if event.width == self.W and event.height == self.H:
            return
        self.W = event.width
        self.H = event.height
        self.bg.configure(width=self.W, height=self.H)
        self.FACE_SZ = min(int(self.H * 0.40), 360)
        self.FCX     = self.W // 2
        self.FCY     = int(self.H * 0.11) + self.FACE_SZ // 2
        self._relayout()

    def _get_input(self) -> str:
        return self._input_text.get("1.0", "end-1c")

    def _set_input(self, text: str):
        self._input_text.delete("1.0", tk.END)
        self._input_text.insert("1.0", text)
        self._input_text.mark_set(tk.INSERT, "end-1c")

    def _on_newline(self, event=None):
        self._input_text.insert(tk.INSERT, "\n")
        return "break"

    def _on_hist_prev(self, event=None):
        if not self._cmd_history:
            return "break"
        if self._hist_idx == -1:
            self._draft    = self._get_input()
            self._hist_idx = len(self._cmd_history)
        if self._hist_idx > 0:
            self._hist_idx -= 1
            self._set_input(self._cmd_history[self._hist_idx])
        return "break"

    def _on_hist_next(self, event=None):
        if self._hist_idx == -1:
            return "break"
        if self._hist_idx < len(self._cmd_history) - 1:
            self._hist_idx += 1
            self._set_input(self._cmd_history[self._hist_idx])
        else:
            self._hist_idx = -1
            self._set_input(self._draft)
        return "break"

    def _on_input_submit(self, event=None):
        text = self._get_input().strip()
        if not text:
            return "break"
        self._set_input("")
        self._cmd_history.append(text)
        if len(self._cmd_history) > 50:
            del self._cmd_history[0]
        self._hist_idx = -1
        self._draft    = ""
        self.write_log(f"You: {text}")
        if self.on_text_command:
            threading.Thread(
                target=self.on_text_command,
                args=(text,),
                daemon=True
            ).start()
        return "break"

    def _on_clear_log(self):
        self._safe_ui(self._clear_log)

    def _clear_log(self):
        self.typing_queue.clear()
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    # ── State management ─────────────────────────────────────────────────────

    def _safe_ui(self, fn, *args):
        """Run a UI mutation on the Tk main thread only (thread-safe)."""
        if threading.current_thread() is self._main_thread:
            return fn(*args)
        self._ui_deferred.append((fn, args))

    def set_state(self, state: str):
        hook = getattr(self, "on_state_change", None)
        if hook:
            try:
                hook(state)
            except Exception:
                pass
        self._safe_ui(self._set_state, state)

    # ── Semi-transparent background ──────────────────────────────────────────

    def set_background_alpha(self, value: float):
        """Window opacity (1.0 = opaque, 0.9 = semi-transparent hologram)."""
        try:
            alpha = max(0.55, min(1.0, float(value)))
        except (TypeError, ValueError):
            alpha = 1.0
        self._base_alpha = alpha
        self._safe_ui(self._apply_background_alpha, alpha)

    def _apply_background_alpha(self, alpha: float):
        try:
            self.root.attributes("-alpha", alpha)
        except Exception:
            pass

    # ── Voice-activation feedback (called from main.py / tray) ───────────────

    def wake_flash(self):
        """Visual burst when 'Hey Niang' / 'Niang IA' is heard."""
        self._safe_ui(self._wake_flash)

    def _wake_flash(self):
        try:
            self.pulse_r = [0.0, 0.0]      # two shockwave rings
            self.target_halo = 200.0
            self.halo_a      = 200.0
        except Exception:
            pass
        self.write_log("SYS: 🎤 Mot d’activation détecté — je vous écoute !")

    def set_mic_level(self, level: float):
        """Live microphone level (0..1) — drives the sound waves."""
        try:
            self._mic_level = max(0.0, min(1.0, float(level)))
        except (TypeError, ValueError):
            pass

    def set_mic_listening(self, on: bool):
        """Show/hide the permanent-microphone indicator."""
        self._safe_ui(self._set_mic_listening, bool(on))

    def _set_mic_listening(self, on: bool):
        self._mic_listening = bool(on)
        if (on and self._state not in ("LISTENING", "SPEAKING", "THINKING",
                                       "PROCESSING", "SLEEPING") and not self.muted):
            self._set_state("LISTENING")

    def _set_state(self, state: str):
        """
        Called from main.py.
        state: LISTENING | SPEAKING | THINKING | MUTED | ONLINE | PROCESSING | SLEEPING
        """
        self._state = state
        if state == "MUTED":
            self.status_text = "MUET"
            self.speaking    = False
        elif state == "SPEAKING":
            self.status_text = "PARLE"
            self.speaking    = True
        elif state == "THINKING":
            self.status_text = "RÉFLEXION"
            self.speaking    = False
        elif state == "LISTENING":
            self.status_text = "À L’ÉCOUTE"
            self.speaking    = False
        elif state == "PROCESSING":
            self.status_text = "TRAITEMENT"
            self.speaking    = False
        elif state == "SLEEPING":
            self.status_text = "VEILLE"
            self.speaking    = False
        else:
            self.status_text = "EN LIGNE"
            self.speaking    = False

    # ── Face loading ─────────────────────────────────────────────────────────

    def _load_face(self, path):
        FW = self.FACE_SZ
        try:
            img  = Image.open(path).convert("RGBA").resize((FW, FW), Image.LANCZOS)
            mask = Image.new("L", (FW, FW), 0)
            ImageDraw.Draw(mask).ellipse((2, 2, FW - 2, FW - 2), fill=255)
            img.putalpha(mask)
            self._face_pil = img
            self._has_face = True
        except Exception:
            self._has_face = False

    @staticmethod
    def _ac(r, g, b, a):
        f = a / 255.0
        return f"#{int(r*f):02x}{int(g*f):02x}{int(b*f):02x}"

    # ── Animation loop ───────────────────────────────────────────────────────

    def _animate(self):
        while self._ui_deferred:
            _fn, _args = self._ui_deferred.popleft()
            try:
                _fn(*_args)
            except Exception:
                pass
        self.tick += 1
        t   = self.tick
        now = time.time()

        if now - self.last_t > (0.14 if self.speaking else 0.55):
            if self.speaking:
                self.target_scale = random.uniform(1.05, 1.11)
                self.target_halo  = random.uniform(138, 182)
            elif self._state == "SLEEPING":
                # Slow breathing while dozing in the tray
                ph = (now - self._t_start) * 1.2
                self.target_scale = 1.0 + 0.014 * math.sin(ph)
                self.target_halo  = 26 + 16 * max(0.0, math.sin(ph))
            elif self.muted:
                self.target_scale = random.uniform(0.998, 1.001)
                self.target_halo  = random.uniform(20, 32)
            else:
                self.target_scale = random.uniform(1.001, 1.007)
                self.target_halo  = random.uniform(50, 68)
            self.last_t = now

        sp = 0.35 if self.speaking else 0.16
        self.scale  += (self.target_scale - self.scale) * sp
        self.halo_a += (self.target_halo  - self.halo_a) * sp

        for i, spd in enumerate([1.2, -0.8, 1.9] if self.speaking else [0.5, -0.3, 0.82]):
            self.rings_spin[i] = (self.rings_spin[i] + spd) % 360

        self.scan_angle  = (self.scan_angle  + (2.8 if self.speaking else 1.2)) % 360
        self.scan2_angle = (self.scan2_angle + (-1.7 if self.speaking else -0.68)) % 360

        pspd  = 3.8 if self.speaking else 1.8
        limit = self.FACE_SZ * 0.72
        new_p = [r + pspd for r in self.pulse_r if r + pspd < limit]
        if len(new_p) < 3 and random.random() < (0.06 if self.speaking else 0.022):
            new_p.append(0.0)
        self.pulse_r = new_p

        if t % 40 == 0:
            self.status_blink = not self.status_blink

        # Video-style HUD phases (ring arcs, dashed ring, tick marks)
        dt   = max(0.0, min(0.1, now - self._prev_now))
        self._prev_now = now
        spin = 2.2 if self.speaking else 1.0
        self._ph_arc  += dt * 0.8 * spin
        self._ph_dash += dt * 22 * spin
        self._ph_tick += dt * 0.15
        T = now - self._t_start
        if self.muted:
            tgt = 0.04
        elif self.speaking:
            tgt = 0.5 + 0.45 * abs(math.sin(T * 5.0)) + random.uniform(-0.08, 0.08)
        elif self._mic_level is not None and self._state == "LISTENING":
            # Real microphone level from the wake-word listener
            tgt = 0.15 + 0.75 * self._mic_level
        elif self._state in ("THINKING", "PROCESSING"):
            tgt = 0.35 + 0.12 * math.sin(T * 4.0)
        else:
            tgt = 0.14 + 0.05 * math.sin(T * 2.0)
        self._lv += (tgt - self._lv) * 0.25

        if not self._intro_done and T >= INTRO_END:
            self._finish_intro()
        self._draw()
        self.root.after(16, self._animate)

    # ── Battery (cached, lightweight) ─────────────────────────────────────────

    def _battery_text(self) -> str:
        now = time.time()
        if self._batt_cache is None or now - self._batt_ts > 5:
            self._batt_ts = now
            try:
                import psutil
                batt = psutil.sensors_battery()
                if batt is None:
                    self._batt_cache = None
                else:
                    self._batt_cache = int(batt.percent)
            except Exception:
                self._batt_cache = None
        if self._batt_cache is None:
            return ""
        return f"🔋 {self._batt_cache}%"

    # ── Drawing ──────────────────────────────────────────────────────────────

    # ── Video look: backdrop, text helpers ───────────────────────────────────

    def _font(self, px, weight="bold"):
        key = (int(px), weight)
        f = self._font_cache.get(key)
        if f is None:
            f = tkfont.Font(family="Segoe UI", size=-int(px), weight=weight)
            self._font_cache[key] = f
        return f

    def _spaced(self, text, x, y, px, fill, gap, weight="bold", anchor="center", tag="dyn"):
        """Letter-spaced text (the video uses wide tracking on every caption)."""
        f  = self._font(px, weight)
        ws = [f.measure(ch) for ch in text]
        tot = sum(ws) + gap * (len(text) - 1)
        xx = x - tot / 2 if anchor == "center" else (x - tot if anchor == "e" else x)
        for ch, w in zip(text, ws):
            if ch != " ":
                self.bg.create_text(xx + w / 2, y, text=ch, fill=fill, font=f, tags=tag)
            xx += w + gap
        return tot

    def _cached(self, name, key, fn):
        """Redraw a block of static canvas items only when its key changes."""
        if self._cache_keys.get(name) != key:
            self._cache_keys[name] = key
            self.bg.delete(name)
            fn()

    def _ensure_backdrop(self):
        """Radial gradient + vignette + scanlines (pre-rendered, like the video's bg())."""
        col = self.col
        if self._drag_active:
            return          # keep the current backdrop while the orb is dragged
        key = (self.W, self.H, self.FCX, self.FCY, col["pri"])
        if key == self._bd_key or self.W < 4 or self.H < 4:
            return
        self._bd_key = key
        W, H = self.W, self.H
        pri = _hex_rgb(col["pri"])
        c0 = tuple(v * 0.13 for v in pri)      # #03202a-ish centre glow
        c1 = tuple(v * 0.045 for v in pri)     # #020c12-ish mid
        half = math.hypot(W / 2, H / 2)
        step = 8
        sw, sh = max(2, W // step), max(2, H // step)
        img = Image.new("RGB", (sw, sh))
        px = []
        for yy in range(sh):
            for xx in range(sw):
                d = math.hypot((xx + .5) * step - self.FCX, (yy + .5) * step - self.FCY) / half
                if d < .55:
                    k = max(0.0, (d - .045) / .505)
                    rgb = [c0[i] + (c1[i] - c0[i]) * k for i in range(3)]
                else:
                    k = min(1.0, (d - .55) / .45)
                    rgb = [c1[i] * (1 - k) for i in range(3)]
                vg = .65 * max(0.0, min(1.0, (d - .36) / .685))
                px.append(tuple(int(v * (1 - vg)) for v in rgb))
        img.putdata(px)
        img = img.resize((W, H), Image.BILINEAR)
        mask = Image.new("L", (W, H), 0)
        md = ImageDraw.Draw(mask)
        for yy in range(0, H, 4):
            md.rectangle([0, yy, W, yy + 1], fill=14)       # scanlines, ~5 %
        img = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, mask)
        self._bd_tk = ImageTk.PhotoImage(img)
        self.bg.delete("bgimg")
        self.bg.create_image(0, 0, image=self._bd_tk, anchor="nw", tags=("bgimg",))
        self.bg.tag_lower("bgimg")

    # ── Dragging the holographic sphere ─────────────────────────────────────

    def _orb_hit(self, x: int, y: int) -> bool:
        """True when the pointer is on the orb (it can be dragged)."""
        radius = self.FACE_SZ * 0.48
        dx = x - self.FCX
        dy = y - self.FCY
        return (dx * dx + dy * dy) <= radius * radius

    def _on_orb_press(self, event):
        if not self._orb_hit(event.x, event.y):
            return
        self._drag_active = True
        self._drag_off = (event.x - self.FCX, event.y - self.FCY)
        self.bg.configure(cursor="fleur")

    def _on_orb_drag(self, event):
        if not self._drag_active:
            return
        margin = max(40, self.FACE_SZ // 3)
        self.FCX = max(margin, min(self.W - margin, event.x - self._drag_off[0]))
        self.FCY = max(margin, min(self.H - margin, event.y - self._drag_off[1]))
        self._draw()

    def _on_orb_release(self, event):
        if not self._drag_active:
            return
        self._drag_active = False
        self.bg.configure(cursor="")
        self._bd_key = None      # re-render the backdrop around the new position

    # ── Drawing ──────────────────────────────────────────────────────────────

    def _draw(self):
        c    = self.bg
        W, H = self.W, self.H
        col  = self.col
        FCX, FCY, FW = self.FCX, self.FCY, self.FACE_SZ
        T    = time.time() - self._t_start
        self._ensure_backdrop()
        c.delete("dyn")
        D = ("dyn",)

        muted = self.muted
        rgb   = col["halo_mut"] if muted else col["halo"]
        pri   = "#%02x%02x%02x" % rgb
        bgc   = col["bg"]
        clamp = lambda x, a=0.0, b=1.0: max(a, min(b, x))
        mix   = lambda k: _blend(bgc, pri, k)

        sg = lambda a_, b_: clamp((T - a_) / (b_ - a_))
        ez = lambda x: 1 - (1 - x) ** 3
        k  = H / 1080.0                 # video (1080p) → window scale
        R_rest = FW * 0.36              # resting ring radius (video: 210)
        s  = R_rest / 210.0             # line widths / tick sizes
        # Startup timeline (same as the ad): ring grows 300→500 at 2.2-3.2 s,
        # then at 5.0-5.8 s it shrinks and moves up to its resting place.
        if T < 5.0:
            R  = 300 * k + (500 - 300) * k * ez(sg(2.2, 3.2))
            ry = H / 2.0
        elif T < INTRO_END:
            kk = ez(sg(5.0, 5.8))
            R  = 500 * k + (R_rest - 500 * k) * kk
            ry = H / 2.0 + (FCY - H / 2.0) * kk
        else:
            R, ry = R_rest, FCY
        ia = sg(1.6, 2.6)               # ring fade-in

        # ── Perspective grid floor (animated, as in bg()) ────────────────────
        y0 = ry + FW * 0.18
        gcol = mix(.11)
        sx = W / 1920.0
        for i in range(14):
            z = ((i + T * .6) % 14) / 14.0
            y = y0 + (z ** 2.2) * (H - y0)
            c.create_line(0, y, W, y, fill=gcol, tags=D)
        for i in range(-14, 15):
            c.create_line(FCX + i * 40 * sx, y0, FCX + i * 260 * sx, H, fill=gcol, tags=D)

        # ── Particles converging on the ring, then orbiting ──────────────────
        pe = 1 - (1 - clamp(T / 2.0)) ** 3
        pfill = mix(.7 * clamp(T / 1.5))
        far_k = W / 1920.0
        for p in self._particles:
            r = p["far"] * far_k * (1 - pe) + (R + 70 * s + p["off"] * s) * pe
            a = p["a"] + T * p["sp"]
            x = FCX + math.cos(a) * r
            y = ry + math.sin(a) * r
            sz = p["s"] * 0.6
            c.create_oval(x - sz, y - sz, x + sz, y + sz, fill=pfill, outline="", tags=D)

        # ── Expanding pulse rings (speech) ───────────────────────────────────
        for pr in self.pulse_r:
            f = 1.0 - pr / (FW * 0.72)
            r = int(pr)
            if r > 4:
                # fade toward the local glow (not toward black) so no dark ring shows
                c.create_oval(FCX - r, ry - r, FCX + r, ry + r,
                              outline=_blend(mix(.06), pri, .55 * f * (.35 if muted else 1)),
                              width=2, tags=D)

        # ── HUD ring: circle + 3 thick arcs + dashed ring + 72 ticks ─────────
        base = mix(.06)                 # fade from the local glow, not from black
        glow = _blend(base, pri, .22 * ia)
        main = _blend(base, pri, ia)
        c.create_oval(FCX - R, ry - R, FCX + R, ry + R, outline=glow, width=6, tags=D)
        c.create_oval(FCX - R, ry - R, FCX + R, ry + R, outline=main, width=2, tags=D)

        Ra = R - 22 * s
        aw = max(3, int(round(7 * s * 1.1)))
        for i in range(3):
            a0 = self._ph_arc + i * 2.0944
            st = -math.degrees(a0 + 1.1)
            for wd, colr in ((aw + 5, glow), (aw, main)):
                c.create_arc(FCX - Ra, ry - Ra, FCX + Ra, ry + Ra, start=st,
                             extent=math.degrees(1.1), style="arc",
                             outline=colr, width=wd, tags=D)

        Rd = R + 26 * s
        c.create_oval(FCX - Rd, ry - Rd, FCX + Rd, ry + Rd, outline=main, width=1,
                      dash=(3, 9), dashoffset=int(self._ph_dash), tags=D)

        t_in = R + 50 * s
        for i in range(72):
            a = i / 72 * math.tau + self._ph_tick
            ln = 20 * s if i % 6 == 0 else 8 * s
            ca, sa = math.cos(a), math.sin(a)
            c.create_line(FCX + ca * t_in, ry + sa * t_in,
                          FCX + ca * (t_in + ln), ry + sa * (t_in + ln),
                          fill=main, width=1, tags=D)

        # ── Orb: glow + 96 radial waveform bars + core (video orb()) ─────────
        oa = sg(5.2, 5.9)
        if oa > 0:
            lv = self._lv
            r0 = R * .55 * self.scale
            for i in range(8, 0, -1):
                rr = R * .6 * i / 8
                c.create_oval(FCX - rr, ry - rr, FCX + rr, ry + rr,
                              fill=mix(.55 * (1 - i / 8) * oa), outline="", tags=D)
            bw = max(2, int(round(5 * s * 1.1)))
            bar = _blend(mix(.06), pri, oa)
            N = 96
            for i in range(N):
                a = i / N * math.tau
                w = (math.sin(a * 3 + T * 6) + math.sin(a * 5 - T * 4) * .7
                     + math.sin(a * 9 + T * 9) * .4)
                L = 3 + abs(w) * lv * R * .2
                ca, sa = math.cos(a), math.sin(a)
                c.create_line(FCX + ca * r0, ry + sa * r0,
                              FCX + ca * (r0 + L), ry + sa * (r0 + L),
                              fill=bar, width=bw, capstyle="round", tags=D)
            ri = r0 - 12 * s
            c.create_oval(FCX - ri, ry - ri, FCX + ri, ry + ri, outline=bar, width=2, tags=D)
            cr = (10 + lv * 10) * s * 1.2 * self.scale
            c.create_oval(FCX - cr - 4, ry - cr - 4, FCX + cr + 4, ry + cr + 4,
                          fill=mix(.35 * oa), outline="", tags=D)
            c.create_oval(FCX - cr, ry - cr, FCX + cr, ry + cr,
                          fill="#eaffff" if not muted else "#ffdde2", outline="", tags=D)

        # ── Startup: "INITIALISATION…" + 0→100 % counter (video scene A) ─────
        if T < 2.4:
            aA = min(clamp(T / 0.4), 1 - clamp((T - 2.0) / 0.4))
            if aA > 0:
                blink = 0.6 + 0.4 * math.sin(T * 14)
                self._spaced("INITIALISATION…", W / 2, H - 170 * k, max(12, int(26 * k)),
                             mix(aA * blink), 10 * k, weight="normal")
                pf = self._font(int(120 * k), "normal")
                pct = f"{int(sg(0.2, 2.1) * 100)}%"
                for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                    c.create_text(W / 2 + dx, ry + dy, text=pct, font=pf, tags=D,
                                  fill=mix(.28 * aA))
                c.create_text(W / 2, ry, text=pct, font=pf, tags=D,
                              fill=_blend(bgc, "#eaffff", aA))
        # intro subtitle (centre), fades out as the layout moves up
        if T < 5.4:
            aS = min(sg(3.5, 3.9), 1 - sg(5.0, 5.4))
            if aS > 0:
                self._spaced("ASSISTANT VOCAL INTELLIGENT", W / 2, H / 2 + 110 * k,
                             max(11, int(26 * k)), mix(aS), 14 * k, weight="normal")

        # ── Logo "NIANG IA": letter-by-letter reveal with chromatic glitch ───
        def draw_logo():
            px_rest = int(clamp(H * 0.045, 24, 40))
            kk2 = ez(sg(5.0, 5.8))
            px = int(130 * k + (px_rest - 130 * k) * kk2)
            f = self._font(px, "bold")
            L = "NIANG IA"
            gap = px * .16
            ws = [f.measure(ch) for ch in L]
            tot = sum(ws) + gap * (len(L) - 1)
            x = W / 2 - tot / 2
            ly = H / 2.0 + (38 - H / 2.0) * kk2
            for i, ch in enumerate(L):
                k0 = 2.5 + i * .09
                u = clamp((T - k0) / .35)
                if u > 0 and ch != " ":
                    cx_ = x + ws[i] / 2
                    if 0 < T - k0 < .3:                      # glitch frame
                        c.create_text(cx_ - 3, ly + 1, text=ch, font=f, tags="logo",
                                      fill=_blend(bgc, col["scan2"], .6))
                        c.create_text(cx_ + 3, ly - 1, text=ch, font=f, tags="logo",
                                      fill=_blend(bgc, col["pri"], .6))
                    for dx, dy in ((-1.5, 0), (1.5, 0), (0, -1.5), (0, 1.5)):
                        c.create_text(cx_ + dx, ly + dy, text=ch, font=f, tags="logo",
                                      fill=_blend(bgc, col["pri"], .30 * u))
                    c.create_text(cx_, ly, text=ch, font=f, tags="logo",
                                  fill=_blend(bgc, "#eaffff", u))
                x += ws[i] + gap
            if H >= 640:
                sa_ = clamp((T - 5.4) / 0.8)
                if sa_ > 0:
                    sub_px = 11
                    self._spaced("ASSISTANT VOCAL INTELLIGENT", W / 2, ly + px / 2 + 16,
                                 sub_px, _blend(bgc, col["pri"], .85 * sa_), 5,
                                 weight="normal", tag="logo")
        self._cached("logo", (W, H, col["pri"], bgc, True if T > INTRO_END + 0.9 else round(T * 40)), draw_logo)

        # ── HUD corners (video: "NIANG//IA  v1.0" / REC) ─────────────────────
        self._cached("hud_tl", (W, col["pri"]), lambda: self._spaced(
            "NIANG//IA  v1.0", 24, 18, 11, _blend(bgc, col["pri"], .6), 3,
            weight="normal", anchor="w", tag="hud_tl"))

        c.create_text(W - 24, 18, text=time.strftime("%H:%M:%S"),
                      fill=col["pri"], font=("Segoe UI", 11, "bold"), anchor="e", tags=D)
        if self.connecting:
            conn_txt, conn_col = "◌ CONNEXION…", col["acc2"]
        elif self.connected:
            conn_txt, conn_col = ("● " if self.status_blink else "○ ") + "EN LIGNE", col["green"]
        else:
            conn_txt, conn_col = "○ HORS LIGNE", col["red"]
        c.create_text(W - 24, 40, text=conn_txt, fill=conn_col,
                      font=("Segoe UI", 8, "bold"), anchor="e", tags=D)
        if T < INTRO_END:
            for _name in ("logo", "hud_tl"):
                c.tag_raise(_name)
            return
        persona_mode = {"normal": "NORMAL"}.get(self.persona_mode.lower(), self.persona_mode.upper())
        persona_mood = {"calm": "CALME"}.get(self.persona_mood.lower(), self.persona_mood.upper())
        badge = f"◈ {persona_mode} · {persona_mood} · {self.persona_voice}"
        c.create_text(24, 40, text=badge, fill=col["acc2"],
                      font=("Segoe UI", 8, "bold"), anchor="w", tags=D)

        # ── Status caption (wide tracking, like "INITIALISATION…") ───────────
        sy = FCY + FW // 2 + 45
        if self.muted:
            stat, sc = "⊘ MUET", col["mutcol"]
        elif self.speaking:
            stat, sc = "● PARLE", col["text"]
        elif self._state == "THINKING":
            stat, sc = ("◈" if self.status_blink else "◇") + " RÉFLEXION", col["acc2"]
        elif self._state == "PROCESSING":
            stat, sc = ("▷" if self.status_blink else "▶") + " TRAITEMENT", col["acc2"]
        elif self._state == "LISTENING":
            stat, sc = ("●" if self.status_blink else "○") + " À L’ÉCOUTE", col["green"]
        else:
            stat, sc = ("●" if self.status_blink else "○") + f" {self.status_text}", col["pri"]
        self._cached("status", (stat, sc, W, sy), lambda: self._spaced(
            stat, W / 2, sy, 13, sc, 6, weight="bold", tag="status"))

        # ── Mic-active indicator (permanent listening) ───────────────────────
        if self._mic_listening:
            mic_col = col["green"] if self.status_blink else col["acc2"]
            mic_txt = "🎤 micro actif — dites « Hey Niang »"
            c.create_text(W - 24, 60, text=mic_txt, fill=mic_col,
                          font=("Segoe UI", 8, "bold"), anchor="e", tags=D)

        for _name in ("logo", "hud_tl", "status"):
            c.tag_raise(_name)

        # ── Footer (no band: the video is full-bleed) ────────────────────────
        if self.last_event:
            lim = 56 if W >= 900 else 34
            ev = self.last_event if len(self.last_event) <= lim else self.last_event[:lim - 3] + "..."
            c.create_text(W - 16, H - 30, text=ev, fill=col["mid"],
                          font=("Segoe UI", 8), anchor="e", tags=D)
        batt = self._battery_text()
        hints = "  ".join(x for x in [batt, "[F4] SON", "[F5] THÈME"] if x)
        c.create_text(W - 16, H - 12, text=hints, fill=col["mid"],
                      font=("Segoe UI", 8), anchor="e", tags=D)
        c.create_text(16, H - 12, text=f"NIANG//IA · {THEMES[self._theme]['name']}",
                      fill=col["mid"], font=("Segoe UI", 8), anchor="w", tags=D)

    # ── Log ───────────────────────────────────────────────────────────────────

    def write_log(self, text: str):
        self._safe_ui(self._write_log, text)

    def _write_log(self, text: str):
        self.typing_queue.append(text)
        stripped = text
        for prefix in ("[Guardian]", "[Monitor]", "[Email]", "⏰", "SYS:"):
            if text.startswith(prefix):
                stripped = text[len(prefix):].strip(" :")
                break
        self.last_event = stripped or self.last_event
        tl = text.lower()
        if tl.startswith("you:"):
            self.set_state("PROCESSING")
        elif tl.startswith("kaizumi:") or tl.startswith("ai:"):
            self.set_state("SPEAKING")
        if not self.is_typing:
            self._start_typing()

    def _start_typing(self):
        if not self.typing_queue:
            self.is_typing = False
            if not self.speaking and not self.muted:
                self.set_state("LISTENING")
            return
        self.is_typing = True
        text = self.typing_queue.popleft()
        tl   = text.lower()
        label = None
        if tl.startswith("you:"):
            tag, label, text = "you", "VOUS", text[4:].lstrip()
        elif tl.startswith("kaizumi:") or tl.startswith("ai:"):
            tag, label, text = "ai", "NIANG IA", text.split(":", 1)[1].lstrip()
        elif tl.startswith("err:"):
            tag, text = "err", "ERREUR :" + text[4:]
        elif "error" in tl or "failed" in tl:
            tag = "err"
        elif tl.startswith("sys:"):
            tag, text = "sys", "SYSTÈME :" + text[4:]
        else:
            tag = "sys"
        self.log_text.configure(state="normal")
        if label:
            self.log_text.insert(tk.END, label + "  ", "lbl_" + tag)
        self._type_char(text, 0, tag)

    def _type_char(self, text, i, tag):
        if i < len(text):
            self.log_text.insert(tk.END, text[i], tag)
            self.log_text.see(tk.END)
            self.root.after(8, self._type_char, text, i + 1, tag)
        else:
            self.log_text.insert(tk.END, "\n")
            self.log_text.configure(state="disabled")
            self.root.after(25, self._start_typing)

    # ── Legacy compat methods (main.py may still call them) ──────────────────

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted and not self.silent_mode:
            self.set_state("LISTENING")

    # ── API key ───────────────────────────────────────────────────────────────

    def _api_keys_exist(self):
        """Check all supported Gemini key sources without exposing key values."""
        if os.environ.get("KAIZUMI_GEMINI_API_KEY", "").strip():
            return True
        if os.environ.get("KAIZUMI_GEMINI_API_KEYS", "").strip():
            return True
        try:
            if INSTALLER_API_KEY_FILE.read_text(encoding="utf-8").strip():
                return True
        except FileNotFoundError:
            pass
        try:
            cfg = json.loads(API_FILE.read_text(encoding="utf-8"))
        except Exception:
            return False
        if isinstance(cfg.get("gemini_api_key"), str) and cfg["gemini_api_key"].strip():
            return True
        keys = cfg.get("gemini_api_keys")
        return bool(isinstance(keys, list) and
                    any(isinstance(k, str) and k.strip() for k in keys))

    def wait_for_api_key(self):
        while not self._api_key_ready:
            time.sleep(0.1)

    def _show_setup_ui(self):
        self._finish_intro()
        col = self.col
        self.setup_frame = tk.Frame(
            self.root, bg=col["panel"],
            highlightbackground=col["pri"], highlightthickness=1
        )
        self.setup_frame.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(self.setup_frame, text="◈  INITIALISATION REQUISE",
                 fg=col["pri"], bg=col["panel"],
                 font=("Segoe UI", 13, "bold")).pack(pady=(20, 4), padx=34)
        tk.Label(self.setup_frame,
                 text="Saisissez votre clé d’API Gemini pour démarrer NIANG IA.",
                 fg=col["acc2"], bg=col["panel"],
                 font=("Segoe UI", 9)).pack(pady=(0, 10))

        tk.Label(self.setup_frame, text="CLÉ D’API GEMINI",
                 fg=col["mid"], bg=col["panel"],
                 font=("Segoe UI", 8, "bold")).pack(pady=(8, 3))
        self.gemini_entry = tk.Entry(
            self.setup_frame, width=52, fg=col["text"],
            bg=col["input"],
            insertbackground=col["text"], borderwidth=0,
            highlightthickness=1, highlightbackground=col["inp_border"],
            highlightcolor=col["pri"],
            font=("Segoe UI", 10), show="*"
        )
        self.gemini_entry.pack(pady=(0, 4), padx=34, ipady=6)

        PillButton(
            self.setup_frame, self, text=tr("DÉMARRER LE SYSTÈME  ▸"),
            command=self._save_api_keys, style="solid",
            font=("Segoe UI", 10, "bold"), height=44, width=260,
        ).pack(pady=(16, 22))

    def _save_api_keys(self):
        gemini = self.gemini_entry.get().strip()
        if not gemini:
            return
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(API_FILE, "w", encoding="utf-8") as f:
            json.dump({"gemini_api_key": gemini}, f, indent=4)
        self.setup_frame.destroy()
        self._api_key_ready = True
        self.set_state("LISTENING")
        self.write_log("SYS: Système initialisé. NIANG IA est en ligne.")

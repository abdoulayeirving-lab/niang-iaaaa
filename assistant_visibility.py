# assistant_visibility.py
# NIANG IA — window visibility / assistant presence controller.
#
# Wraps every show/hide/quit transition behind Tk `after` marshalling so
# any thread (wake-word listener, tray menu, voice tools, hotkeys) can
# drive the interface without blocking the Tk main loop or racing it.
#
#   show()   -> restore + fade-in + brief topmost + focus  (wake word)
#   hide()   -> fade-out + withdraw                        ("Dors Niang")
#   confirm_quit() -> confirmation dialog, then full shutdown

import threading

FADE_STEPS = 10            # frames per fade
FADE_DELAY_MS = 18         # ~180 ms total
TOPMOST_RELEASE_MS = 1200  # keep the window on top this long after a wake


class AssistantVisibility:

    def __init__(self, ui):
        self.ui = ui
        self._fade_job = None
        self._topmost_job = None
        # Cached presence flag: reading the Tk window state from another
        # thread deadlocks the interpreter, so we never call Tk here.
        self._hidden = False

    # ── Queries ──────────────────────────────────────────────────────────────

    def is_hidden(self) -> bool:
        """True when the interface is withdrawn (thread-safe, no Tk call)."""
        return bool(self._hidden)

    # ── Show (wake / reveal) ─────────────────────────────────────────────────

    def show(self, animate: bool = True, on_top: bool = True, reason: str = ""):
        """Restore the interface, fade it in and bring it to the foreground."""
        self.ui._safe_ui(self._show_on_ui, animate, on_top, reason)

    def _show_on_ui(self, animate: bool, on_top: bool, reason: str):
        root = self.ui.root
        was_hidden = self._hidden
        self._hidden = False
        try:
            if getattr(self.ui, "_mic_listening", False):
                self.ui.set_state("LISTENING")
        except Exception:
            pass
        try:
            if root.state() == "iconic":
                root.deiconify()
            elif was_hidden:
                root.deiconify()
        except Exception:
            pass
        try:
            self.ui._finish_intro()          # skip the intro if it is still running
        except Exception:
            pass
        self._cancel_fade()
        if animate and was_hidden:
            try:
                root.attributes("-alpha", 0.0)
            except Exception:
                animate = False
        try:
            root.lift()
        except Exception:
            pass
        if on_top:
            try:
                root.attributes("-topmost", True)
                if self._topmost_job:
                    try:
                        root.after_cancel(self._topmost_job)
                    except Exception:
                        pass
                self._topmost_job = root.after(
                    TOPMOST_RELEASE_MS, self._release_topmost)
            except Exception:
                pass
        try:
            root.focus_force()
        except Exception:
            pass
        if animate:
            self._fade_in()
        if reason:
            self.ui.write_log(f"SYS: {reason}")

    def _release_topmost(self):
        self._topmost_job = None
        try:
            self.ui.root.attributes("-topmost", False)
        except Exception:
            pass

    def _base_alpha(self) -> float:
        """Window opacity set by the user (1.0 = opaque)."""
        try:
            return float(getattr(self.ui, "_base_alpha", 1.0))
        except Exception:
            return 1.0

    def _fade_in(self, step: int = 0):
        root = self.ui.root
        value = self._base_alpha() * (step + 1) / FADE_STEPS
        try:
            root.attributes("-alpha", min(self._base_alpha(), value))
        except Exception:
            return
        if step + 1 < FADE_STEPS:
            self._fade_job = root.after(
                FADE_DELAY_MS, lambda: self._fade_in(step + 1))
        else:
            self._fade_job = None

    # ── Hide (sleep / reduce) ────────────────────────────────────────────────

    def hide(self, animate: bool = True, reason: str = ""):
        """Fade the interface out and keep only the tray icon + listeners."""
        self.ui._safe_ui(self._hide_on_ui, animate, reason)

    def _hide_on_ui(self, animate: bool, reason: str):
        root = self.ui.root
        if self._hidden:
            return
        self._hidden = True
        self._cancel_fade()
        try:
            self.ui.set_state("SLEEPING")
        except Exception:
            pass
        if reason:
            self.ui.write_log(f"SYS: {reason}")
        if animate:
            try:
                root.attributes("-alpha", self._base_alpha())
                self._fade_out()
                return
            except Exception:
                pass
        self._withdraw_now()

    def _fade_out(self, step: int = 0):
        root = self.ui.root
        base = self._base_alpha()
        value = base * (1.0 - (step + 1) / FADE_STEPS)
        try:
            if value <= 0.02 * base:
                self._withdraw_now()
                return
            root.attributes("-alpha", value)
        except Exception:
            self._withdraw_now()
            return
        self._fade_job = root.after(FADE_DELAY_MS, lambda: self._fade_out(step + 1))

    def _withdraw_now(self):
        self._fade_job = None
        try:
            self.ui.root.attributes("-alpha", self._base_alpha())
        except Exception:
            pass
        try:
            self.ui.root.withdraw()          # out of the taskbar too
        except Exception:
            pass

    def _cancel_fade(self):
        if self._fade_job:
            try:
                self.ui.root.after_cancel(self._fade_job)
            except Exception:
                pass
            self._fade_job = None

    # ── Quit with confirmation ───────────────────────────────────────────────

    def confirm_quit(self, reason: str = ""):
        """Ask before leaving NIANG IA completely (never instant)."""
        self.ui._safe_ui(self._confirm_quit_on_ui, reason)

    def _confirm_quit_on_ui(self, reason: str):
        import tkinter.messagebox as mb
        if reason:
            self.ui.write_log(f"SYS: {reason}")
        if self.is_hidden():
            self.show(animate=False, on_top=False)
        answer = mb.askyesno(
            "Quitter NIANG IA",
            "Voulez-vous vraiment quitter NIANG IA ?\n"
            "L'écoute vocale et la veille seront désactivées.\n\n"
            "« Non » garde NIANG IA en arrière-plan.",
        )
        if answer:
            self.shutdown()

    def shutdown(self):
        """Full, clean exit (stops listeners and services first)."""
        self.ui._safe_ui(self._shutdown_on_ui)

    def _shutdown_on_ui(self):
        try:
            self.ui.on_application_close and self.ui.on_application_close()
        except Exception:
            pass
        try:
            self.ui.root.destroy()
        except Exception:
            pass
        import os
        os._exit(0)

    # ── Immediate voice stop (no confirmation) ──────────────────────────────

    def stop_now(self, reason: str = "", delay_ms: int = 3000):
        """Stop NIANG IA completely and immediately (voice command).

        The delay lets Gemini finish the farewell sentence before the
        process exits, so the assistant is not cut off mid-word.
        """
        self.ui._safe_ui(self._stop_now_on_ui, reason, delay_ms)

    def _stop_now_on_ui(self, reason: str, delay_ms: int):
        root = self.ui.root
        if reason:
            try:
                self.ui.write_log(f"SYS: {reason}")
            except Exception:
                pass

        def finish():
            try:
                self.ui.on_application_close and self.ui.on_application_close()
            except Exception:
                pass
            try:
                root.destroy()
            except Exception:
                pass
            import os
            os._exit(0)

        try:
            root.after(max(0, int(delay_ms)), finish)
        except Exception:
            finish()


def handle_visibility_command(args, kaizumi, voice) -> str:
    """Voice-tool entry point: show | hide | sleep | quit | status."""
    action = str((args or {}).get("action", "status")).strip().lower()
    visibility = kaizumi.visibility
    if action in ("show", "réveille-toi", "reveille-toi", "wake"):
        visibility.show(reason="Interface affichée sur demande vocale.")
        return "Interface affichée. Je vous écoute."
    if action in ("hide", "sleep", "dors", "dors niang", "réduis-toi", "reduis-toi"):
        visibility.hide(reason="Interface masquée sur demande vocale — veille active.")
        return ("Je vais dormir. L'icône reste dans la zone de notification et "
                "l'écoute vocale continue : dites « Réveille-toi » (ou cliquez "
                "sur l'icône) pour me rappeler.")
    if action in ("stop", "arrête", "arrete", "arrêter", "arrête-toi", "arrete-toi",
                  "arrête niang", "arrête niang ia", "éteins", "eteins",
                  "éteins-toi", "eteins-toi", "coupe tout", "coupe-toi",
                  "stoppe"):
        # Immediate and complete: the voice command alone stops NIANG IA.
        visibility.stop_now("Arrêt complet demandé par commande vocale.")
        return "D'accord, j'arrête. Bonne soirée !"
    if action in ("quit", "quitte", "ferme niang ia", "ferme niang",
                  "ferme niang ia"):
        visibility.confirm_quit("Fermeture demandée par commande vocale.")
        return ("Je vous demande une confirmation à l'écran pour arrêter "
                "complètement NIANG IA.")
    if action in ("status", "état", "etat"):
        engine = getattr(voice, "status", lambda: "inconnu")()
        state = "masquée (veille)" if visibility.is_hidden() else "affichée"
        return f"Interface {state}. Écoute vocale : {engine}."
    return "Action inconnue. Utilisez : show | hide | sleep | quit | status."


def _self_test():
    """Smoke test without the full app: a bare Tk root + fake UI."""
    import tkinter as tk
    import time as _time

    class FakeUI:
        def __init__(self):
            self.root = tk.Tk()
            self.root.geometry("220x120+60+60")
            self.logs = []

        def _safe_ui(self, fn, *a):
            fn(*a)

        def _finish_intro(self):
            pass

        def write_log(self, msg):
            self.logs.append(msg)

    fake = FakeUI()
    vis = AssistantVisibility(fake)
    assert not vis.is_hidden()
    vis.hide(animate=False)
    assert vis.is_hidden()
    vis.show(animate=False)
    assert not vis.is_hidden()
    fake.root.attributes("-alpha", 0.0)
    vis._fade_in()
    deadline = _time.time() + 2
    while _time.time() < deadline and fake.root.attributes("-alpha") < 0.99:
        fake.root.update()
        _time.sleep(0.02)
    assert fake.root.attributes("-alpha") > 0.95, "fade-in incomplete"
    print("assistant_visibility self-test OK")
    fake.root.destroy()


if __name__ == "__main__":
    _self_test()

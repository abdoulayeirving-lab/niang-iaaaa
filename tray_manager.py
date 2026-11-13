# tray_manager.py
# NIANG IA — system tray integration.
#
# Extends actions/system_tray (pystray + keyboard are optional deps there)
# with the assistant-presence menu:
#   · left-click on the icon  -> show the interface (default item)
#   · "Dors (masquer)"        -> hide to tray, keep listening
#   · wake-word toggle        -> enable/disable permanent listening
#   · "Démarrage en arrière-plan" toggle (persisted, applied at next start)
#   · "Quitter…"              -> confirmation, then a clean shutdown
# The window never opens a second instance: the mutex in main.py still runs.

import threading


def _ui_call(ui, fn, *args):
    """Marshal any callback onto the Tk thread."""
    def runner():
        try:
            fn(*args)
        except Exception as exc:
            print(f"[Tray] ⚠️ {exc}")
    try:
        ui.root.after(0, runner)
    except Exception:
        runner()


def _background(fn, *args):
    """Run a blocking callback off the keyboard-hook thread.

    The `keyboard` library dispatches hotkeys on its listener thread; if that
    thread blocks (e.g. waiting for the mic thread to join) Windows silently
    drops the low-level hook and every shortcut stops working.
    """
    import threading

    def runner():
        try:
            fn(*args)
        except Exception as exc:
            print(f"[Tray] ⚠️ {exc}")

    threading.Thread(target=runner, daemon=True, name="TrayAction").start()


def attach(kaizumi, visibility, voice) -> bool:
    """Build the tray menu + global hotkeys. Returns True when the tray is on."""
    ui = kaizumi.ui
    try:
        from actions import system_tray
        import pystray
    except Exception as exc:
        print(f"[Tray] ⚠️ pystray indisponible: {exc}")
        return False

    def wake_running() -> bool:
        return voice._engine is not None and voice._engine.running

    def toggle_wake():
        print("[Tray] raccourci ctrl+alt+w reçu")
        try:
            # Never block the keyboard-hook thread: engine.stop() joins the mic
            # thread and Windows drops the low-level hook if we stall here.
            _background(_toggle_wake_impl)
        except Exception as exc:
            print(f"[Tray] ⚠️ {exc}")

    def _toggle_wake_impl():
        voice.toggle()
        ui.write_log(f"SYS: Écoute vocale — {voice.status()}")

    def toggle_mute():
        print("[Tray] raccourci ctrl+alt+m reçu")
        _ui_call(ui, ui._toggle_mute)

    def show_window():
        print("[Tray] affichage de l'interface")
        _ui_call(ui, visibility.show, True, True, "")

    def hide_window():
        print("[Tray] masquage de l'interface")
        _ui_call(ui, visibility.hide, True, "Interface masquée — NIANG IA reste en veille (icône + écoute vocale).")

    def hide_show():
        print("[Tray] raccourci ctrl+alt+h reçu")
        # Everything that touches Tk must run on the Tk thread: calling Tk from
        # the keyboard-hook thread deadlocks it and Windows then drops the
        # low-level hook (all shortcuts stop working).
        def action():
            if visibility.is_hidden():
                show_window()
            else:
                hide_window()
        _ui_call(ui, action)

    def toggle_start_hidden():
        try:
            from voice_activation import load_settings, update_setting
            current = load_settings().get("start_hidden", False)
            update_setting("start_hidden", not current)
            state = "activé" if not current else "désactivé"
            ui.write_log(f"SYS: Démarrage en arrière-plan {state} (appliqué au prochain lancement).")
        except Exception as exc:
            print(f"[Tray] ⚠️ {exc}")

    def toggle_transparency():
        try:
            from voice_activation import load_settings, update_setting
            current = load_settings().get("background_alpha", 1.0)
            new_value = 1.0 if float(current) < 1.0 else 0.88
            update_setting("background_alpha", new_value)
            ui.set_background_alpha(new_value)
            state = "semi-transparent" if new_value < 1.0 else "opaque"
            ui.write_log(f"SYS: Fond de l'interface : {state}.")
        except Exception as exc:
            print(f"[Tray] ⚠️ {exc}")

    def briefing():
        try:
            if kaizumi._loop and kaizumi.session:
                kaizumi.speak("Give me today's morning briefing.")
        except Exception as exc:
            print(f"[Tray] ⚠️ {exc}")

    def quit_app():
        _ui_call(ui, visibility.confirm_quit, "Fermeture demandée depuis la zone de notification.")

    def menu_factory():
        start_hidden = False
        try:
            from voice_activation import load_settings
            start_hidden = load_settings().get("start_hidden", False)
        except Exception:
            pass

        def _alpha() -> float:
            try:
                from voice_activation import load_settings
                return float(load_settings().get("background_alpha", 1.0))
            except Exception:
                return 1.0
        return pystray.Menu(
            pystray.MenuItem(
                "🔊  Afficher NIANG IA",
                show_window,
                default=True,        # left-click on the tray icon
            ),
            pystray.MenuItem(
                lambda item: "🔇  Réactiver le son" if ui.muted else "🔈  Couper le son (F4)",
                toggle_mute,
            ),
            pystray.MenuItem(
                "🌙  Dors (masquer l'interface)",
                hide_window,
            ),
            pystray.MenuItem(
                lambda item: ("🛑  Arrêter l'écoute vocale" if wake_running()
                              else "🎤  Activer l'écoute vocale"),
                toggle_wake,
            ),
            pystray.MenuItem(
                lambda item: ("✅  Démarrage en arrière-plan" if start_hidden
                              else "⬜  Démarrage en arrière-plan"),
                toggle_start_hidden,
            ),
            pystray.MenuItem(
                lambda item: ("🪟  Fond semi-transparent" if _alpha() < 1.0
                              else "🪟  Fond opaque"),
                toggle_transparency,
            ),
            pystray.MenuItem("📋  Résumé du jour", briefing),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⏹  ARRÊTER NIANG IA…", quit_app),
        )

    tray_ok = system_tray.configure_icon(menu_factory)

    hotkeys = {
        "toggle_mute": toggle_mute,
        "toggle_wake": toggle_wake,
        "hide_show":   hide_show,
        "briefing":    briefing,
        "quit":        quit_app,
    }
    hot_ok = system_tray.register_hotkeys(hotkeys)
    print(f"[Tray] Icône : {'on' if tray_ok else 'off'} | Raccourcis : {hot_ok} "
          f"({system_tray.available()})")
    return tray_ok

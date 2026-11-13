# voice_launcher.py
# NIANG IA — voice launcher: starts NIANG IA when "Hey Niang" is heard,
# even when the assistant is not running at all.
#
# This is a small, headless companion process:
#   · it never creates a second NIANG IA interface (the single-instance mutex
#     of main.py is checked, never acquired);
#   · it listens locally for the wake word (same engines as the app);
#   · when the wake word is heard and NIANG IA is not running, it starts
#     NIANG IA with --wake so the interface appears immediately with the
#     blue screen-edge effect;
#   · as soon as NIANG IA is up, the launcher quits by itself.
#
# Launch it manually with:   python voice_launcher.py
# or register it at login with the "autostart" tool (background = launcher).

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MUTEX_NAME = "Local\\NIANG_IA_SINGLE_INSTANCE_MUTEX"
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
SYNCHRONIZE = 0x00100000

# How long we wait before checking whether NIANG IA is already running
# (gives the normal autostart entry time to take over).
STARTUP_GRACE = 6.0


def niang_is_running() -> bool:
    """True when NIANG IA already holds its single-instance mutex."""
    try:
        handle = ctypes.windll.kernel32.OpenMutexW(SYNCHRONIZE, False, MUTEX_NAME)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
    except Exception:
        pass
    return False


def launch_niang(wake: bool = True) -> bool:
    """Start NIANG IA (detached, no console window)."""
    main_py = BASE_DIR / "main.py"
    if not main_py.is_file():
        return False
    pyw = Path(sys.executable).with_name("pythonw.exe")
    if not pyw.exists():
        pyw = Path(sys.executable)
    cmd = [str(pyw), "-u", str(main_py)]
    if wake:
        cmd.append("--wake")
    flags = CREATE_NO_WINDOW
    if os.name == "nt":
        flags |= DETACHED_PROCESS
    try:
        subprocess.Popen(cmd, cwd=str(BASE_DIR), creationflags=flags,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True)
        return True
    except Exception as exc:
        print(f"[VoiceLauncher] ⚠️ démarrage impossible : {exc}")
        return False


def _listener(on_detect):
    """Start the local wake-word listener (same engines as the app)."""
    try:
        from voice_activation import voice_activation
    except Exception as exc:
        print(f"[VoiceLauncher] ⚠️ voice_activation indisponible : {exc}")
        return None
    voice_activation._on_detect = on_detect
    try:
        voice_activation.start()
    except Exception as exc:
        print(f"[VoiceLauncher] ⚠️ écoute impossible : {exc}")
        return None
    return voice_activation


def main(grace: float = None) -> int:
    if grace is None:
        try:
            grace = float(os.environ.get("NIANG_LAUNCHER_GRACE", STARTUP_GRACE))
        except (TypeError, ValueError):
            grace = STARTUP_GRACE
    print("[VoiceLauncher] démarrage…")
    time.sleep(grace)

    if niang_is_running():
        print("[VoiceLauncher] NIANG IA est déjà lancé — le lanceur se ferme.")
        return 0

    print("[VoiceLauncher] en veille — dites « Hey Niang » pour lancer NIANG IA.")
    launched = {"done": False}

    def on_detect():
        if launched["done"]:
            return
        launched["done"] = True
        print("[VoiceLauncher] ✓ « Hey Niang » détecté — lancement de NIANG IA…")
        launch_niang(wake=True)

    listener = _listener(on_detect)
    if listener is None:
        return 1

    try:
        while not launched["done"]:
            time.sleep(0.3)
            if niang_is_running():
                break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            listener.stop()
        except Exception:
            pass
    print("[VoiceLauncher] NIANG IA est en ligne — le lanceur se ferme.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

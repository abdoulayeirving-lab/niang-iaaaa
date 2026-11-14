# actions/autostart.py
# Kaizumi — start automatically on Windows login (HKCU Run key)

import sys
import winreg
from pathlib import Path

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
TASK_NAME    = "Kaizumi"
# Older installs registered the entry under another name — reuse whichever
# one already exists instead of creating a second (double launch at login).
KNOWN_TASK_NAMES = ("NIANG IA", "Kaizumi")
# Separate entry for the voice launcher (starts NIANG IA on "Hey Niang"
# even when the assistant is not running).
LAUNCHER_TASK_NAME = "NIANG IA Voice Launcher"


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _launch_command(remote: bool, background: bool = False) -> str:
    base   = get_base_dir()
    script = base / "START_NIANG_IA.vbs"
    cmd = f'wscript.exe "{script}"'
    if remote:
        cmd += " --remote"
    if background:
        cmd += " --background"
    return cmd


def _existing_task_name() -> str | None:
    """Name of the Run entry that already exists (if any)."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
            for name in KNOWN_TASK_NAMES:
                try:
                    winreg.QueryValueEx(key, name)
                    return name
                except FileNotFoundError:
                    continue
    except FileNotFoundError:
        return None
    return None


def _set_run(cmd: str) -> None:
    name = _existing_task_name() or TASK_NAME
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0,
                        winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, cmd)


def _del_run() -> bool:
    removed = False
    for name in KNOWN_TASK_NAMES:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
            removed = True
        except FileNotFoundError:
            continue
    return removed


def _get_run() -> str | None:
    for name in KNOWN_TASK_NAMES:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
                value, _ = winreg.QueryValueEx(key, name)
                return value
        except FileNotFoundError:
            continue
    return None


def _launcher_command() -> str:
    """Command that starts the headless voice launcher."""
    base = get_base_dir()
    script = base / "START_NIANG_IA.vbs"
    return f'wscript.exe "{script}" --voice'


def _set_launcher_run(cmd: str) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0,
                        winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, LAUNCHER_TASK_NAME, 0, winreg.REG_SZ, cmd)


def _del_launcher_run() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, LAUNCHER_TASK_NAME)
        return True
    except FileNotFoundError:
        return False


def _get_launcher_run() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH) as key:
            value, _ = winreg.QueryValueEx(key, LAUNCHER_TASK_NAME)
            return value
    except FileNotFoundError:
        return None


def autostart_action(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Autostart control: status | enable | disable | launcher_status |
    enable_launcher | disable_launcher"""
    params = parameters or {}
    action = str(params.get("action", "status")).lower().strip()
    remote = str(params.get("remote", "true")).lower() in ("true", "1", "yes", "on")
    background = str(params.get("background", "false")).lower() in ("true", "1", "yes", "on")

    try:
        if action in ("launcher_status", "status_launcher"):
            val = _get_launcher_run()
            if not val:
                return ("The voice launcher is OFF, sir. Say 'enable the voice "
                        "launcher' and NIANG IA will start on 'Hey Niang' even "
                        "when it is not running.")
            return (f"The voice launcher is ON, sir. NIANG IA can be started by "
                    f"saying 'Hey Niang'. Command: {val}")

        if action in ("enable_launcher", "launcher_enable"):
            _set_launcher_run(_launcher_command())
            return ("Voice launcher enabled, sir. Say 'Hey Niang' at any time: "
                    "NIANG IA will start even if it was closed.")

        if action in ("disable_launcher", "launcher_disable"):
            removed = _del_launcher_run()
            return ("Voice launcher disabled, sir." if removed else
                    "The voice launcher was already off, sir.")

        if action in ("status", "check"):
            val = _get_run()
            launcher = _get_launcher_run()
            if not val:
                extra = (" The voice launcher is ON, so NIANG IA can still be "
                         "started by voice." if launcher else "")
                return ("NIANG IA is NOT set to start automatically, sir. Say "
                        "'enable autostart' to start it at every login." + extra)
            extra = (" The voice launcher is ON." if launcher else "")
            return ("NIANG IA will start automatically at login, sir. "
                    f"Command: {val}" + extra)

        if action in ("enable", "on", "add"):
            cmd = _launch_command(remote, background)
            _set_run(cmd)
            suffix = "with the phone bridge (--remote)" if remote else "in local mode"
            if background:
                suffix += ", hidden in the tray (--background: wake-word only)"
            extra = ""
            if str(params.get("launcher", "false")).lower() in ("true", "1", "yes", "on"):
                _set_launcher_run(_launcher_command())
                extra = (" The voice launcher is ON too: NIANG IA will start on "
                         "'Hey Niang' even if it was closed.")
            return (f"Autostart enabled, sir. NIANG IA will launch at login "
                    f"{suffix}.{extra}")

        if action in ("disable", "off", "remove", "delete"):
            removed = _del_run()
            launcher_removed = False
            if str(params.get("launcher", "false")).lower() in ("true", "1", "yes", "on"):
                launcher_removed = _del_launcher_run()
            extra = " The voice launcher was removed too." if launcher_removed else ""
            return ("Autostart disabled, sir. NIANG IA will no longer start at "
                    "login." if removed else
                    "Autostart was already off, sir.") + extra

        return f"Unknown autostart action: {action}. Use status | enable | disable."
    except Exception as e:
        return f"Autostart operation failed: {e}"

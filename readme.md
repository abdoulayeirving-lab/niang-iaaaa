<p align="center">
  <img src="assets/banner.png" alt="Kaizumi Banner" width="100%">
</p>

<p align="center">
  <b>Your real-time, voice-driven AI companion for Windows</b><br>
  <i>It hears you. It sees your screen. It acts.</i>
</p>

<p align="center">
  <a href="#-features">Features</a> •
  <a href="#-quick-start">Quick Start</a> •
  <a href="#-configuration">Configuration</a> •
  <a href="#-remote-control">Remote Control</a> •
  <a href="#-safety-model">Safety</a> •
  <a href="#-tools">Tools</a> •
  <a href="#-how-it-works">How it works</a> •
  <a href="#-tests">Tests</a>
</p>

---

# 🤖 Kaizumi

**Kaizumi** is a real-time, voice-driven AI assistant that lives on your Windows
computer. It can **hear** you, **see** your screen, understand context, answer
with a **natural human-like voice**, and **take action** — launching apps,
managing files, running commands, sending messages, controlling smart-home
devices, creating presentations, and much more.

Kaizumi runs **locally** on your Windows machine; AI inference and optional
integrations (Gemini, Telegram, Google, weather, flights, smart home) use
external APIs. It is **free to self-host** — you only need a Gemini API key
(free tier available at [Google AI Studio](https://aistudio.google.com/apikey)).

> 👤 **Project owner:** Musayev Doniyor ([GitHub](https://github.com/MusayevDoniyor)) · nick **Kaizo**

> ⚠️ **Security note:** This project was made public from a personal codebase.
> Before your first run, open `config/api_keys.json` and confirm it only
> contains your own keys. **Never commit that file** — it is git-ignored.

---

## ✨ Features

| Area | What Kaizumi does |
|------|-------------------|
| 🎙️ **Real-time voice** | Natural, low-latency speech-to-speech conversation in any language |
| 🎬 **Video Studio** | Local video inspection and subtitle-guided promo renders with transitions and audio mastering |
| 👁️ **Visual awareness** | Screen analysis, screenshot understanding, opt-in live webcam input, click-on-command |
| 🧠 **Persistent memory** | Remembers your name, preferences, projects, and plans across sessions |
| 🖥️ **Guarded Computer Use** | Observe Windows UI Automation controls, operate mouse/keyboard, and verify visible results |
| 📱 **Android app** | Standalone Gemini voice/chat assistant with optional Bluetooth control of the Windows PC |
| 💬 **Telegram control** | Remote-control from any Telegram chat (text + voice notes) |
| 🕐 **Guardian** | Watches battery, RAM, CPU, disk, and temperature; alerts on thresholds |
| 🗓️ **Google integration** | Gmail, Calendar, Drive via OAuth (device flow) |
| 🧩 **50+ tools** | Web search, reminders, PDF/Word/Excel/PowerPoint, YouTube, weather, translation, and more |
| 🎭 **Modes & moods** | 6 modes × 4 moods change Kaizumi's personality |
| 🎨 **Themed UI** | 4 themes (cyber, ocean, aurora, sunset) + animated canvas |
| 🔊 **30+ voices** | Pick from 30 Gemini voices (male/female, warm/clear/soft…) |
| 🔇 **Hotkeys** | `F4` mute, `F5` cycle theme |
| ⌨️ **Keyboard input** | Type commands in the UI instead of speaking |
| 🗓️ **In-app scheduler** | "Remind me in 10 minutes" — fires with speech + phone notification |
| 🧠 **Agent mode** | Background `agent/` planner-executor handles multi-step tasks |
| 🔒 **Safety gate** | Central risk model — HIGH-risk actions need your verbal confirmation |

---

## 📦 Requirements

- **Windows 10 / 11**
- **Python 3.11 or 3.12** (the Windows launcher supports these versions)
- A microphone and speakers
- Bluetooth adapter (optional — for the Android app)
- A free [Gemini API key](https://aistudio.google.com/apikey)

---

## 🚀 Quick Start

For a Windows install, run `START_NIANG_IA.bat`. It installs the bundled
Python 3.12.10 automatically when Python 3.11 or 3.12 is not already available,
then creates a virtual environment and installs app dependencies. Installing
Python works offline; dependency and Playwright browser installation on first
launch requires internet. The Windows installer also offers an optional
personalization page for the name NIANG IA should use and its default response
language. A following setup page links directly to Google AI Studio to create a
Gemini API key and accepts pasting it during installation. The name and language
are imported into NIANG IA's memory on first launch; a pasted key is saved
locally as a separate configuration file. Both pages can be skipped. You can
also configure a Gemini API key later in `config/api_keys.json`.

For a manual install:

```bash
git clone https://github.com/MusayevDoniyor/kaizumi.git
cd kaizumi

python -m venv .venv
.venv\Scripts\activate

python setup.py        # installs deps, Playwright browsers, creates config files
python main.py
```

Configure your Gemini API key in `config/api_keys.json`:

```jsonc
// config/api_keys.json
{
    "gemini_api_key": "AIzaSy...",                          // required
    "gemini_api_keys": ["AIzaSy...", "AIzaSy..."],          // optional: multi-key rotation on 429
    "telegram_bot_token": "",                               // optional: Telegram remote control
    "telegram_chat_id": null,                               // optional: your chat id (numeric)
    "gmail_user": "",                                       // optional: Gmail address
    "gmail_app_password": "",                               // optional: Gmail app password
    "google_client_id": "",                                 // optional: Google OAuth
    "google_client_secret": ""                              // optional: Google OAuth
}
```

Secrets can also be provided as environment variables (docker/CI friendly):

| Env var | Replaces |
|---------|----------|
| `KAIZUMI_GEMINI_API_KEY` | `gemini_api_key` |
| `KAIZUMI_GEMINI_API_KEYS` | `gemini_api_keys` (comma-separated) |
| `KAIZUMI_TELEGRAM_TOKEN` | `telegram_bot_token` |
| `KAIZUMI_TELEGRAM_CHAT_ID` | `telegram_chat_id` |
| `KAIZUMI_BRIDGE_TOKEN` | Bluetooth-app token (auto-generated in `config/bridge_token.txt`) |

### Google account access

Web search and browser navigation use the configured Gemini/web-search
capabilities and do not require linking a personal Google account. To let the
assistant access Gmail, Calendar, or Drive, create a Desktop OAuth client in
[Google Cloud Console](https://console.cloud.google.com/apis/credentials), enable
the Google APIs you intend to use, and add its client ID and client secret to
`config/api_keys.json`. Keep the secret local; never share it in chat. Then ask
NIANG IA to connect Google and approve the requested access in Google's consent
flow.

System ready in minutes.

---

## 🪟 Building a Windows release

Run `python build_release.py` to create a clean source archive and staging
folder in `dist/`. The build downloads the official Python 3.12.10 x64
installer from python.org and checks its SHA-256 against the pinned value
before packaging it. The release excludes local API keys, runtime
configuration, logs, memory data, caches, backups, and virtual environments.
It includes the model files in `models/`; verify their redistribution terms
before publishing. The NIANG IA logo in `assets/niang_ia.ico` is used for the
installer and its Windows shortcuts.

To compile the Windows installer, install Inno Setup 6 and run:

```powershell
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" NIANG_IA.iss
```

The installer and ZIP are built from the same staging folder. Python 3.12.10
is bundled and installs without an internet connection. First-launch dependency
and Playwright browser installation still needs internet. Users must configure
their own Gemini API key.

---

## ⚙️ Configuration

All configuration lives in `config/`. `python setup.py` copies any
`*.example.json` to a real `.json` automatically (it never overwrites existing
files).

| File | Purpose |
|------|---------|
| `api_keys.json` | Gemini key(s), Telegram bot, Gmail, Google OAuth |
| `guardian.json` | Health-guardian thresholds (battery, RAM, CPU, disk, temp) |
| `smart_home.json` | Smart home devices (Home Assistant / webhook / simulated) |
| `bridge_token.txt` | Auto-generated access token for the Bluetooth Android app |

### Guardian thresholds (`guardian.json`)

```jsonc
{
    "enabled": true,
    "battery_low": 20,        // warn when battery drops below 20%
    "battery_full_plugged": 100,
    "disk_min_free_gb": 10,   // warn when free disk < 10 GB
    "ram_high": 90,           // warn when RAM usage > 90%
    "cpu_high": 95,           // warn when CPU usage > 95%
    "temp_high": 85,          // warn when temperature > 85°C
    "backup_days": 7,
    "cooldown": 3600          // seconds between repeated alerts
}
```

### Smart home (`smart_home.json`)

Supports **Home Assistant**, **generic webhooks**, or a **simulated** mode —
plus a per-device config (switches, lights, thermostats, covers, locks, media
players, and scenes). Home Assistant mode also supports configured whole-area
on/off controls. Store Home Assistant long-lived tokens only in the local,
git-ignored `config/smart_home.json`; never paste them into chat. Unlocking a
lock requires explicit user confirmation.

Example Home Assistant configuration:

```json
{
    "enabled": true,
    "mode": "home_assistant",
    "home_assistant": {
        "url": "http://homeassistant.local:8123",
        "token": "YOUR_LOCAL_LONG_LIVED_TOKEN"
    },
    "devices": [
        {"id": "living-room-light", "name": "Living room light", "entity": "light.living_room"},
        {"id": "evening-scene", "name": "Evening scene", "entity": "scene.evening"}
    ],
    "areas": [
        {"id": "living_room", "name": "Living room"}
    ]
}
```

Ask NIANG IA to control a configured device, activate a configured scene, or
turn a configured area on/off. Area ids are Home Assistant area ids.

---

## 📱 Remote Control

The Android app provides its own Gemini assistant and an optional Bluetooth
remote for the Windows app. Telegram commands, in contrast, run through the
Windows assistant's Gemini Live session.

### 1. Android app and optional Bluetooth PC remote

```bash
python main.py --remote
```

- The Android app supports standalone text/voice chat, optional Gemini Web
  Search, selected PDF/image/text documents, and confirmed Android actions
  (apps/settings, calendar reminders, alarms, and public links).
- It requires internet and a user-provided Gemini API key; it does not offer
  offline operation or Windows-only automation features.
- Run `--remote` to additionally start the BLE GATT peripheral advertising as
  **"Kaizumi Remote"**.
- Build and install the Android app from `android/` (see
  [`android/README.md`](android/README.md)). The bridge token is automatically
  generated in `config/bridge_token.txt` on first run.
- In the Android app, open **Contrôle PC**, enter the token, and tap **Connect** — it pairs via the
  encrypted characteristic, authenticates, and shows *Authenticated*.
- Type a command and tap **Send** — NIANG IA replies and streams live events
  (tool status, phase changes, system alerts) to your phone.

### 2. Telegram — remote control from anywhere

1. Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. Message your new bot once (this gives you the numeric chat id), then find
   your chat id with `@userinfobot` or via `getUpdates`.
3. Put both in `config/api_keys.json`:

```jsonc
{
    "telegram_bot_token": "123456:ABC-DEF...",
    "telegram_chat_id": 123456789
}
```

Kaizumi starts polling automatically and **only responds to your chat id**.
Built-in commands: `/status`, `/mute`, `/unmute`, `/mode`, `/voice`,
`/screenshot`, `/help` — plus quick-reply keyboards. Voice notes are
transcribed on the fly.

---

## 🛡️ Safety model

Kaizumi classifies every tool into **LOW / MEDIUM / HIGH** risk (`safety.py`)
and enforces it centrally — no per-tool ad-hoc checks.

- **HIGH-risk actions** (delete/move files, run terminal commands, send
  email/SMS, kill processes, auto-update games, shutdown/restart, drive
  deletes, live webcam streaming, …) **require your explicit verbal confirmation** before they run.
- When a high-risk tool is requested, Kaizumi asks *"May I …?"* and waits for
  an explicit **yes** before re-invoking the action.
- The model is instructed to **never set `confirm=true` on its own** — only
  after you approve. This is *enforced technically*, not just by instruction:
  a blocked high-risk call receives a **single-use token** (`confirm_token`)
  bound to that exact call. The tool stays blocked until the model echoes the
  token back, and each token works only once.
- Secrets (API keys, tokens, passwords) are **redacted from logs** and never
  written to memory.
- The Bluetooth app requires the access token (constant-time comparison);
  Telegram is locked to your chat id.
- The desktop AI sandbox blocks `ctypes`/subprocess/escalation escapes and
  obfuscated variants of dangerous calls.
- URL fetching (document/web QA) refuses loopback, private, link-local, and
  cloud-metadata targets (SSRF guard).

---

## 🧩 Tools

Kaizumi exposes **53 tools** to the model. The full list lives in `main.py`
(`_build_tool_schemas`); highlights:

| Category | Tools |
|----------|-------|
| 🖥️ **System** | `system_status`, `task_manager`, `computer_settings`, `autostart`, `clipboard`, `media_control`, `notify`, `pc_health` |
| 🗂️ **Files** | `file_controller`, `open_app`, `desktop_control`, `read_pdf`, `pdf_qa`, `read_document`, `document_qa`, `search_documents`, `create_document`, `analyze_data`, `create_presentation`, `create_spreadsheet` |
| 🌐 **Web** | `web_search`, `browser_control`, `youtube_video`, `weather_report`, `flight_finder`, `translate`, `set_live_translation`, `proactive_suggestions` |
| 💬 **Communication** | `send_message`, `gmail`, `email_watch`, `calendar`, `drive`, `google_auth`, `google_auth_status`, `whatsapp_call` |
| 🤖 **Automation** | `cmd_control`, `code_helper`, `dev_agent`, `agent_task`, `schedule`, `daily_briefing`, `game_updater`, `smart_home_control` |
| 👁️ **Vision** | `screen_process`, `vision_gesture`, `live_camera`, `vision_click`, `wake_word` |
| 🧠 **Memory** | `save_memory`, `recall_memory`, `forget_memory`, `clear_memory`, `set_mode`, `set_voice`, `set_voice_style`, `set_mood` |
| 🔑 **Admin** | `api_add_key` |

Every tool is dispatched through a single handler table with per-tool
timeouts and a loop guard that stops identical-arg / ping-pong tool loops.
Background agent plans are limited to five validated steps and known tools;
task status reports the current phase and step progress.

---

## 🎭 Modes, moods & voices

- **Modes:** `normal`, `girlfriend`, `crazy_friend`, `butler`, `friend`,
  `casual` — set with `set_mode` or Telegram `/mode`.
- **Moods:** `calm`, `playful`, `romantic`, `strict` — set with `set_mood`.
- **Voices:** 30 Gemini voices (Aoede, Charon, Fenrir, Kore, Puck, Zephyr,
  …) — set with `set_voice` or Telegram `/voice`. Preferences persist across
  sessions in memory.
- **Voice delivery:** Choose `natural`, `calm`, `warm`, `energetic`,
  `expressive`, or `measured` with `set_voice_style`; the preference is saved.
- **Live webcam:** Ask NIANG IA to start the live camera to share webcam frames
  with Gemini during the current conversation. Starting requires explicit
  confirmation, a red UI indicator stays visible while sharing, and streaming
  stops when asked or when the Gemini session disconnects. Microphone audio
  was already streamed live by the existing conversation mode.
- **Personal document search:** `search_documents` searches local files in
  Documents, Downloads, Desktop, or a specific folder you request. The scan is
  limited to 300 supported files (20 MB each); only the top five matching
  excerpts are returned to Gemini, so relevant private text is sent to Google
  for the answer. It does not search the whole computer or cloud accounts.
- **Live speech translation:** `set_live_translation` enables spoken
  interpretation into a chosen target language (source language can be
  auto-detected), or disables/checks the mode. The preference is stored locally
  and applied when the live session reconnects. In translation mode, NIANG IA
  translates microphone speech instead of responding to its meaning.
- **Proactive suggestions:** `proactive_suggestions` lets you opt in to
  suggestions based on repeated use. When enabled, NIANG IA stores only a
  small allow-listed tool name and date locally (never arguments or message
  contents), for up to 30 days. Suggestions are based on use on at least three
  different days and appear in the daily briefing; disabling also deletes the
  stored usage history. No background microphone or activity monitoring runs.
- **Calendar briefing:** When Google Calendar is already authorized, the
  daily briefing includes the next events for the local calendar day. Without
  authorization, it skips the calendar section; no new background sync runs.
- **WhatsApp call assistant (manual-assist):** `whatsapp_call` never selects
  contacts, places, detects, or hangs up calls. The user verifies the contact
  and number, starts the WhatsApp call manually, and informs the other person
  that NIANG IA is an AI before connecting. A separate Gemini Live session
  receives live call audio and selected display names. NIANG IA does not retain
  local transcripts or recordings; Google's service policies apply. It
  requires two distinct, isolated virtual audio routes configured in
  `config/whatsapp_call.json`; copy `config/whatsapp_call.example.json`, use
  separate virtual cable A and B pairs, and set `isolation_confirmed` to true
  only after verifying that the routes do not feed back into one another. Route
  WhatsApp output to cable A's playback end, NIANG IA capture to cable A's
  capture end, NIANG IA output to cable B's playback end, and WhatsApp's
  microphone to cable B's capture end. Do not use speaker-to-microphone
  loopback. In the JSON, `incoming_audio_device` is cable A's capture endpoint;
  `outgoing_audio_device` is cable B's playback endpoint. The current machine
  has no such virtual routes, so this mode remains unavailable until the user
  installs and configures a virtual audio mixer/cable.
  Use **STOP AI AUDIO** if the other person declines; this stops NIANG IA only,
  not WhatsApp, and refusal detection is not automatic. This does not control
  WhatsApp Desktop or implement the WhatsApp Business Calling API. No call
  summary is available because transcripts are not retained. Gemini/cloud audio
  processing requires the user's explicit confirmation. To use it, ask NIANG IA
  to prepare, manually verify and start the WhatsApp call, disclose the AI, then
  ask it to join; confirm the explicit consent prompt before audio is sent.
- **Local data reports:** `analyze_data` reads a local CSV or `.xlsx` and
  generates a Word report with descriptive statistics. It processes at most
  10,000 rows, 50 columns, and 20 MB per file; dataset contents are analyzed
  locally and are not uploaded to Gemini.
- **Video Studio:** `video_studio status` checks CapCut in standard
  install locations. `video_studio analyze` reads a local AVI, M4V, MKV, MOV,
  MP4, or WEBM file with OpenCV and saves metadata plus sampled visual-change
  candidates as JSON under `outputs/video_studio/`. Frames are inspected locally
  and are not uploaded. The report does not identify story content, speech,
  or verified scene boundaries. `video_studio edit` creates a rendered copy
  using existing subtitle phrase boundaries, smooth-wipe/dissolve transitions,
  synchronized audio crossfades, burnt-in captions, restrained reframing/color
  adjustment, and normalized audio. It does not modify the source or create a
  CapCut project. This automated promo preset requires an existing subtitle
  track and CapCut's bundled FFmpeg; it is not a substitute for editorial review.
  CapCut 9.6.0.4097 is installed under `%LOCALAPPDATA%/CapCut/Apps/CapCut.exe`.
- **Guarded Windows Computer Use:** `computer_control` provides screen
  resolution/scaling and monitor information, local screenshots, active-window
  details, accessible controls from the foreground window, mouse and keyboard
  input, visual-change waits, and accessible-label verification. Input actions
  and access to private screen/window content require the normal one-time
  confirmation token before execution; screen descriptions and visual element
  searches explicitly disclose that the screenshot is sent to Gemini. Results
  report whether an action executed and whether its visible outcome was verified.
  `stop` cancels interruptible work and releases held mouse buttons. After
  explicitly enabling the emergency hook, `Ctrl+Alt+Pause` stops ongoing typing,
  movement, or dragging; moving the pointer to the top-left screen corner also
  activates PyAutoGUI's built-in fail-safe. The emergency hook can be disabled
  with `disable_emergency_stop`. This uses the existing `pyautogui`, `pywinauto`,
  `mss`, and `keyboard` dependencies. Windows secure/UAC desktops and controls
  that expose no UI Automation metadata cannot be operated or verified.
  Coordinate-based input is limited to the primary display; `mss` screenshots
  and monitor information include the full virtual desktop when supported.
  The separate `screen_process` screen/webcam analysis and `computer_settings`
  text-entry, clipboard, Run-dialog, and save/close actions also require explicit
  confirmation through the same gate; typed text is redacted from its action log.

---

## 🧠 How it works

- **Gemini Live API** (`models/gemini-3.1-flash-live-preview`) powers real-time
  speech-to-speech interaction. Voice, screen, and control code run on-device;
  speech understanding/generation, optional live webcam frames, and tool
  reasoning are sent to Google's Gemini API.
- **Planner/executor** (`agent/`) breaks multi-step requests into tool calls,
  validates the plan, runs steps in order, reports progress, and auto-recovers:
  retry → skip → replan → abort.
- **Resilience layer** (`agent/resilience.py`) wraps every tool with a hard
  timeout and bounded retries — a hung tool can't freeze the session.
- **Loop guard** (`agent/loop_guard.py`) detects identical-arg / ping-pong
  tool loops in live mode.
- **Guardian** (`actions/guardian.py`) runs a background loop, watching system
  health and speaking alerts.
- **Monitor** (`actions/monitor.py`) watches user-defined rules (CPU, RAM,
  battery, disk, temperature) and pushes alerts.
- **In-app scheduler** (`main._scheduler_loop`) fires reminders with speech +
  phone notification — no Windows Task Scheduler needed.
- **Wake word** (`actions/wake_word.py`) uses openwakeword on-device for
  hands-free "Hey Kaizumi" activation (you can record your own wake word).
- **Logging** (`logger.py`) writes one log file per run under `logs/` and
  redacts secrets.

---

## 📁 Project structure

```
kaizumi/
├── main.py                    # engine: Gemini Live session, tools, scheduler
├── ui.py                      # Tkinter animated UI, setup dialog, themes
├── telegram_bot.py            # Telegram long-polling transport
├── api_keys.py                # multi-key loading + 429 auto-rotation
├── safety.py                  # central risk model + confirmation gate
├── google_oauth.py            # Google device-flow OAuth
├── setup.py                   # one-shot install + config creation
├── actions/                   # 40+ tool implementations
├── agent/                     # planner, executor, error recovery, task queue
├── memory/                    # persistent memory (CRUD, pruning, secrets)
├── remote/                    # Bluetooth BLE transport (GATT peripheral)
├── android/                   # standalone Android assistant + optional BLE remote (Kotlin)
├── docs/PROTOCOL.md           # Bluetooth wire protocol spec
├── config/                    # configuration (git-ignored)
└── tests/                     # unit tests (no API keys, no network)
```

---

## 🛠️ Troubleshooting

- **`1007 Request contains an invalid argument`** during a session: this
  happens when text turns are sent via `send_client_content` instead of
  `send_realtime_input`. Current code uses `send_realtime_input(text=...)` for
  in-conversation text — if you fork and see it, check your send paths.
- **Microphone not detected:** check the default input device in Windows sound
  settings.
- **Bluetooth "No bridge token":** run `python main.py --remote` once — the
  token is generated automatically in `config/bridge_token.txt`. Or set
  `KAIZUMI_BRIDGE_TOKEN` (min 16 chars).
- **`winrt` not available:** Bluetooth transport needs
  `winrt-Windows.Devices.Bluetooth.*` packages (see `requirements.txt`).
  Without them, Kaizumi runs fine — only the Bluetooth channel is disabled.
- **Voice/tool errors are spoken aloud** — read the log file in `logs/` for
  details (one file per run).
- **Slow startup:** heavy ML packages (mediapipe, openwakeword) are imported
  lazily — they load only when the matching feature (vision / wake word) is
  first used, so startup stays fast.

---

## 🧪 Tests

Unit tests live in `tests/` and require **no API keys and no network** —
external services (Gemini, Telegram, Google) are never called.

```bash
python -m unittest discover -s tests -v
# or
python -m pytest tests -q
```

Covered: risk classification & confirmation gate (`safety.py`), memory
CRUD/pruning/secret filtering (`memory/memory_manager.py`), log redaction
(`logger.py`), zip-slip protection (`file_controller.py`), multi-key/env
loading (`api_keys.py`), plus the P0 security fixes — SSRF guard, exec-sandbox
hardening, executor unknown-tool handling, and API-key readiness checks
(`tests/test_p0_security.py`).

---

## 📄 License

[MIT](LICENSE) © Musayev Doniyor (Kaizo)

---

<p align="center">
  Made with ❤️ by <b>Musayev Doniyor</b> (Kaizo) · Star the repo if you find it useful! ⭐
</p>
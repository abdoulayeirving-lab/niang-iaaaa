# NIANG IA Mobile — Android

Native Android app with a standalone Gemini assistant and an optional Bluetooth
remote for NIANG IA on Windows. The mobile app does not reproduce Windows-only
features such as desktop automation, WhatsApp call audio routing, or CapCut
editing.

## Mobile assistant

- Text chat and voice input using the phone's speech-recognition service.
- Spoken replies using Android Text-to-Speech; speech recognition and speech
  synthesis are not a real-time duplex voice call.
- Optional Gemini Google Search grounding with source links.
- User-selected PDF, PNG, JPEG, and plain-text documents (up to 10 MiB each).
- A Gemini-supplied request can open allowlisted Android apps/settings, open
  the calendar to create a reminder, create an alarm, or open a public HTTP(S)
  URL. Each action requires confirmation.
- The Gemini API key is encrypted with Android Keystore and stored only on the
  device. Conversation history is kept in memory for the current app session.
- Optional Bluetooth remote to the Windows assistant remains available from
  the **Contrôle PC** button.

The app sends submitted messages, voice-recognition text, and selected
documents to Google Gemini. Web search is used only when its switch is enabled.
An internet connection and a Gemini API key are required.

## Requirements

- **JDK 17+** and the **Android SDK**
- A phone running **Android 8.0+ (API 26+)**
- Bluetooth is needed only for the optional PC-remote screen
- On the PC: `winrt-Windows.Devices.Bluetooth*` packages installed
  (see `requirements.txt`) and the PC's Bluetooth adapter that supports BLE
  peripheral mode

## Build

```bash
cd android
gradlew.bat assembleDebug
```

Or open `android/` in **Android Studio**, let it sync, and run on a phone
(Gradle 8.7 / AGP 8.5.2 / Kotlin 2.0.20).

## Install and use the Android assistant

1. Copy `app/build/outputs/apk/debug/app-debug.apk` to the phone and open it.
   Allow installation from that file source if Android asks.
2. Obtain a Gemini API key from Google AI Studio and enter it using **Clé API**.
   It is encrypted on the phone with Android Keystore; it is not bundled into
   the APK.
3. Use **Parler** and grant microphone access for voice input. The phone's
   configured speech-recognition service processes the audio; the recognized
   text is sent to Gemini.
4. To analyze a supported document, choose **Document**, select a PDF, PNG,
   JPEG, or plain-text file, then send a question. The selected file is sent to
   Gemini only when the message is submitted.
5. Enable Web search for a message when online sources are needed. The switch
   turns off after sending.

The assistant requires internet and a valid Gemini API key. It does not work
offline. Android actions are limited to allowlisted apps/settings, calendar reminders,
alarms, and opening HTTP(S) links; NIANG IA asks before launching them. The optional
Bluetooth PC-remote screen separately requests Bluetooth permissions on
Android 12+ or location permission on Android 11 and earlier.

## Usage

1. To use the optional PC remote, run NIANG IA on the PC with Bluetooth enabled:
   ```bash
   python main.py --remote
   ```
   The BLE peripheral starts (advertising as **"Kaizumi Remote"**) and the
   bridge token is auto-generated at `config/bridge_token.txt` (or use the
   `KAIZUMI_BRIDGE_TOKEN` env var, min 16 chars).
2. Copy the bridge token from `config/bridge_token.txt`.
3. On the phone: open **Contrôle PC**, enable Bluetooth, enter the token, tap
   **Connect**. The app finds the PC, pairs (confirm the pairing prompt),
   authenticates, and shows *Authenticated*.
4. Type a command and tap **Send** — NIANG IA answers on the PC and streams
   live events to the phone.

The Bluetooth protocol (framing, envelope, message types, authentication, and
reconnect) is documented in [`docs/PROTOCOL.md`](../docs/PROTOCOL.md).

> 🔐 The bridge token is your only credential for the phone. Keep it private —
> it unlocks full control of your assistant.

## Troubleshooting

- **Scan finds nothing:** ensure the PC's Bluetooth radio is on and the PC and
  phone are close together. Some PCs need the device in discoverable mode; the
  peripheral advertising is always discoverable.
- **Pairing prompt doesn't appear:** on Android the first encrypted write
  triggers pairing; if the PC requires "just works" pairing this is automatic.
- **Reply is slow:** BLE default MTU is small; the Android app requests high
  connection priority. Text replies are short, so latency is fine.
- **`[Bluetooth] ⛔ No bridge token`:** run `--remote` once to auto-generate
  `config/bridge_token.txt`, or set `KAIZUMI_BRIDGE_TOKEN`.

## Protocol

See [`docs/PROTOCOL.md`](../docs/PROTOCOL.md) for the complete wire spec:
service/characteristic UUIDs, length-prefixed framing, the JSON envelope,
auth flow, and reconnect behavior.
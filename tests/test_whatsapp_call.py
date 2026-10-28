"""Tests for the privacy-isolated, manual WhatsApp call audio assistant."""

import asyncio
import json
import os
import queue
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actions.whatsapp_call import (
    AudioConfigurationError,
    CallState,
    WhatsAppCallAssistant,
    load_audio_configuration,
    resolve_audio_routes,
    whatsapp_call_action,
)
import safety


class AudioConfigurationTests(unittest.TestCase):
    def test_missing_configuration_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "missing.json"
            with self.assertRaisesRegex(AudioConfigurationError, "not configured"):
                load_audio_configuration(path)

    def test_configuration_requires_isolation_and_distinct_names(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "routes.json"
            path.write_text(json.dumps({
                "incoming_audio_device": "Cable A",
                "outgoing_audio_device": "Cable B",
                "isolation_confirmed": False,
            }), encoding="utf-8")
            with self.assertRaisesRegex(AudioConfigurationError, "isolation_confirmed"):
                load_audio_configuration(path)

            path.write_text(json.dumps({
                "incoming_audio_device": "Cable A",
                "outgoing_audio_device": " cable a ",
                "isolation_confirmed": True,
            }), encoding="utf-8")
            with self.assertRaisesRegex(AudioConfigurationError, "different"):
                load_audio_configuration(path)

    def test_configuration_loads_exact_routes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "routes.json"
            path.write_text(json.dumps({
                "incoming_audio_device": "Cable A capture",
                "outgoing_audio_device": "Cable B playback",
                "isolation_confirmed": True,
            }), encoding="utf-8")
            self.assertEqual(
                load_audio_configuration(path),
                ("Cable A capture", "Cable B playback"),
            )

    def test_routes_require_unique_devices_with_correct_direction(self):
        devices = [
            {"index": 4, "name": "Cable A", "input_channels": 1, "output_channels": 0},
            {"index": 7, "name": "Cable B", "input_channels": 0, "output_channels": 1},
        ]
        self.assertEqual(resolve_audio_routes("Cable A", "Cable B", devices), (4, 7))
        with self.assertRaisesRegex(AudioConfigurationError, "found 0"):
            resolve_audio_routes("Cable B", "Cable A", devices)
        with self.assertRaisesRegex(AudioConfigurationError, "found 2"):
            resolve_audio_routes(
                "Cable A",
                "Cable B",
                devices + [
                    {"index": 8, "name": "Cable A", "input_channels": 1, "output_channels": 0},
                ],
            )


class ManualCallSafetyTests(unittest.TestCase):
    def test_connect_requires_explicit_verified_contact_boolean(self):
        assistant = Mock()
        for value in (None, False, "true", 1):
            with self.subTest(value=value):
                result = whatsapp_call_action(
                    {
                        "action": "connect",
                        "contact_name": "Amadou",
                        "contact_confirmed": value,
                    },
                    assistant,
                )
                self.assertIn("verify", result)
        assistant.connect.assert_not_called()

    def test_connect_fails_closed_when_routes_are_not_configured(self):
        sounddevice = Mock()
        sounddevice.query_devices.return_value = []
        client_factory = Mock()
        with tempfile.TemporaryDirectory() as folder:
            assistant = WhatsAppCallAssistant(
                sounddevice_module=sounddevice,
                client_factory=client_factory,
                config_path=Path(folder) / "missing.json",
            )
            result = assistant.connect("Amadou")
        self.assertIn("did not join", result)
        self.assertEqual(assistant.status()["state"], CallState.FAILED.value)
        client_factory.assert_not_called()

    def test_mute_and_stop_are_local_and_never_claim_to_hang_up(self):
        assistant = WhatsAppCallAssistant()
        assistant._set_state(CallState.LISTENING)
        self.assertIn("WhatsApp call itself remains active", assistant.mute())
        self.assertEqual(assistant.status()["state"], CallState.ON_HOLD.value)
        self.assertIn("hang up in WhatsApp", assistant.stop())
        self.assertEqual(
            assistant.status()["state"],
            CallState.COMPLETED.value,
            assistant.status()["detail"],
        )

    def test_connect_and_resume_require_bound_explicit_confirmation(self):
        args = {
            "action": "connect",
            "contact_name": "Amadou",
            "owner_name": "User",
            "contact_confirmed": True,
        }
        self.assertTrue(safety.needs_confirmation("whatsapp_call", args))
        token = safety.issue_confirmation_token("whatsapp_call", args)
        self.assertFalse(safety.needs_confirmation(
            "whatsapp_call", args, confirm=True, confirm_token=token,
        ))
        self.assertTrue(safety.needs_confirmation(
            "whatsapp_call",
            {**args, "contact_name": "Someone else"},
            confirm=True,
            confirm_token=token,
        ))
        self.assertTrue(safety.needs_confirmation(
            "whatsapp_call", {"action": "resume"},
        ))
        self.assertTrue(safety.needs_confirmation(
            "whatsapp_call", {"action": "join"},
        ))
        self.assertTrue(safety.needs_confirmation(
            "whatsapp_call", {"action": "unmute"},
        ))
        self.assertFalse(safety.needs_confirmation(
            "whatsapp_call", {"action": "stop"},
        ))

    def test_contact_and_owner_names_are_redacted_from_tool_arguments(self):
        self.assertEqual(
            safety.sanitize("whatsapp_call", {
                "contact_name": "Amadou",
                "owner_name": "User",
                "action": "connect",
            }),
            {
                "contact_name": "[private]",
                "owner_name": "[private]",
                "action": "connect",
            },
        )


class _FakeStream:
    def __init__(self, callback, input_stream=False):
        self.callback = callback
        self.input_stream = input_stream

    def __enter__(self):
        if self.input_stream:
            self.callback(bytes(2048), 1024, None, None)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _FakeSoundDevice:
    def query_devices(self):
        return [
            {
                "name": "Cable A capture",
                "max_input_channels": 1,
                "max_output_channels": 0,
            },
            {
                "name": "Cable B playback",
                "max_input_channels": 0,
                "max_output_channels": 1,
            },
        ]

    def RawInputStream(self, **kwargs):
        return _FakeStream(kwargs["callback"], input_stream=True)

    def RawOutputStream(self, **kwargs):
        return _FakeStream(kwargs["callback"])


class _FakeTypes:
    class _Object:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    LiveConnectConfig = _Object
    SpeechConfig = _Object
    VoiceConfig = _Object
    PrebuiltVoiceConfig = _Object
    Blob = _Object


class _FakeSession:
    def __init__(self, assistant):
        self.assistant = assistant
        self.audio_ready = asyncio.Event()
        self.audio_sent = []
        self.disclosure = ""
        self.output_audio = b""

    async def send_realtime_input(self, **kwargs):
        if "text" in kwargs:
            self.disclosure = kwargs["text"]
        if "audio" in kwargs:
            self.audio_sent.append(kwargs["audio"])
            self.audio_ready.set()

    async def receive(self):
        await self.audio_ready.wait()
        yield SimpleNamespace(
            server_content=SimpleNamespace(
                interrupted=False,
                turn_complete=False,
                model_turn=SimpleNamespace(
                    parts=[
                        SimpleNamespace(
                            inline_data=SimpleNamespace(data=b"\x01\x00" * 16),
                        )
                    ],
                ),
            ),
        )
        await asyncio.sleep(0)
        output = bytearray(32)
        self.assistant._output_stream.callback(output, 16, None, None)
        self.output_audio = bytes(output)
        self.assistant.stop()
        await asyncio.sleep(3600)


class _FakeLive:
    def __init__(self, assistant):
        self.assistant = assistant
        self.session = _FakeSession(assistant)
        self.config = None

    def connect(self, model, config):
        self.config = config
        live = self

        class _Context:
            async def __aenter__(self):
                return live.session

            async def __aexit__(self, exc_type, exc_value, traceback):
                return False

        return _Context()


class _FakeClient:
    def __init__(self, live):
        self.aio = SimpleNamespace(live=live)


class AudioPipelineTests(unittest.TestCase):
    def test_mocked_live_audio_round_trip_and_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            config_path = Path(folder) / "routes.json"
            config_path.write_text(json.dumps({
                "incoming_audio_device": "Cable A capture",
                "outgoing_audio_device": "Cable B playback",
                "isolation_confirmed": True,
            }), encoding="utf-8")
            assistant = WhatsAppCallAssistant(
                sounddevice_module=_FakeSoundDevice(),
                config_path=config_path,
            )
            assistant._contact_name = "Test contact"
            live = _FakeLive(assistant)
            assistant._client_factory = lambda **kwargs: _FakeClient(live)
            assistant._load_runtime = lambda: _FakeTypes
            with patch("api_keys.next_key", return_value="not-a-real-key"):
                assistant._thread_main()

        self.assertEqual(
            assistant.status()["state"],
            CallState.COMPLETED.value,
            assistant.status()["detail"],
        )
        self.assertTrue(live.session.audio_sent)
        self.assertTrue(any(live.session.output_audio))
        self.assertIn("AI assistant", live.session.disclosure)
        self.assertNotIn("input_audio_transcription", vars(live.config))
        self.assertNotIn("output_audio_transcription", vars(live.config))

    def test_interruption_clears_queued_generated_audio(self):
        class _InterruptedSession:
            async def receive(self):
                yield SimpleNamespace(
                    server_content=SimpleNamespace(
                        interrupted=True,
                        turn_complete=False,
                        model_turn=None,
                    ),
                )

        assistant = WhatsAppCallAssistant()
        assistant._playback_queue = queue.Queue()
        assistant._playback_queue.put_nowait(b"stale response")
        assistant._set_state(CallState.SPEAKING)
        asyncio.run(assistant._receive_audio(_InterruptedSession()))
        self.assertTrue(assistant._playback_queue.empty())
        self.assertEqual(assistant.status()["state"], CallState.LISTENING.value)

    def test_mute_discards_queued_input_before_resume(self):
        async def exercise():
            assistant = WhatsAppCallAssistant()
            assistant._audio_queue = asyncio.Queue()
            assistant._audio_queue.put_nowait(b"stale audio")
            assistant._loop = asyncio.get_running_loop()
            assistant._set_state(CallState.LISTENING)
            assistant.mute()
            await asyncio.sleep(0)
            self.assertTrue(assistant._audio_queue.empty())
            assistant.resume()
            self.assertEqual(assistant.status()["state"], CallState.LISTENING.value)

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()

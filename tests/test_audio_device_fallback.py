import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main


class _FakeUI:
    silent_mode = False
    muted = False

    def __init__(self):
        self.messages = []

    def write_log(self, message):
        self.messages.append(message)


class _CancelAfterChunk:
    def __init__(self, chunks):
        self._chunks = iter(chunks)

    async def get(self):
        try:
            return next(self._chunks)
        except StopIteration:
            raise asyncio.CancelledError()

    def empty(self):
        return True


class AudioDeviceFallbackTests(unittest.TestCase):
    @staticmethod
    def _assistant_with_chunks(chunks):
        assistant = object.__new__(main.KaizumiLive)
        assistant.ui = _FakeUI()
        assistant.audio_in_queue = _CancelAfterChunk(chunks)
        assistant._is_speaking = False
        assistant._last_play_ts = 0.0
        assistant._turn_complete = False
        assistant.set_speaking = Mock()
        return assistant

    def test_missing_output_driver_keeps_audio_task_alive_in_text_fallback(self):
        assistant = self._assistant_with_chunks([b"audio"])
        sounddevice = SimpleNamespace(
            RawOutputStream=Mock(side_effect=RuntimeError("no playback device")),
        )

        with patch.object(main, "sd", sounddevice):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(assistant._play_audio())

        self.assertIn("Sortie audio indisponible", assistant.ui.messages[0])

    def test_playback_driver_failure_switches_to_text_fallback(self):
        assistant = self._assistant_with_chunks([b"first", b"second"])
        stream = SimpleNamespace(
            start=Mock(),
            write=Mock(side_effect=RuntimeError("device removed")),
            stop=Mock(),
            close=Mock(),
        )
        sounddevice = SimpleNamespace(RawOutputStream=Mock(return_value=stream))

        with patch.object(main, "sd", sounddevice):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(assistant._play_audio())

        self.assertTrue(any("Sortie audio interrompue" in msg for msg in assistant.ui.messages))
        stream.close.assert_called_once()

    def test_missing_microphone_driver_leaves_text_input_available(self):
        assistant = object.__new__(main.KaizumiLive)
        assistant.ui = _FakeUI()
        sounddevice = SimpleNamespace(
            InputStream=Mock(side_effect=RuntimeError("no recording device")),
        )

        with patch.object(main, "sd", sounddevice):
            asyncio.run(assistant._listen_audio())

        self.assertIn("Microphone indisponible", assistant.ui.messages[0])


if __name__ == "__main__":
    unittest.main()

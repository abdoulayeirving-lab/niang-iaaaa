import asyncio
import threading
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


class _FakeInputStream:
    def __init__(self, device):
        self.device = device
        self.active = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


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
            query_devices=Mock(return_value={"index": 0}),
            RawOutputStream=Mock(side_effect=RuntimeError("no playback device")),
        )

        with patch.object(main, "sd", sounddevice):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(assistant._play_audio())

        self.assertIn("Sortie audio indisponible", assistant.ui.messages[0])

    def test_playback_driver_failure_switches_to_text_fallback(self):
        assistant = self._assistant_with_chunks([b"first", b"second"])
        stream = SimpleNamespace(
            device=0,
            active=True,
            start=Mock(),
            write=Mock(side_effect=RuntimeError("device removed")),
            stop=Mock(),
            close=Mock(),
        )
        sounddevice = SimpleNamespace(
            RawOutputStream=Mock(return_value=stream),
            query_devices=Mock(return_value={"index": 0}),
        )

        with patch.object(main, "sd", sounddevice):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(assistant._play_audio())

        self.assertTrue(any("Sortie audio interrompue" in msg for msg in assistant.ui.messages))
        stream.close.assert_called_once()

    def test_playback_reopens_when_default_output_changes(self):
        assistant = self._assistant_with_chunks([b"audio"])
        write_threads = []
        first_stream = SimpleNamespace(
            device=0,
            active=True,
            start=Mock(),
            write=Mock(),
            stop=Mock(),
            close=Mock(),
        )
        second_stream = SimpleNamespace(
            device=1,
            active=True,
            start=Mock(),
            write=Mock(
                side_effect=lambda chunk: write_threads.append(
                    threading.current_thread().name
                )
            ),
            stop=Mock(),
            close=Mock(),
        )
        sounddevice = SimpleNamespace(
            RawOutputStream=Mock(side_effect=[first_stream, second_stream]),
            query_devices=Mock(
                side_effect=[
                    {"index": 0},
                    {"index": 1},
                    {"index": 1},
                ]
            ),
        )

        with patch.object(main, "sd", sounddevice):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(assistant._play_audio())

        first_stream.close.assert_called_once()
        second_stream.write.assert_called_once_with(b"audio")
        second_stream.close.assert_called_once()
        self.assertEqual(write_threads, ["niang-audio-output_0"])
        self.assertEqual(sounddevice.RawOutputStream.call_args.kwargs["blocksize"], 0)
        self.assertEqual(
            [call.kwargs["device"] for call in sounddevice.RawOutputStream.call_args_list],
            [0, 1],
        )

    def test_missing_microphone_driver_leaves_text_input_available(self):
        assistant = object.__new__(main.KaizumiLive)
        assistant.ui = _FakeUI()
        sounddevice = SimpleNamespace(
            InputStream=Mock(side_effect=RuntimeError("no recording device")),
        )

        with patch.object(main, "sd", sounddevice):
            with patch.object(main.asyncio, "sleep", side_effect=asyncio.CancelledError):
                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(assistant._listen_audio())

        self.assertIn("Microphone indisponible", assistant.ui.messages[0])

    def test_microphone_stream_reopens_when_default_input_changes(self):
        assistant = object.__new__(main.KaizumiLive)
        assistant.ui = _FakeUI()
        first_stream = _FakeInputStream(device=1)
        second_stream = _FakeInputStream(device=2)
        sounddevice = SimpleNamespace(
            InputStream=Mock(side_effect=[first_stream, second_stream]),
            query_devices=Mock(return_value={"index": 2}),
        )

        with patch.object(main, "sd", sounddevice):
            with patch.object(main.asyncio, "sleep", side_effect=[None, asyncio.CancelledError]):
                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(assistant._listen_audio())

        self.assertEqual(sounddevice.InputStream.call_count, 2)
        self.assertEqual(
            [call.kwargs["device"] for call in sounddevice.InputStream.call_args_list],
            [2, 2],
        )

    def test_default_audio_device_uses_resolved_device_index(self):
        sounddevice = SimpleNamespace(
            query_devices=Mock(return_value={"index": 3}),
            default=SimpleNamespace(device=[None, None]),
        )

        with patch.object(main, "sd", sounddevice):
            self.assertEqual(main._default_audio_device_index("input"), 3)

        sounddevice.query_devices.assert_called_once_with(kind="input")

    def test_microphone_queue_discards_stale_audio_when_full(self):
        assistant = object.__new__(main.KaizumiLive)
        assistant.out_queue = asyncio.Queue(maxsize=2)

        assistant._safe_put_mic(b"first")
        assistant._safe_put_mic(b"second")
        assistant._safe_put_mic(b"latest")

        self.assertEqual(assistant.out_queue.get_nowait()["data"], b"second")
        self.assertEqual(assistant.out_queue.get_nowait()["data"], b"latest")


if __name__ == "__main__":
    unittest.main()

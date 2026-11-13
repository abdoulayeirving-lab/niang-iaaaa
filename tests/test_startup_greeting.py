import os
import sys
import unittest
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import KaizumiLive, _starts_in_background


class StartupVisibilityTests(unittest.TestCase):
    def test_normal_and_wake_startup_are_visible_by_default(self):
        self.assertFalse(_starts_in_background([]))
        self.assertFalse(_starts_in_background(["--wake"]))
        self.assertFalse(_starts_in_background(["--remote"]))

    def test_explicit_background_flags_still_start_hidden(self):
        for flag in ("--background", "--hidden", "--minimized"):
            with self.subTest(flag=flag):
                self.assertTrue(_starts_in_background([flag]))


class StartupGreetingTests(unittest.IsolatedAsyncioTestCase):
    def make_assistant(self, silent_mode=False):
        assistant = object.__new__(KaizumiLive)
        assistant._startup_greeting_sent = False
        assistant._pending_text_inputs = []
        assistant._pending_text_inputs_lock = threading.Lock()
        assistant.session = SimpleNamespace(send_realtime_input=AsyncMock())
        assistant.ui = SimpleNamespace(
            silent_mode=silent_mode,
            write_log=Mock(),
        )
        return assistant

    async def test_greets_user_without_waiting_for_input(self):
        assistant = self.make_assistant()

        with patch("main.load_memory", return_value={"identity": {"name": {"value": "Aminata"}}}):
            await assistant._send_startup_greeting()

        assistant.session.send_realtime_input.assert_awaited_once()
        prompt = assistant.session.send_realtime_input.await_args.kwargs["text"]
        self.assertIn("Greet the user aloud", prompt)
        self.assertIn('"Aminata"', prompt)
        self.assertIn("do not substitute another name", prompt)
        self.assertIn("Do not wait for the user to speak or type first", prompt)
        self.assertTrue(assistant._startup_greeting_sent)
        assistant.ui.write_log.assert_called_once()

    async def test_greets_without_guessing_when_no_preferred_name_is_saved(self):
        assistant = self.make_assistant()

        with patch("main.load_memory", return_value={"identity": {}}):
            await assistant._send_startup_greeting()

        prompt = assistant.session.send_realtime_input.await_args.kwargs["text"]
        self.assertIn("without guessing or inventing a name", prompt)
        self.assertNotIn("George", prompt)

    async def test_does_not_repeat_greeting_after_reconnection(self):
        assistant = self.make_assistant()
        assistant._startup_greeting_sent = True

        await assistant._send_startup_greeting()

        assistant.session.send_realtime_input.assert_not_awaited()
        assistant.ui.write_log.assert_not_called()

    async def test_respects_text_only_mode(self):
        assistant = self.make_assistant(silent_mode=True)

        await assistant._send_startup_greeting()

        assistant.session.send_realtime_input.assert_not_awaited()
        self.assertTrue(assistant._startup_greeting_sent)
        assistant.ui.write_log.assert_not_called()


class TextInputMemoryTests(unittest.TestCase):
    def make_assistant(self):
        assistant = object.__new__(KaizumiLive)
        assistant._pending_text_inputs = []
        assistant._pending_text_inputs_lock = threading.Lock()
        return assistant

    def test_consumes_typed_input_when_server_does_not_transcribe_it(self):
        assistant = self.make_assistant()
        assistant._pending_text_inputs.append("Remember that I prefer quiet mornings.")

        captured = assistant._consume_text_input("")

        self.assertEqual(captured, "Remember that I prefer quiet mornings.")
        self.assertEqual(assistant._pending_text_inputs, [])

    def test_avoids_duplicate_when_server_transcribes_typed_input(self):
        assistant = self.make_assistant()
        assistant._pending_text_inputs.append("Remember that I prefer quiet mornings.")

        captured = assistant._consume_text_input(
            "Remember that I prefer quiet mornings!"
        )

        self.assertEqual(captured, "Remember that I prefer quiet mornings!")
        self.assertEqual(assistant._pending_text_inputs, [])


if __name__ == "__main__":
    unittest.main()

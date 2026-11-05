import asyncio
import threading
import unittest
from unittest.mock import patch

from actions import browser_control, playwright_mcp


class MissionBrowserIsolationTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(self._clear_mcp_clients)
        with playwright_mcp._mission_clients_lock:
            playwright_mcp._mission_clients.clear()
            playwright_mcp._mission_client_keys.clear()

    @staticmethod
    def _clear_mcp_clients():
        with playwright_mcp._mission_clients_lock:
            clients = list(playwright_mcp._mission_clients.values())
            playwright_mcp._mission_clients.clear()
            playwright_mcp._mission_client_keys.clear()
        for client in clients:
            client.close()

    def test_ephemeral_missions_receive_distinct_mcp_clients(self):
        first_key, first = playwright_mcp._client_for_mission({}, "mission-one")
        second_key, second = playwright_mcp._client_for_mission({}, "mission-two")
        again_key, again = playwright_mcp._client_for_mission({}, "mission-one")

        self.assertEqual(first_key, "mission:mission-one")
        self.assertEqual(second_key, "mission:mission-two")
        self.assertIsNot(first, second)
        self.assertIs(first, again)
        self.assertEqual(again_key, first_key)

    def test_named_persistent_session_is_explicit_and_reused_by_name(self):
        key, first = playwright_mcp._client_for_mission(
            {"persistent_session_id": "work-profile"},
            "mission-one",
        )
        other_key, second = playwright_mcp._client_for_mission(
            {"persistent_session_id": "work-profile"},
            "mission-two",
        )

        self.assertEqual(key, "persistent:work-profile")
        self.assertEqual(other_key, key)
        self.assertIs(first, second)

    def test_invalid_persistent_session_name_is_rejected(self):
        with self.assertRaises(playwright_mcp.PlaywrightMCPError):
            playwright_mcp._client_for_mission(
                {"persistent_session_id": "../profile"},
                "mission-one",
            )

    def test_fallback_browser_instances_are_distinct_per_ephemeral_mission(self):
        class FakeBrowser:
            def __init__(self):
                self.started = False

            def start(self):
                self.started = True

        with (
            patch.object(browser_control, "_BrowserThread", FakeBrowser),
            patch.dict(browser_control._mission_browsers, {}, clear=True),
            patch.dict(browser_control._mission_browser_keys, {}, clear=True),
        ):
            first = browser_control._ensure_started("mission-one")
            second = browser_control._ensure_started("mission-two")

        self.assertIsNot(first, second)
        self.assertTrue(first.started)
        self.assertTrue(second.started)

    def test_cancel_request_sets_the_active_mcp_action_event(self):
        client = playwright_mcp.PlaywrightMCPClient()
        event = threading.Event()
        client._active_cancel_event = event

        client.request_cancel()

        self.assertTrue(event.is_set())

    def test_cancel_during_mcp_action_cancels_coroutine_and_stops_client_loop(self):
        client = playwright_mcp.PlaywrightMCPClient()
        action_started = threading.Event()
        cancel_event = threading.Event()
        failures = []

        async def stalled_action(*_args):
            action_started.set()
            await asyncio.Event().wait()

        def call_action():
            try:
                client.call_tool(
                    "go_to",
                    {},
                    cancel_event=cancel_event,
                    timeout_s=5,
                )
            except Exception as exc:
                failures.append(exc)

        with patch.object(client, "_call_tool", side_effect=stalled_action):
            worker = threading.Thread(target=call_action, daemon=True)
            worker.start()
            self.assertTrue(action_started.wait(timeout=2))
            cancel_event.set()
            worker.join(timeout=5)

        self.assertFalse(worker.is_alive())
        self.assertIsInstance(failures[0], playwright_mcp.PlaywrightMCPCancelled)
        self.assertIsNone(client._loop)


if __name__ == "__main__":
    unittest.main()

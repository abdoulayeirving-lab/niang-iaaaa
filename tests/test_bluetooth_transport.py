import asyncio
import unittest
from unittest.mock import AsyncMock

from remote.bluetooth_transport import BluetoothBridge, BluetoothRemoteClient


class BluetoothDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatches_write_using_write_characteristic(self):
        bridge = BluetoothBridge.__new__(BluetoothBridge)
        bridge._clients_lock = asyncio.Lock()
        client = BluetoothRemoteClient("BLE")
        write_char = object()
        notify_char = object()
        client.bind_write(write_char)
        client.bind_notify(notify_char)
        bridge._clients = {client}
        bridge._handle_message = AsyncMock()

        payload = b"framed message"
        await bridge._dispatch_client(write_char, payload)

        bridge._handle_message.assert_awaited_once_with(client, payload)


if __name__ == "__main__":
    unittest.main()

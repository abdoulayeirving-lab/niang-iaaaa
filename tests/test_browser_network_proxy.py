import socket
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

from actions.browser_network_proxy import BrowserNetworkProxy, _BrowserProxyHandler
from actions.browser_security import BrowserURLPolicyError


class BrowserNetworkProxyTests(unittest.TestCase):
    def test_local_target_is_allowed_only_for_the_exact_managed_preview_port(self):
        handler = object.__new__(_BrowserProxyHandler)
        with patch(
            "agent.project_execution.is_authorized_local_preview_target",
            side_effect=lambda host, port: host == "127.0.0.1" and port == 5187,
        ):
            self.assertEqual(
                handler._target("http", "127.0.0.1:5187"),
                ("127.0.0.1", 5187, ["127.0.0.1"]),
            )
            with self.assertRaises(BrowserURLPolicyError):
                handler._target("http", "127.0.0.1:5188")

    def test_blocks_private_targets_for_connect_and_http_requests(self):
        proxy = BrowserNetworkProxy()
        try:
            address = urlsplit(proxy.endpoint)
            for request in (
                "CONNECT 127.0.0.1:443 HTTP/1.1\r\nHost: 127.0.0.1:443\r\n\r\n",
                "GET http://127.0.0.1/admin HTTP/1.1\r\n"
                "Host: 127.0.0.1\r\nConnection: close\r\n\r\n",
            ):
                with self.subTest(request=request.splitlines()[0]):
                    with socket.create_connection(
                        (address.hostname, address.port), timeout=5
                    ) as connection:
                        connection.sendall(request.encode("ascii"))
                        chunks = []
                        while chunk := connection.recv(4096):
                            chunks.append(chunk)
                        response = b"".join(chunks).decode("iso-8859-1")
                    self.assertIn(" 403 ", response.split("\r\n", 1)[0])
                    self.assertIn("private or reserved", response)
        finally:
            proxy.close()


if __name__ == "__main__":
    unittest.main()

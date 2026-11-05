"""Local egress proxy that applies NIANG IA's browser URL policy per request."""

from __future__ import annotations

import select
import socket
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

from actions.browser_security import BrowserURLPolicyError, resolve_safe_browser_host


class _BrowserProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    rbufsize = 0
    wbufsize = 0

    def handle(self) -> None:
        try:
            super().handle()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, TimeoutError):
            return

    def log_message(self, _format: str, *_args) -> None:
        return

    def _target(self, scheme: str, authority: str) -> tuple[str, int, list[str]]:
        parsed = urlsplit(f"{scheme}://{authority}")
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise BrowserURLPolicyError("Invalid browser proxy target.")
        try:
            port = parsed.port
        except ValueError as exc:
            raise BrowserURLPolicyError("Invalid browser proxy port.") from exc
        if port is None:
            port = 443 if scheme == "https" else 80
        if not 1 <= port <= 65535:
            raise BrowserURLPolicyError("Invalid browser proxy port.")
        try:
            addresses = resolve_safe_browser_host(parsed.hostname)
        except BrowserURLPolicyError:
            from agent.project_execution import is_authorized_local_preview_target
            if (
                parsed.hostname.casefold().rstrip(".") != "127.0.0.1"
                or not is_authorized_local_preview_target(parsed.hostname, port)
            ):
                raise
            addresses = resolve_safe_browser_host(
                parsed.hostname,
                allowed_local_hosts={parsed.hostname},
            )
        return parsed.hostname, port, addresses

    @staticmethod
    def _connect(addresses: list[str], port: int) -> socket.socket:
        last_error = None
        for address in addresses:
            try:
                return socket.create_connection((address, port), timeout=10)
            except OSError as exc:
                last_error = exc
        raise OSError("No resolved address could be reached.") from last_error

    def _deny(self, status: int, message: str) -> None:
        body = message.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_CONNECT(self) -> None:
        try:
            _, port, addresses = self._target("https", self.path)
            upstream = self._connect(addresses, port)
        except BrowserURLPolicyError as exc:
            self._deny(403, str(exc))
            return
        except OSError:
            self._deny(502, "The browser proxy could not reach the requested host.")
            return

        with upstream:
            upstream.setblocking(False)
            self.send_response(200, "Connection Established")
            self.end_headers()
            client = self.connection
            client.settimeout(None)
            upstream.settimeout(None)
            peers = (client, upstream)
            while True:
                try:
                    readable, _, exceptional = select.select(peers, (), peers, 300)
                except (OSError, ValueError):
                    break
                if exceptional or not readable:
                    break
                disconnected = False
                for source in readable:
                    try:
                        data = source.recv(65536)
                    except OSError:
                        disconnected = True
                        break
                    if not data:
                        disconnected = True
                        break
                    destination = upstream if source is client else client
                    try:
                        destination.sendall(data)
                    except OSError:
                        disconnected = True
                        break
                if disconnected:
                    break
            client.setblocking(True)

    def _forward_http(self) -> None:
        try:
            parsed = urlsplit(self.path)
            if parsed.scheme.lower() != "http" or not parsed.hostname:
                raise BrowserURLPolicyError("Only HTTP(S) browser proxy requests are allowed.")
            host, port, addresses = self._target("http", parsed.netloc)
            upstream = self._connect(addresses, port)
        except BrowserURLPolicyError as exc:
            self._deny(403, str(exc))
            return
        except OSError:
            self._deny(502, "The browser proxy could not reach the requested host.")
            return

        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        headers = [
            (key, value)
            for key, value in self.headers.items()
            if key.lower() not in {"proxy-authorization", "proxy-connection", "connection"}
        ]
        if not any(key.lower() == "host" for key, _ in headers):
            headers.append(("Host", host if port == 80 else f"{host}:{port}"))
        headers.append(("Connection", "close"))

        try:
            if self.headers.get("Transfer-Encoding"):
                self._deny(501, "Chunked browser proxy request bodies are not supported.")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._deny(400, "Invalid browser proxy request body length.")
                return
            if length < 0 or length > 20 * 1024 * 1024:
                self._deny(413, "Browser proxy request body exceeds 20 MiB.")
                return
            request = [f"{self.command} {path} {self.request_version}\r\n"]
            request.extend(f"{key}: {value}\r\n" for key, value in headers)
            request.append("\r\n")
            upstream.sendall("".join(request).encode("iso-8859-1"))
            remaining = length
            while remaining:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    raise OSError("Incomplete request body.")
                upstream.sendall(chunk)
                remaining -= len(chunk)
            upstream.settimeout(30)
            while True:
                data = upstream.recv(65536)
                if not data:
                    break
                self.wfile.write(data)
        except OSError:
            self.close_connection = True
        finally:
            upstream.close()
            self.close_connection = True

    do_GET = _forward_http
    do_POST = _forward_http
    do_PUT = _forward_http
    do_PATCH = _forward_http
    do_DELETE = _forward_http
    do_OPTIONS = _forward_http
    do_HEAD = _forward_http


class BrowserNetworkProxy:
    """Starts a loopback-only proxy for an isolated MCP browser context."""

    def __init__(self) -> None:
        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
            block_on_close = False

        self._server = Server(("127.0.0.1", 0), _BrowserProxyHandler)
        self._worker = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="BrowserNetworkPolicyProxy",
        )
        self._worker.start()

    @property
    def endpoint(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._worker.join(timeout=2)

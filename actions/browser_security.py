"""URL policy for browser navigation and requests."""

from __future__ import annotations

import ipaddress
import os
import re
import socket
from urllib.parse import urlsplit, urlunsplit
from collections.abc import Callable, Sequence


class BrowserURLPolicyError(ValueError):
    """Raised when a URL is outside the browser's network policy."""


def _resolve_addresses(host: str) -> list[str]:
    return list({
        result[4][0]
        for result in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    })


def _local_host_allowlist() -> set[str]:
    return {
        host.strip().rstrip(".").lower()
        for host in os.environ.get("NIANG_IA_BROWSER_ALLOWED_LOCAL_HOSTS", "").split(",")
        if host.strip()
    }


def validate_browser_url(
    value: str,
    *,
    resolve_host: Callable[[str], Sequence[str]] = _resolve_addresses,
    allowed_local_hosts: set[str] | None = None,
) -> str:
    """Normalize an HTTP(S) URL and reject local, private, or unresolved hosts."""
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise BrowserURLPolicyError("A valid URL of at most 2048 characters is required.")

    raw_url = value.strip()
    parsed = urlsplit(raw_url)
    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        bare_host_port = re.fullmatch(
            r"(?P<host>[^/:?#]+):\d+(?:/.*)?",
            raw_url,
        )
        if not bare_host_port or "." not in bare_host_port.group("host"):
            raise BrowserURLPolicyError("Only HTTP and HTTPS URLs are allowed.")
        raw_url = "https://" + raw_url
    elif not parsed.scheme:
        raw_url = "https://" + raw_url

    try:
        parsed = urlsplit(raw_url)
        hostname = parsed.hostname
        parsed.port
    except ValueError as exc:
        raise BrowserURLPolicyError(f"Invalid URL: {exc}") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise BrowserURLPolicyError("Only HTTP and HTTPS URLs are allowed.")
    if parsed.username is not None or parsed.password is not None:
        raise BrowserURLPolicyError("URLs containing embedded credentials are not allowed.")
    if not hostname:
        raise BrowserURLPolicyError("The URL must include a hostname.")

    host = hostname.rstrip(".").lower()
    allowlist = (
        {item.rstrip(".").lower() for item in allowed_local_hosts}
        if allowed_local_hosts is not None
        else _local_host_allowlist()
    )
    if host in allowlist:
        return urlunsplit(parsed._replace(scheme=parsed.scheme.lower()))

    if (
        host == "localhost"
        or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid", ".example"))
        or host == "metadata.google.internal"
    ):
        raise BrowserURLPolicyError("Local and internal hostnames are blocked.")

    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addresses = [str(ipaddress.ip_address(item)) for item in resolve_host(host)]
        except (OSError, ValueError) as exc:
            raise BrowserURLPolicyError(f"Could not safely resolve host '{host}'.") from exc
        if not addresses:
            raise BrowserURLPolicyError(f"Could not safely resolve host '{host}'.")

    if any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise BrowserURLPolicyError("URLs resolving to private or reserved addresses are blocked.")

    return urlunsplit(parsed._replace(scheme=parsed.scheme.lower()))

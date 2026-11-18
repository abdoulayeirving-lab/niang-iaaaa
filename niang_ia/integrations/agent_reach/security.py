"""Input and URL validation for externally dispatched, read-only requests."""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import parse_qs, urlsplit

from agent.secrets import detect_sensitive_data
from user_data_paths import persistent_path


_GITHUB_TARGET = re.compile(
    r"^(?:https://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:\.git)?"
    r"(?:/(?:issues|pull)/[0-9]+)?/?(?:[?#][^\s]*)?$",
    re.IGNORECASE,
)
_SUBREDDIT = re.compile(r"^[A-Za-z0-9_]{2,21}$")
_SYMBOL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,15}$")
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_BILIBILI_ID = re.compile(r"^BV[0-9A-Za-z]{10}$")
_POST_ID = re.compile(r"^[A-Za-z0-9]{5,32}$")
_HOSTS = {
    "twitter_post": ("x.com", "twitter.com"),
    "youtube_video": ("youtube.com", "youtu.be"),
    "reddit_target": ("reddit.com", "redd.it"),
    "bilibili_video": ("bilibili.com", "b23.tv"),
    "linkedin_job": ("linkedin.com",),
    "boss_job": ("zhipin.com",),
    "v2ex_topic": ("v2ex.com",),
}


class AgentReachInputError(ValueError):
    """A request is outside the integration's explicit input policy."""


def session_reuse_allowed() -> bool:
    """Return whether the local installer explicitly authorized browser-session reuse."""
    consent_path = persistent_path("config/agent_reach_session_reuse.txt")
    try:
        consent = consent_path.read_text(encoding="utf-8").strip().casefold()
    except FileNotFoundError:
        return False
    return consent == "true"


def validate_query(value: object) -> str:
    if not isinstance(value, str):
        raise AgentReachInputError("A text query is required.")
    query = value.strip()
    if (
        not query
        or len(query) > 500
        or query.startswith("-")
        or any(ord(char) < 32 for char in query)
    ):
        raise AgentReachInputError("The query must contain 1 to 500 printable characters.")
    if detect_sensitive_data(query):
        raise AgentReachInputError("The query appears to contain sensitive data and was not sent.")
    return query


def validate_subreddit(value: object) -> str:
    if not isinstance(value, str):
        raise AgentReachInputError("A subreddit name is required.")
    name = value.strip()
    if name.startswith("r/"):
        name = name[2:]
    if not _SUBREDDIT.fullmatch(name):
        raise AgentReachInputError("The subreddit name is invalid.")
    return name


def validate_github_target(value: object) -> str:
    if not isinstance(value, str) or not _GITHUB_TARGET.fullmatch(value.strip()):
        raise AgentReachInputError("Use a public GitHub owner/repository, issue, or pull-request URL.")
    return value.strip()


def validate_channel_input(value: object, kind: str) -> str:
    if kind == "query":
        return validate_query(value)
    if kind == "subreddit":
        return validate_subreddit(value)
    if kind == "github_target":
        return validate_github_target(value)
    if kind == "symbol":
        if not isinstance(value, str) or not _SYMBOL.fullmatch(value.strip()):
            raise AgentReachInputError("Use a short public stock symbol.")
        return value.strip()
    if kind == "username":
        name = validate_query(value)
        name = name.lstrip("@")
        if not name or len(name) > 100:
            raise AgentReachInputError("The username is too long.")
        return name
    if kind == "url":
        return validate_public_url(value)
    if kind == "youtube_video" and isinstance(value, str) and _YOUTUBE_ID.fullmatch(value.strip()):
        return value.strip()
    if kind == "bilibili_video" and isinstance(value, str) and _BILIBILI_ID.fullmatch(value.strip()):
        return value.strip()
    if kind == "twitter_post" and isinstance(value, str) and _POST_ID.fullmatch(value.strip()):
        return value.strip()
    if kind == "reddit_target" and isinstance(value, str) and _POST_ID.fullmatch(value.strip()):
        return value.strip()
    if kind == "v2ex_topic" and isinstance(value, str) and value.strip().isdigit():
        return value.strip()
    if kind in {
        "youtube_video", "bilibili_video", "twitter_post", "reddit_target",
        "linkedin_job", "boss_job", "v2ex_topic",
    }:
        url = validate_public_url(value)
        _validate_allowed_host(url, _HOSTS[kind])
        _validate_channel_path(url, kind)
        return url
    raise AgentReachInputError("This Agent-Reach argument type is not supported.")


def validate_option(value: object, option: str) -> str:
    if option == "limit":
        if type(value) is not int or not 1 <= value <= 5:
            raise AgentReachInputError("Result limit must be from 1 to 5.")
        return str(value)
    text = validate_query(value)
    if option in {"city", "location"}:
        if len(text) > 100:
            raise AgentReachInputError(f"The {option} value is too long.")
        return text
    if option == "lang":
        languages = text.split(",")
        if len(languages) > 8 or any(
            not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?", item.strip())
            for item in languages
        ):
            raise AgentReachInputError("The subtitle language list is invalid.")
        return ",".join(item.strip() for item in languages)
    raise AgentReachInputError("This Agent-Reach option is not supported.")


def validate_public_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise AgentReachInputError("A public HTTP(S) URL is required.")
    url = value.strip()
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"}:
            raise AgentReachInputError("Only public HTTP(S) URLs without credentials are allowed.")
        expected_port = {"http": 80, "https": 443}[parts.scheme.lower()]
        if (
            not parts.hostname
            or parts.username is not None
            or parts.password is not None
            or parts.port not in {None, expected_port}
            or any(ord(char) < 32 for char in url)
        ):
            raise AgentReachInputError("Only public HTTP(S) URLs without credentials are allowed.")
        host = parts.hostname.rstrip(".").encode("idna").decode("ascii").lower()
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
            raise AgentReachInputError("Local and private network URLs are not allowed.")
        try:
            addresses = {ipaddress.ip_address(host)}
        except ValueError:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(host, parts.port or 443, type=socket.SOCK_STREAM)
            }
    except AgentReachInputError:
        raise
    except (OSError, UnicodeError, ValueError):
        raise AgentReachInputError("The URL host could not be validated as public.") from None
    if not addresses or any(not address.is_global for address in addresses):
        raise AgentReachInputError("Local and private network URLs are not allowed.")
    return url


def _validate_allowed_host(url: str, domains: tuple[str, ...]) -> None:
    host = urlsplit(url).hostname
    host = host.rstrip(".").casefold() if host else ""
    if not any(host == domain or host.endswith(f".{domain}") for domain in domains):
        raise AgentReachInputError("The URL does not belong to the selected public channel.")


def _validate_channel_path(url: str, kind: str) -> None:
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    valid = True
    if kind == "youtube_video":
        valid = (
            (parts.hostname or "").casefold().endswith("youtu.be")
            and bool(_YOUTUBE_ID.fullmatch(path.lstrip("/")))
        ) or (
            (parts.hostname or "").casefold().endswith("youtube.com")
            and path == "/watch"
            and bool(_YOUTUBE_ID.fullmatch(parse_qs(parts.query).get("v", [""])[0]))
        )
    elif kind == "bilibili_video":
        host = (parts.hostname or "").casefold()
        valid = (
            bool(re.fullmatch(r"/video/BV[0-9A-Za-z]{10}(?:/.*)?", path))
            if host.endswith("bilibili.com")
            else bool(re.fullmatch(r"/[A-Za-z0-9]+", path))
        )
    elif kind == "twitter_post":
        valid = bool(re.fullmatch(r"/(?:[^/]+/status|i/status)/[0-9]+", path))
    elif kind == "reddit_target":
        host = (parts.hostname or "").casefold()
        valid = (
            bool(re.fullmatch(r"/[A-Za-z0-9]+", path))
            if host.endswith("redd.it")
            else bool(re.search(r"/comments/[A-Za-z0-9]+(?:/|$)", path))
        )
    elif kind == "linkedin_job":
        valid = bool(re.fullmatch(r"/jobs/view/(?:[^/]+-)?[0-9]+", path))
    elif kind == "boss_job":
        valid = bool(re.fullmatch(r"/job_detail/[A-Za-z0-9_-]+\.html", path))
    elif kind == "v2ex_topic":
        valid = bool(re.fullmatch(r"/t/[0-9]+", path))
    if not valid:
        raise AgentReachInputError("The URL path is not a supported public target for this channel.")

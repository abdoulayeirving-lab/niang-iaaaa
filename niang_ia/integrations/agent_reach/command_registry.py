"""Explicit allowlist of public, read-only Agent-Reach actions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    channel: str
    action: str
    input_name: str | None = None
    input_kind: str | None = None
    options: tuple[str, ...] = ()
    backend: str | None = None
    public_without_login: bool = False


def _action(
    channel: str,
    action: str,
    input_name: str | None = None,
    input_kind: str | None = None,
    *,
    options: tuple[str, ...] = (),
    backend: str | None = None,
    public_without_login: bool = False,
) -> CommandSpec:
    return CommandSpec(
        channel, action, input_name, input_kind, options, backend, public_without_login,
    )


COMMANDS = {
    ("web", "search"): _action(
        "web", "search", "query", "query", options=("limit",), public_without_login=True,
    ),
    ("web", "read"): _action(
        "web", "read", "target", "url", public_without_login=True,
    ),
    ("github", "search"): _action(
        "github", "search", "query", "query", options=("limit",), public_without_login=True,
    ),
    ("github", "read"): _action(
        "github", "read", "target", "github_target", public_without_login=True,
    ),
    ("twitter", "search"): _action(
        "twitter", "search", "query", "query", options=("limit",),
        backend="public-web", public_without_login=True,
    ),
    ("twitter", "profile"): _action("twitter", "profile", "username", "username"),
    ("twitter", "tweets"): _action(
        "twitter", "tweets", "username", "username", options=("limit",),
    ),
    ("twitter", "thread"): _action("twitter", "thread", "target", "twitter_post"),
    ("youtube", "search"): _action(
        "youtube", "search", "query", "query", options=("limit",), public_without_login=True,
    ),
    ("youtube", "read"): _action(
        "youtube", "read", "target", "youtube_video", public_without_login=True,
    ),
    ("youtube", "subtitle"): _action(
        "youtube", "subtitle", "target", "youtube_video", options=("lang",),
        public_without_login=True,
    ),
    ("reddit", "search"): _action(
        "reddit", "search", "query", "query", options=("limit",),
        backend="public-web", public_without_login=True,
    ),
    ("reddit", "read"): _action(
        "reddit", "read", "target", "reddit_target",
        backend="public-web", public_without_login=True,
    ),
    ("reddit", "subreddit"): _action("reddit", "subreddit", "subreddit", "subreddit", options=("limit",)),
    ("facebook", "search"): _action(
        "facebook", "search", "query", "query", options=("limit",),
        backend="public-web", public_without_login=True,
    ),
    ("facebook", "profile"): _action("facebook", "profile", "username", "username"),
    ("instagram", "search"): _action(
        "instagram", "search", "query", "query", options=("limit",),
    ),
    ("instagram", "profile"): _action("instagram", "profile", "username", "username"),
    ("instagram", "posts"): _action(
        "instagram", "posts", "username", "username", options=("limit",),
    ),
    ("bilibili", "search"): _action(
        "bilibili", "search", "query", "query", options=("limit",), public_without_login=True,
    ),
    ("bilibili", "read"): _action(
        "bilibili", "read", "target", "bilibili_video", public_without_login=True,
    ),
    ("bilibili", "hot"): _action(
        "bilibili", "hot", options=("limit",), public_without_login=True,
    ),
    ("xiaohongshu", "search"): _action(
        "xiaohongshu", "search", "query", "query", options=("limit",),
        backend="public-web", public_without_login=True,
    ),
    ("linkedin", "jobs"): _action(
        "linkedin", "jobs", "query", "query", options=("limit", "location"),
        backend="public-web", public_without_login=True,
    ),
    ("linkedin", "read"): _action(
        "linkedin", "read", "target", "linkedin_job",
        backend="public-web", public_without_login=True,
    ),
    ("boss", "search"): _action(
        "boss", "search", "query", "query", options=("limit", "city"),
        backend="public-web", public_without_login=True,
    ),
    ("boss", "read"): _action(
        "boss", "read", "target", "boss_job",
        backend="public-web", public_without_login=True,
    ),
    ("v2ex", "hot"): _action("v2ex", "hot", options=("limit",), public_without_login=True),
    ("v2ex", "node"): _action(
        "v2ex", "node", "query", "query", options=("limit",), public_without_login=True,
    ),
    ("v2ex", "read"): _action(
        "v2ex", "read", "target", "v2ex_topic", public_without_login=True,
    ),
    ("v2ex", "user"): _action("v2ex", "user", "username", "username", public_without_login=True),
    ("xueqiu", "quote"): _action("xueqiu", "quote", "symbol", "symbol", public_without_login=True),
    ("xueqiu", "search"): _action(
        "xueqiu", "search", "query", "query", options=("limit",), public_without_login=True,
    ),
}

SUPPORTED_CHANNELS = (
    "github",
    "twitter",
    "youtube",
    "reddit",
    "facebook",
    "instagram",
    "bilibili",
    "xiaohongshu",
    "linkedin",
    "boss",
    "v2ex",
    "xueqiu",
    "xiaoyuzhou",
    "web",
)

SAFE_ACTIONS = {
    name: tuple(action for channel, action in COMMANDS if channel == name)
    for name in SUPPORTED_CHANNELS
}

MAX_QUERY_CHARS = 500
MAX_TEXT_CHARS = 100_000
MAX_RESULTS = 5
MAX_TIMEOUT_SECONDS = 60.0
MAX_STDOUT_BYTES = 2_000_000
MAX_STDERR_BYTES = 32_000

CHANNEL_STATUS_ARGS = ("channels",)
DOCTOR_ARGS = ("doctor",)

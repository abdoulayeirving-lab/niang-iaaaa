# Agent-Reach integration

NIANG IA can optionally call the separately installed Agent-Reach CLI for
read-only public research. The integration lives in
`niang_ia/integrations/agent_reach/`; Agent-Reach remains an external component.
The existing NIANG IA web search and YouTube tools remain the first-line tools.

## Connector coverage

The explicit allowlist covers these channels and public read-only actions:

| Agent-Reach channel | NIANG IA actions |
| --- | --- |
| Web / Exa | Search, read |
| GitHub | Repository search, repository / issue / PR read |
| X / Twitter | Search, profile, recent tweets, thread |
| YouTube | Search, video read, subtitles |
| Reddit | Search, post read, subreddit |
| Facebook | Search, public profile |
| Instagram | Search, public profile, recent posts |
| Bilibili | Search, video read, trending videos |
| Xiaohongshu | Public search |
| LinkedIn | Public job search and job read |
| BOSS | Public job search and job read |
| V2EX | Hot topics, node, topic read, public profile |
| Xueqiu | Public stock search and quote |

Capability discovery also reports the official Xiaoyuzhou channel, but its only
action is transcription through an external provider, so NIANG IA marks it
`DISABLED` pending explicit approval. YouTube transcription, Bilibili subtitles,
and Xueqiu community actions that can silently reuse local sessions are not
allowlisted. RSS is not a channel in the current Agent-Reach registry; Web search
and reading remain available instead. New or future Agent-Reach channels appear
as `DISABLED` until an explicit, reviewed action is added to the registry.

## Trust and command boundary

The adapter exposes only the operations in `command_registry.py`. It does not
expose setup, installation, update, login, logout, configuration, browser
management, transcription, or arbitrary CLI arguments. Where Agent-Reach offers
a public-web backend, NIANG IA selects it explicitly to avoid browser-session
fallback. Session-backed actions are blocked unless local `doctor` status is
`AVAILABLE`. Other configured channels are called only for their declared,
read-only actions; private content is never promised. Child processes use an
argument vector, never a shell, inherit only
a restricted environment, and have bounded time, stdout, stderr, and result
sizes. URL and query validation rejects local network targets and detected
credentials. Sensitive URL query parameters are removed from returned source
links. All fetched page text is untrusted external data.

Agent-Reach `doctor` status is local readiness evidence, not proof of live
platform access. `agent-reach check` performs network requests and is not run
automatically. `NEEDS_AUTH`, `DISABLED`, and `UNAVAILABLE` channels are not
queried for session-backed actions; allowlisted public-without-login actions can
use their public route when authentication is missing. The installer asks
separately before NIANG IA may use site-scoped cookies from a connected local
browser. Without that opt-in, session-backed actions are hidden from capability
discovery and are refused. If authorized, Agent-Reach can copy cookies only for
the requested site into its dedicated profile when that action runs; neither
installation nor local `doctor` checks copy cookies. NIANG IA does not ask for
or log credentials. A failed public request remains a failure; it is not
reported as a successful search.

## Installation and maintenance

The Windows installer offers a separate, unchecked-by-default opt-in to install
Agent-Reach. If selected, it downloads checksum-pinned `uv` 0.13.7 and the
official Agent-Reach 1.6.1 release, then runs the upstream `setup` and `add`
commands for all 14 declared channels. Channel dependencies can download
OpenCLI, a dedicated browser, Python/Node packages, and FFmpeg; network access
is required and no administrator permission is requested. The installer
verifies SHA-256 before executing the two pinned archives. If Python 3.12 is
missing, it installs the Python runtime already bundled with NIANG IA.

For this installer-managed CLI, the tool environment, cache, browser,
configuration, and state are isolated under
`%LOCALAPPDATA%\NIANG IA\agent_reach`; they are not installed into NIANG IA's
`.venv` or a global `uv` tool directory. If a user explicitly overrides the CLI
path to an existing installation, its existing Agent-Reach home is preserved.
The user can decline installation and still install NIANG IA. The installer
does not add API keys or log in to platforms. Xiaoyuzhou is installed as a connector, but NIANG IA keeps
transcription disabled until protected provider-key configuration is available;
provider calls will require a per-request high-risk confirmation and may incur
charges.

The user must separately opt in to local browser-session reuse. The choice is
stored as the non-secret `config/agent_reach_session_reuse.txt` preference
(`true` or `false`), and can be changed by rerunning the installer. No cookies,
keys, or tokens are stored in that file.

The pinned Agent-Reach CLI is installed from its official GitHub release:

`https://github.com/Panniantong/Agent-Reach/blob/main/docs/install.md`

The installer performs the equivalent of:

`agent-reach setup` plus `agent-reach add` for Twitter/X, Reddit, Facebook,
Instagram, Xiaohongshu, LinkedIn, BOSS, Xueqiu, and Xiaoyuzhou. Optional
browser channels can install OpenCLI, CloakBrowser, a managed browser, and
related extensions within the isolated Agent-Reach home. NIANG IA discovers
this CLI directly; a user-specified
`NIANG_IA_AGENT_REACH_EXECUTABLE` remains available as an override.

The local capability report lists declared actions and the CLI's cached/local
channel status. A real network test must be run separately and reported
separately. `agent-reach doctor` is local-only; `agent-reach check` performs
network requests and may trigger upstream cookie reuse. Never claim access to
private content without authorization. Channel login and provider-backed
transcription remain separate user choices; Xiaoyuzhou transcription is not
installed or allowlisted without explicit provider approval.

The developer machine currently has Agent-Reach 1.6.1 in a separate `uv` tool
environment. Defaults and optional connectors that do not need a transcription
key are installed there. Live public checks through NIANG IA
returned results for Web, GitHub, YouTube, Reddit, Bilibili, Xiaohongshu,
LinkedIn, BOSS, V2EX, and Xueqiu. Twitter/X and Facebook public-web searches
returned `UPSTREAM_BROKEN` (no usable public content); their session-backed
actions were not tested. Instagram, subtitles, and all session-backed actions
were not live-tested. Agent-Reach's `doctor` continues to report channels as
`unverified` until its explicit live-check command is run; successful adapter
queries do not change that local status.

## Tests

`python -m unittest tests.test_agent_reach_integration -v` runs offline unit
tests with a fake CLI. These tests do not establish that Agent-Reach is
installed or that any external platform is reachable.

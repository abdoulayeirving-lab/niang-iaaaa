# OpenCode integration

NIANG IA starts the installed OpenCode CLI as an Agent Client Protocol (ACP)
child process for software-development missions. The selected project is passed
as the session working directory, and progress and permission requests are
handled by NIANG IA. The existing Cline adapter remains available for older
saved missions; new development-panel and voice-routed missions use OpenCode.

## Requirements

- OpenCode CLI installed and available from the user's npm installation.
- OpenCode authenticated with a free OpenCode or OpenCode Go model.
- NIANG IA's Python environment has the `mcp` package from `requirements.txt`.
- Visual Studio Code installed to view the selected project while a mission runs.

OpenCode uses its existing local user configuration and provider credentials.
NIANG IA does not copy credentials into mission prompts or the ACP child
environment. Before a mission, NIANG IA intersects OpenCode's enabled models
with the public `models.dev` catalog and uses only models whose input, output,
and any listed cache prices are all zero and that support tool calls. The
selected model is set and verified through ACP before the task prompt is sent.
If pricing cannot be verified or no matching free model is enabled, the mission
stops before generation.

On a quota/HTTP 429 response, NIANG IA tries the next verified free model and
asks it to continue from the current workspace state. Authentication errors,
model-resolution errors, and other failures do not trigger a fallback. If all
free-model quotas are exhausted, the mission stops; it never falls back to a
paid model.

The development panel reports how many verified free models are available and
shows the active model and attempt number in mission progress. This preflight
checks the CLI model list and public pricing metadata; it does not verify
generation authentication or send a prompt. It also checks that the active
NIANG IA Python environment can import the MCP workspace server required for
file and preview tools. The Windows launchers repair declared dependencies
when this runtime package is missing.

## Modes and permissions

- **Plan** selects OpenCode's read-only plan agent through ACP session
  configuration. The mission is rejected if plan mode is unavailable or the
  agent tries to leave it.
- **Assisted** requests NIANG IA confirmation for each in-workspace file edit.
- **Autonomous controlled** is the default for a software-creation request. It
  may approve edits only for new files in the selected workspace. Existing-file
  edits and optional external actions still require confirmation.

The managed OpenCode configuration denies shell execution, external directories,
subagents, and web access; it allows project reads and sends edits through the
NIANG IA permission gate.
Credential and environment files are denied. Workspace-local OpenCode plugin
directories and `plugins`/`mcp` config entries are rejected because they can
launch host code outside NIANG IA's action gate. Global OpenCode user settings
and credentials remain in effect. Permission requests are checked against
NIANG IA's workspace path rules before they are presented or approved.

OpenCode receives a local stdio MCP server with four base tools:

- `run_check` runs a fixed Python/Node build, test, lint, or Git status check.
  Each check is individually confirmed and limited to 180 seconds.
- `install_dependency` supports only Python packages in a project virtual
  environment and Node packages installed with npm lifecycle scripts disabled.
  Each install is individually confirmed and limited to 180 seconds.
- `start_preview` serves existing static files on `127.0.0.1` only. It blocks
  hidden/credential files, directory listings, ignored build/dependency
  directories, and files over 10 MB. It does not execute a project server.
  The preview expires after 30 minutes; `stop_preview` stops it sooner.
  Starting and stopping the preview require confirmation.

When `visual-asset-intelligence` is selected, OpenCode also receives four
mission-scoped visual tools: inspect local images, search configured Pixabay
and Unsplash APIs, optionally search Pexels when both configured and explicitly
approved, save a selected result, and verify image references/metadata/credits.
The visual skill must be observed loading before these tools can be used.
Provider searches, image writes, and visual verification require NIANG IA
approval. Provider keys are read only from `NIANG_IA_PIXABAY_API_KEY`,
`NIANG_IA_UNSPLASH_ACCESS_KEY`, or `NIANG_IA_PEXELS_API_KEY` and are passed only
to the trusted local MCP child process when the visual skill is selected; they
are not added to the model prompt or OpenCode's general child environment.
Search results are cached locally with Pixabay's required 24-hour minimum
retention; cache keys are one-way hashes, and provider credentials are not
stored. No provider request is made when a key is absent.

No general shell, arbitrary command, delete, deployment, or system-control
tool is exposed. Plan mode denies all MCP tools. ACP messages are
newline-delimited JSON; the mission is capped at 80 reported tool actions and
30 minutes. OpenCode runs through ACP without launching VS Code or a browser
preview unless the user explicitly requests one; Cline continues to open its
required VS Code workspace.

## Skills and quality gate

NIANG IA selects up to 10 skills from the curated `web_design_skills/` library
for each mission: the existing general skills, the 15-skill elite engineering
profile (with `software-architecture` shared between them), and the dedicated
`visual-asset-intelligence` skill. The
engineering baseline includes `clean-code-engineering`,
`testing-debugging-mastery`, and `secure-software-engineering`. The managed
OpenCode config adds that source and permits the `skill` tool only for selected
IDs; all other skill IDs are denied. Skills are read-only guidance and do not
add workspace or shell permissions. Mission results distinguish selected
skills from skill IDs OpenCode reported loading. If the visual asset skill is
selected, the quality gate additionally requires host-reported asset
verification and keeps visual composition review `NOT_TESTED` unless it was
actually performed.

The mission result includes a quality gate: `PASS`, `FAIL`, or `NOT_TESTED`
(`NON TESTÉ`). It records host-observed test/build checks. Visual design,
responsive behavior, accessibility, interactions, performance, and security
remain `NOT_TESTED` without corresponding verification evidence.

Website and landing-page requests that reach the general project builder are
routed to this supervised OpenCode workflow instead of the Python project
generator. For a new workspace without an existing frontend stack, the task
requires actual `index.html`, `styles.css`, and `app.js` deliverables; an
installer script or Python-only file is not considered a website.

## Validation

Run the OpenCode integration tests without contacting a model provider:

```powershell
py -3.12 -m unittest discover -s tests -p test_opencode_integration.py -v
```

The tests use a fake ACP process and a loopback-only static preview. They verify
the handshake, bounded MCP tools, per-operation permission gate, preview file
restrictions, workspace checks, mode restrictions, action limit, executable
detection, and task-queue dispatch. They do not claim a live model-backed
coding mission.

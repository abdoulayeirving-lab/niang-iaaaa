# Cline software-development integration

This adapter runs Cline Agent SDK tasks with NIANG IA's bounded workspace tools.
OpenCode is a separate integration documented in `../opencode/README.md`.

NIANG IA routes software-project missions to `ClineEngine` through the existing
`TaskQueue`. The adapter uses the installed Cline Agent SDK (`@cline/agents`)
behind a small Node.js worker; Python and Node exchange newline-delimited JSON
messages. The Cline CLI is used for installation/version health checks, not for
unrestricted task execution.

## Start a mission

From the repository root, start NIANG IA with:

```powershell
py -3.12 main.py
```

The default provider is Cline Free. Its fallback order is Nemotron 3.5 Super VL,
Solar Mini 4, then Nemotron 3.5 Lightning Free. The local Ollama provider remains
available for explicitly configured local missions.

Open **DÉVELOPPEMENT LOGICIEL** in NIANG IA, select an existing project folder,
choose a mode, and enter the task. NIANG IA opens that folder in a new VS Code
window before starting Cline. The development panel shows progress and completed
workspace actions as they happen; VS Code reflects the Cline file writes in the
open project. If a voice request starts the mission, NIANG IA opens the
development panel on the configured workspace and updates it while the task is
running. The chat router can also start a mission in the configured
`NIANG_IA_WORKSPACE_ROOT` after NIANG IA's confirmation gate; it opens the
development panel and the same workspace in VS Code automatically.

Cline missions fail closed unless the Cline CLI and Agent SDK are available.
NIANG IA never copies API keys or credentials into the worker environment. A
quota fallback occurs only when the Cline SDK identifies its free-model limit
error; other failures stop the mission. If every free quota is exhausted, the
mission stops without selecting a paid model. An authenticated Cline account is
required and is checked by the provider when the first request is made.

## Modes and permissions

- **Plan**: exposes only workspace list, read, text-search, and (when selected)
  local visual-asset inspection tools.
- **Assisted**: asks before every write, patch, project check, or dependency install.
- **Autonomous controlled**: allows bounded in-workspace edits and new-file
  creation; overwrites, multi-file patches, dependency installs, and executable
  project checks still require approval.

The agent receives no general shell, delete, deployment, browser, or system
administration tool. Python and Node dependency installs are project-scoped;
Python requires a project `.venv`/`venv`, and npm lifecycle scripts are disabled.
Tests and build scripts run as the current Windows user, so NIANG IA asks before
running them; this is not an OS-level sandbox. UAC is not bypassed and no
administrator command is launched.

The adapter caps each mission at 20 workspace actions, each check/install at
180 seconds, and a mission at 1,800 seconds. Workspace paths are resolved
relative to the selected root; symlinks, credential files, environment files,
generated folders, hard-linked files, junctions, and oversized text files are
denied. Child processes receive an allowlisted environment without API-key
variables; cancellation and timeout handling also tracks and terminates
descendant processes. These checks reduce accidental exposure but do not replace
an OS sandbox. Mission history continues to use NIANG IA's encrypted mission
store.

Raw CLI task execution is intentionally not used: Cline CLI's built-in tools
include shell execution and do not provide the host-controlled workspace tool
boundary and per-action approval callback used here. SDK tool policies are
explicit; only read-only workspace access and skill loading are auto-approved.
When `visual-asset-intelligence` is selected and loaded, Cline can inspect local
images, search the configured Pixabay/Unsplash APIs, optionally search Pexels
when explicitly approved, save a selected image, and verify its local
references, provenance, and credits. Provider searches, writes, and verification
require explicit user approval. The Python host reads provider keys only from
`NIANG_IA_PIXABAY_API_KEY`, `NIANG_IA_UNSPLASH_ACCESS_KEY`, or
`NIANG_IA_PEXELS_API_KEY`; the Cline worker and model prompt never receive them.
No provider request is made without a configured key. Search results are
cached locally with a 24-hour minimum for Pixabay; cache entries contain no
provider keys or plaintext queries.

Each mission selects up to 10 skills from `web_design_skills/`: the existing
general skills, the 15-skill elite engineering profile (with
`software-architecture` shared between them). The engineering baseline includes
`clean-code-engineering`, `testing-debugging-mastery`, and
`secure-software-engineering`; `visual-asset-intelligence` is selected
automatically for image-dependent work. Cline receives only selected IDs and
descriptions; the `workspace_load_skill` host tool returns instructions only
after checking the ID against that mission's selection. Skill loading cannot
read arbitrary workspace files. Mission results distinguish selected skills
from skill IDs actually loaded and include a quality gate with `PASS`, `FAIL`,
or `NOT_TESTED`; missing visual, accessibility, security, or runtime evidence
is never reported as a pass.

## Validation

Run the isolated unit suite without requiring a live Cline task or paid model:

```powershell
py -3.12 tests\test_cline_integration.py
```

These tests use a fake process for protocol behavior. A passing unit suite does
not claim a real model-backed coding mission was executed.

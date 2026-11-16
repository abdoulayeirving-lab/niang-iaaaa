from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


MAX_ACTIONS = 20
MAX_ACTION_SECONDS = 180
MAX_MISSION_SECONDS = 1800
DEFAULT_PROVIDER = "ollama"
# qwen2.5-coder:7b returns tool calls as plain JSON text with Ollama in this
# SDK stack (not parsed as structured tool calls). qwen2.5:7b/qwen3:8b emit
# native tool calls compatible with ollama-ai-provider-v2 used by @cline/llms.
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_BASE_URL = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class ClineConfig:
    workspace_root: Path
    provider_id: str = DEFAULT_PROVIDER
    model_id: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    max_actions: int = MAX_ACTIONS
    action_timeout_seconds: int = MAX_ACTION_SECONDS
    mission_timeout_seconds: int = MAX_MISSION_SECONDS

    def __post_init__(self) -> None:
        root = Path(self.workspace_root).expanduser()
        is_junction = getattr(root, "is_junction", None)
        if root.is_symlink() or (is_junction is not None and is_junction()) or not root.is_dir():
            raise ValueError("The selected project folder must be an existing directory, not a link or junction.")
        object.__setattr__(self, "workspace_root", root.resolve(strict=True))
        if self.provider_id != DEFAULT_PROVIDER:
            raise ValueError("Only the local Ollama provider is enabled; paid providers are not configured.")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("The Ollama endpoint must use HTTP on localhost.")
        if not self.model_id or len(self.model_id) > 160:
            raise ValueError("A valid local model ID is required.")
        if not 1 <= self.max_actions <= MAX_ACTIONS:
            raise ValueError(f"Mission actions are limited to {MAX_ACTIONS}.")
        if not 1 <= self.action_timeout_seconds <= MAX_ACTION_SECONDS:
            raise ValueError(f"Each action is limited to {MAX_ACTION_SECONDS} seconds.")
        if not 1 <= self.mission_timeout_seconds <= MAX_MISSION_SECONDS:
            raise ValueError(f"A mission is limited to {MAX_MISSION_SECONDS} seconds.")

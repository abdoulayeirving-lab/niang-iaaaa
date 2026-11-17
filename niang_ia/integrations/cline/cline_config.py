from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


MAX_ACTIONS = 20
MAX_ACTION_SECONDS = 180
MAX_MISSION_SECONDS = 1800
DEFAULT_PROVIDER = "cline"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
CLINE_FREE_MODELS = (
    "cline-free/nemotron-3.5-super-vl",
    "cline-free/solar-mini4",
    "nvidia/nemotron-3.5-lightning-free",
)
DEFAULT_MODEL = CLINE_FREE_MODELS[0]
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
        if self.provider_id not in {"cline", "ollama"}:
            raise ValueError("Only Cline Free and local Ollama providers are enabled.")
        if self.provider_id == "ollama" and self.model_id == DEFAULT_MODEL:
            object.__setattr__(self, "model_id", DEFAULT_OLLAMA_MODEL)
        if not self.model_id or len(self.model_id) > 160:
            raise ValueError("A valid model ID is required.")
        if self.provider_id == "cline" and self.model_id not in CLINE_FREE_MODELS:
            raise ValueError("Cline missions may use only the configured free models.")
        if self.provider_id == "ollama":
            parsed = urlparse(self.base_url)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
                raise ValueError("The Ollama endpoint must use HTTP on localhost.")
        if not 1 <= self.max_actions <= MAX_ACTIONS:
            raise ValueError(f"Mission actions are limited to {MAX_ACTIONS}.")
        if not 1 <= self.action_timeout_seconds <= MAX_ACTION_SECONDS:
            raise ValueError(f"Each action is limited to {MAX_ACTION_SECONDS} seconds.")
        if not 1 <= self.mission_timeout_seconds <= MAX_MISSION_SECONDS:
            raise ValueError(f"A mission is limited to {MAX_MISSION_SECONDS} seconds.")

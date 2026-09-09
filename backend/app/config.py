"""Arena configuration loader.

Reads `config.yaml` (tracked in git, NEVER contains secrets) and overlays
`config.local.yaml` (git-ignored, may contain API keys via the Vault).
Environment variables always win for secrets.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = Path(os.environ.get("ARENA_CONFIG", REPO_ROOT / "config.yaml"))


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000


class AppConfig(BaseModel):
    app_name: str = "AK Dev Arena"
    version: str = "0.1.0"
    server: ServerConfig = Field(default_factory=ServerConfig)
    default_models: dict[str, str] = Field(
        default_factory=lambda: {
            "chat": "gpt-4o-mini",
            "code": "gpt-4o",
            "agent": "claude-opus-4-8",
            "build": "gpt-5.5",
        }
    )
    providers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    permissions: dict[str, str] = Field(
        default_factory=lambda: {
            "list_files": "allow", "read_file": "allow", "write_file": "allow",
            "edit_file": "allow", "delete_file": "ask",
            "search": "allow", "run": "allow", "run_build": "allow",
            "run_tests": "allow", "install_dependency": "ask",
            "start_server": "ask", "stop_server": "allow",
            "git_status": "allow", "git_diff": "allow",
            "git_checkpoint": "ask", "git_revert": "ask",
            "web_search": "allow", "web_fetch": "allow",
            "todo": "allow", "mcp": "ask",
        }
    )
    hooks: dict[str, str] = Field(default_factory=dict)
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)

    def safe_dict(self) -> dict[str, Any]:
        """Config safe for API responses — guaranteed secret-free."""
        return self.model_dump(exclude={"providers": {"__all__": {"api_key"}}})


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(path: Path | None = None) -> AppConfig:
    data = _load_yaml(Path(path) if path else DEFAULT_CONFIG_PATH)
    return AppConfig(**data)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config()


def reload_config() -> AppConfig:
    get_config.cache_clear()
    return get_config()

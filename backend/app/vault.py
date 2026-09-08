"""Arena Vault — API key storage.

Lookup order for a provider key:
  1. Environment variable (e.g. OPENAI_API_KEY)
  2. `config.local.yaml` in repo root (git-ignored, chmod 600)

The Vault NEVER returns keys to API callers — only booleans
(`is_configured`). Raw keys are only injected server-side into LiteLLM calls.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .config import REPO_ROOT

# Provider -> env var. None = no key needed (local provider).
PROVIDER_ENV_VARS: dict[str, str | None] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": None,  # 100% local, no key required
}


def _local_path() -> Path:
    override = os.environ.get("ARENA_LOCAL_CONFIG")
    return Path(override) if override else REPO_ROOT / "config.local.yaml"


def _read_local_file() -> dict[str, Any]:
    path = _local_path()
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def get_key(provider: str) -> str | None:
    """Return raw key for internal use only. Never expose via API."""
    provider = provider.lower()
    env_var = PROVIDER_ENV_VARS.get(provider)
    if env_var:
        value = os.environ.get(env_var)
        if value:
            return value.strip()
    keys = _read_local_file().get("keys", {})
    value = keys.get(provider)
    return value.strip() if isinstance(value, str) and value.strip() else None


def set_key(provider: str, key: str) -> None:
    """Persist a key to config.local.yaml (chmod 600) + current process env."""
    provider = provider.lower()
    if provider not in PROVIDER_ENV_VARS:
        raise ValueError(f"Unknown provider: {provider}")
    if not key or not key.strip():
        raise ValueError("Empty key")
    path = _local_path()
    data = _read_local_file()
    data.setdefault("keys", {})[provider] = key.strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # non-POSIX filesystem; file is still git-ignored
    env_var = PROVIDER_ENV_VARS[provider]
    if env_var:
        os.environ[env_var] = key.strip()


def delete_key(provider: str) -> bool:
    """Remove a key from local file + process env. Returns True if existed."""
    provider = provider.lower()
    existed = False
    env_var = PROVIDER_ENV_VARS.get(provider)
    if env_var and env_var in os.environ:
        del os.environ[env_var]
        existed = True
    data = _read_local_file()
    if provider in data.get("keys", {}):
        del data["keys"][provider]
        with open(_local_path(), "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False)
        existed = True
    return existed


def is_configured(provider: str) -> bool:
    provider = provider.lower()
    if provider == "ollama":
        return True  # local provider, always "ready" (daemon checked at call time)
    return get_key(provider) is not None


def provider_status() -> list[dict[str, Any]]:
    """Safe for API responses — booleans only, never key values."""
    return [
        {
            "provider": name,
            "env_var": env_var,
            "needs_key": env_var is not None,
            "configured": is_configured(name),
        }
        for name, env_var in PROVIDER_ENV_VARS.items()
    ]

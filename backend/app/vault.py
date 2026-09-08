"""Arena Vault — API key storage for 200+ providers.

Lookup order for a provider key:
  1. Environment variable (from models.dev registry, e.g. OFOX_API_KEY)
  2. `config.local.yaml` in repo root (git-ignored, chmod 600)

The Vault NEVER returns keys to API callers — only booleans
(`is_configured`). Raw keys are only injected server-side into LLM calls.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from . import catalog
from .config import REPO_ROOT

# Core providers (always known, even if the catalog snapshot is missing).
# None = no key needed (local provider).
STATIC_ENV_VARS: dict[str, str | None] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": None,  # 100% local, no key required
}

_VALID_ID = re.compile(r"^[a-z0-9][a-z0-9_.\-]*$")


def _local_path() -> Path:
    override = os.environ.get("ARENA_LOCAL_CONFIG")
    return Path(override) if override else REPO_ROOT / "config.local.yaml"


def _read_local_file() -> dict[str, Any]:
    path = _local_path()
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def env_var_for(provider: str) -> str | None:
    """Resolve the env var for ANY catalog provider (OpenCode-style)."""
    provider = (provider or "").lower()
    if provider in STATIC_ENV_VARS:
        return STATIC_ENV_VARS[provider]
    entry = catalog.get_provider(provider)
    if entry:
        env = entry.get("env") or []
        return env[0] if env else None
    return None


def needs_key(provider: str) -> bool:
    return env_var_for(provider) is not None


def _check_id(provider: str) -> str:
    provider = (provider or "").lower()
    if not _VALID_ID.match(provider):
        raise ValueError(f"Invalid provider id: {provider}")
    return provider


def get_key(provider: str) -> str | None:
    """Return raw key for internal use only. Never expose via API."""
    provider = provider.lower()
    env_var = env_var_for(provider)
    if env_var:
        value = os.environ.get(env_var)
        if value:
            return value.strip()
    keys = _read_local_file().get("keys", {})
    value = keys.get(provider)
    return value.strip() if isinstance(value, str) and value.strip() else None


def set_key(provider: str, key: str) -> None:
    """Persist a key to config.local.yaml (chmod 600) + current process env."""
    provider = _check_id(provider)
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
    env_var = env_var_for(provider)
    if env_var:
        os.environ[env_var] = key.strip()


def delete_key(provider: str) -> bool:
    """Remove a key from local file + process env. Returns True if existed."""
    provider = provider.lower()
    existed = False
    env_var = env_var_for(provider)
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
    if not needs_key(provider):
        return True  # local/keyless provider — always "ready"
    return get_key(provider) is not None


def provider_status() -> list[dict[str, Any]]:
    """Safe for API responses — booleans only, never key values.

    Configured providers first, then alphabetical. (OpenCode /connect style.)
    """
    seen: dict[str, dict[str, Any]] = {}
    for name in STATIC_ENV_VARS:
        seen[name] = {"provider": name, "name": name,
                      "env_var": STATIC_ENV_VARS[name],
                      "needs_key": STATIC_ENV_VARS[name] is not None,
                      "models": 0, "free_models": 0}
    for entry in catalog.providers():
        pid = entry["id"]
        env = entry.get("env") or []
        seen[pid] = {"provider": pid, "name": entry.get("name") or pid,
                     "env_var": env[0] if env else None,
                     "needs_key": bool(env),
                     "models": entry.get("model_count", 0),
                     "free_models": entry.get("free_count", 0)}
    if "ollama" in seen:  # static said unknown counts — catalog knows better
        pass
    out = list(seen.values())
    for item in out:
        item["configured"] = is_configured(item["provider"])
    return sorted(out, key=lambda p: (not p["configured"], p["provider"]))

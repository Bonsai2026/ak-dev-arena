"""Arena Catalog — 200+ providers & auto-detected models (OpenCode formula).

Same open registry OpenCode uses: https://models.dev (CC/same-org open data).
- Online: POST /api/catalog/refresh re-fetches the live registry.
- Offline: trimmed snapshot in backend/app/data/models_snapshot.json is used.
- Ollama (local): installed models are probed live from localhost:11434.

Free detection: cost.input == 0 and cost.output == 0  →  FREE.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .config import REPO_ROOT

REMOTE_URL = os.environ.get("ARENA_CATALOG_URL", "https://models.dev/api.json")
OLLAMA_BASE = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")

# Providers LiteLLM speaks natively as "<provider>/<model>".
LITELLM_PREFIXES = {
    "openai", "anthropic", "gemini", "vertex_ai", "vertex_ai_beta",
    "deepseek", "groq", "mistral", "cohere", "cohere_chat",
    "together_ai", "fireworks_ai", "openrouter", "ollama", "ollama_chat",
    "xai", "perplexity", "azure", "azure_ai", "bedrock", "bedrock_converse",
    "cerebras", "sambanova", "cloudflare", "deepinfra", "replicate",
    "anyscale", "ai21", "nlp_cloud", "aleph_alpha", "vllm", "databricks",
    "watsonx", "predibase", "nscale", "github", "dashscope", "volcengine",
    "voyage", "jina_ai", "recraft", "nvidia_nim", "nebius", "morph",
    "lambda_ai", "inception", "assistantapi", "sap", "snowflake",
}

OLLAMA_FALLBACK = ["llama3.1", "qwen3", "mistral", "deepseek-r1", "codellama", "gemma3"]


class CatalogError(Exception):
    """User-friendly catalog failure (safe to show in UI)."""


def snapshot_path() -> Path:
    override = os.environ.get("ARENA_CATALOG_SNAPSHOT")
    if override:
        return Path(override)
    return REPO_ROOT / "backend" / "app" / "data" / "models_snapshot.json"


_REG: dict[str, Any] | None = None


def reset_for_tests() -> None:
    global _REG
    _REG = None


def load() -> dict[str, Any]:
    """Load registry {providers: {...}} from snapshot (cached)."""
    global _REG
    if _REG is not None:
        return _REG
    path = snapshot_path()
    if not path.exists():
        _REG = {"_meta": {}, "providers": {}}
        return _REG
    try:
        _REG = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _REG = {"_meta": {}, "providers": {}}
    return _REG


def _fetch_remote() -> dict[str, Any]:
    import httpx

    resp = httpx.get(REMOTE_URL, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


def refresh() -> dict[str, Any]:
    """Re-fetch models.dev, re-trim, overwrite snapshot. Returns stats."""
    import datetime

    global _REG
    try:
        raw = _fetch_remote()
    except Exception as exc:  # noqa: BLE001 — network failure → friendly error
        raise CatalogError(f"Could not reach models.dev: {exc}") from exc
    out: dict[str, Any] = {
        "_meta": {"source": REMOTE_URL,
                  "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "note": "Trimmed snapshot for AK Dev Arena (offline fallback)."},
        "providers": {},
    }
    n_models = 0
    for pid, p in (raw or {}).items():
        if not isinstance(p, dict):
            continue
        models: dict[str, Any] = {}
        for mid, m in (p.get("models") or {}).items():
            if not isinstance(m, dict):
                continue
            cost = m.get("cost") or {}
            try:
                ci = float(cost.get("input", 0) or 0)
                co = float(cost.get("output", 0) or 0)
            except (TypeError, ValueError):
                ci, co = 0.0, 0.0
            lim = m.get("limit") or {}
            try:
                ctx = int(lim.get("context") or 0)
            except (TypeError, ValueError):
                ctx = 0
            models[mid] = {"id": mid, "name": m.get("name") or mid,
                           "cost": {"input": ci, "output": co},
                           "free": (ci == 0 and co == 0),
                           "tool_call": bool(m.get("tool_call")),
                           "reasoning": bool(m.get("reasoning")),
                           "context": ctx}
            n_models += 1
        out["providers"][pid] = {"id": pid, "name": p.get("name") or pid,
                                 "env": list(p.get("env") or []),
                                 "api": p.get("api"), "models": models}
    try:
        path = snapshot_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    except OSError as exc:
        raise CatalogError(f"Could not save snapshot: {exc}") from exc
    _REG = out
    return {"providers": len(out["providers"]), "models": n_models,
            "fetched_at": out["_meta"]["fetched_at"]}


def get_provider(provider_id: str) -> dict[str, Any] | None:
    return load().get("providers", {}).get((provider_id or "").lower())


def ollama_models() -> list[dict[str, Any]]:
    """Live-probe installed Ollama models; fallback list if daemon is down."""
    if os.environ.get("ARENA_NO_OLLAMA_PROBE") == "1":
        installed = []
    else:
        installed = []
        try:
            import httpx

            resp = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=2)
            if resp.status_code == 200:
                for m in resp.json().get("models", []):
                    name = str(m.get("name", "")).split(":")[0]
                    if name:
                        installed.append(m.get("name", name))
        except Exception:  # noqa: BLE001, S110 — offline daemon → fallback list
            pass
    names = installed or OLLAMA_FALLBACK
    return [{"id": f"ollama/{n}", "provider": "ollama", "provider_name": "Ollama (local)",
             "label": n, "name": n, "cost": {"input": 0, "output": 0}, "free": True,
             "tool_call": True, "reasoning": False, "context": 0,
             "needs_key": False, "installed": bool(installed)} for n in names]


def providers() -> list[dict[str, Any]]:
    """All providers, normalized. Ollama (local) is always included."""
    out = []
    for pid, p in load().get("providers", {}).items():
        models = p.get("models", {})
        out.append({"id": pid, "name": p.get("name") or pid,
                    "env": p.get("env") or [], "api": p.get("api"),
                    "model_count": len(models),
                    "free_count": sum(1 for m in models.values() if m.get("free"))})
    out.append({"id": "ollama", "name": "Ollama (local)", "env": [],
                "api": OLLAMA_BASE, "model_count": len(ollama_models()),
                "free_count": len(ollama_models())})
    return sorted(out, key=lambda p: p["id"])


def models(provider: str = "", search: str = "", free_only: bool = False,
           limit: int = 500) -> list[dict[str, Any]]:
    """Flattened model list with filters. id format: provider/model."""
    provider = (provider or "").lower()
    query = (search or "").lower()
    out: list[dict[str, Any]] = []
    for pid, p in load().get("providers", {}).items():
        if provider and pid != provider:
            continue
        env = p.get("env") or []
        for mid, m in p.get("models", {}).items():
            if free_only and not m.get("free"):
                continue
            if query and query not in mid.lower() and query not in str(m.get("name", "")).lower():
                continue
            out.append({"id": f"{pid}/{mid}", "provider": pid,
                        "provider_name": p.get("name") or pid,
                        "label": m.get("name") or mid, "name": m.get("name") or mid,
                        "cost": m.get("cost", {"input": 0, "output": 0}),
                        "free": bool(m.get("free")),
                        "tool_call": bool(m.get("tool_call")),
                        "reasoning": bool(m.get("reasoning")),
                        "context": int(m.get("context") or 0),
                        "needs_key": bool(env)})
            if len(out) >= limit:
                return out
    if not provider or provider == "ollama":
        for entry in ollama_models():
            if query and query not in entry["label"].lower():
                continue
            out.append(entry)
            if len(out) >= limit:
                break
    return out


def resolve_call(model_id: str, provider: str) -> dict[str, Any]:
    """Map an Arena model id → LiteLLM call params.

    Returns {litellm_model, api_base|None}. Strategy (OpenCode-style):
    - bare id (no slash) → pass through, LiteLLM infers the provider.
    - known LiteLLM prefix → direct "provider/rest".
    - provider with api base → OpenAI-compatible via that base URL.
    - otherwise → direct attempt; LiteLLM's own registry may still know it.
    """
    provider = (provider or "").lower()
    mid = (model_id or "").strip()
    if "/" not in mid:
        return {"litellm_model": mid, "api_base": None}
    first, rest = mid.split("/", 1)
    first = first.lower()
    if first == "ollama":
        return {"litellm_model": mid, "api_base": OLLAMA_BASE}
    if first in LITELLM_PREFIXES:
        return {"litellm_model": mid, "api_base": None}
    entry = get_provider(first)
    if entry and entry.get("api"):
        return {"litellm_model": f"openai/{rest}", "api_base": entry["api"]}
    return {"litellm_model": mid, "api_base": None}

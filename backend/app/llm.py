"""Arena LLM router — one interface for every provider (via LiteLLM).

Any LiteLLM model id works out of the box. The MODEL_CATALOG below is just a
curated picker for the UI; power users can type any id (e.g. a new model that
launched yesterday) and it will work as long as the provider key is set.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import litellm

from . import vault

# litellm can be chatty; keep server logs clean
litellm.suppress_debug_info = True

MODEL_CATALOG: list[dict[str, Any]] = [
    {"id": "gpt-5.5", "label": "GPT-5.5", "provider": "openai",
     "best_for": "All-round coding + agents", "needs_key": True},
    {"id": "gpt-4o", "label": "GPT-4o", "provider": "openai",
     "best_for": "Fast + capable chat", "needs_key": True},
    {"id": "gpt-4o-mini", "label": "GPT-4o mini", "provider": "openai",
     "best_for": "Cheapest OpenAI chat", "needs_key": True},
    {"id": "claude-opus-4-8", "label": "Claude Opus 4.8", "provider": "anthropic",
     "best_for": "Deepest reasoning + long tasks", "needs_key": True},
    {"id": "gemini/gemini-3-pro", "label": "Gemini 3 Pro", "provider": "gemini",
     "best_for": "Huge context window", "needs_key": True},
    {"id": "deepseek/deepseek-chat", "label": "DeepSeek", "provider": "deepseek",
     "best_for": "Cheap + strong coding", "needs_key": True},
    {"id": "groq/llama-3.3-70b-versatile", "label": "Groq Llama 70B", "provider": "groq",
     "best_for": "Ultra-fast responses", "needs_key": True},
    {"id": "ollama/llama3.1", "label": "Ollama Llama 3.1 (local)", "provider": "ollama",
     "best_for": "100% free + offline", "needs_key": False},
]

_CATALOG_INDEX = {m["id"]: m for m in MODEL_CATALOG}


class ArenaLLMError(Exception):
    """User-friendly LLM failure (safe to show in UI)."""


def provider_for_model(model_id: str) -> str:
    """Resolve provider from catalog, else from `provider/model` prefix."""
    if model_id in _CATALOG_INDEX:
        return _CATALOG_INDEX[model_id]["provider"]
    if "/" in model_id:
        prefix = model_id.split("/", 1)[0].lower()
        if prefix in vault.PROVIDER_ENV_VARS:
            return prefix
    lowered = model_id.lower()
    if lowered.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    if lowered.startswith("claude"):
        return "anthropic"
    if lowered.startswith("gemini"):
        return "gemini"
    if lowered.startswith("deepseek"):
        return "deepseek"
    return "openai"  # LiteLLM default


def _ensure_key(provider: str) -> None:
    if provider == "ollama":
        return
    if not vault.is_configured(provider):
        env_var = vault.PROVIDER_ENV_VARS.get(provider, "API_KEY")
        raise ArenaLLMError(
            f"No API key for '{provider}'. Add it via the Keys panel in the app "
            f"or set the {env_var} environment variable."
        )


def _friendly_error(exc: Exception, provider: str) -> ArenaLLMError:
    name = type(exc).__name__
    msg = str(exc)
    if "Authentication" in name or "auth" in msg.lower():
        return ArenaLLMError(f"Provider '{provider}' rejected the API key. Check the key and try again.")
    if "NotFound" in name or "404" in msg:
        return ArenaLLMError(f"Model not found on '{provider}'. Pick another model from the list.")
    if "RateLimit" in name or "429" in msg:
        return ArenaLLMError(f"Rate limit hit on '{provider}'. Wait a moment and retry.")
    if "Connection" in name or "connect" in msg.lower():
        if provider == "ollama":
            return ArenaLLMError("Cannot reach Ollama. Is `ollama serve` running on http://localhost:11434?")
        return ArenaLLMError(f"Cannot reach '{provider}'. Check your internet connection.")
    short = msg.strip().split("\n")[0][:300]
    return ArenaLLMError(f"LLM call failed ({name}): {short}")


async def chat_completion(
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> dict[str, Any]:
    """Single (non-streaming) chat completion."""
    provider = provider_for_model(model)
    _ensure_key(provider)
    try:
        resp = await litellm.acompletion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except ArenaLLMError:
        raise
    except Exception as exc:  # noqa: BLE001 — converted to friendly error
        raise _friendly_error(exc, provider) from exc
    choice = resp.choices[0]
    content = choice.message.content or ""
    usage = {}
    try:
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        }
    except Exception:  # noqa: BLE001, S110 — usage is best-effort
        pass
    return {"content": content, "model": resp.model or model, "provider": provider, "usage": usage}


async def chat_stream(
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> AsyncIterator[str]:
    """Streaming chat completion — yields text deltas."""
    provider = provider_for_model(model)
    _ensure_key(provider)
    try:
        resp = await litellm.acompletion(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        async for chunk in resp:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
    except ArenaLLMError:
        raise
    except Exception as exc:  # noqa: BLE001 — converted to friendly error
        raise _friendly_error(exc, provider) from exc

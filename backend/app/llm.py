"""Arena LLM router — one interface for 200+ providers (via LiteLLM).

Model ids look like OpenCode's: "provider/model" (e.g. "ofox/bailian/qwen3.7-max",
"openai/gpt-5-nano", "ollama/llama3.1"). Bare legacy ids ("gpt-4o-mini") still work.
Any provider in the catalog works the moment its API key is added — models are
auto-detected from the models.dev registry, free ones flagged automatically.
"""

from __future__ import annotations

from typing import Any, AsyncIterator

import litellm

from . import catalog, usage as usage_mod, vault

# litellm can be chatty; keep server logs clean
litellm.suppress_debug_info = True

# Minimal fallback if the catalog snapshot is missing entirely.
FALLBACK_CATALOG: list[dict[str, Any]] = [
    {"id": "openai/gpt-4o-mini", "label": "GPT-4o mini", "provider": "openai",
     "best_for": "Cheapest OpenAI chat", "needs_key": True},
    {"id": "ollama/llama3.1", "label": "Ollama Llama 3.1 (local)", "provider": "ollama",
     "best_for": "100% free + offline", "needs_key": False},
]


class ArenaLLMError(Exception):
    """User-friendly LLM failure (safe to show in UI)."""


def provider_for_model(model_id: str) -> str:
    """Resolve provider: "provider/..." → provider; bare id → legacy inference."""
    mid = (model_id or "").strip()
    if "/" in mid:
        return mid.split("/", 1)[0].lower()
    lowered = mid.lower()
    if lowered.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    if lowered.startswith("claude"):
        return "anthropic"
    if lowered.startswith("gemini"):
        return "gemini"
    if lowered.startswith("deepseek"):
        return "deepseek"
    if lowered.startswith(("llama", "qwen", "mistral", "mixtral", "codellama", "gemma")):
        return "ollama"
    return "openai"  # LiteLLM default


def _ensure_key(provider: str) -> None:
    if not vault.needs_key(provider):
        return
    if not vault.is_configured(provider):
        env_var = vault.env_var_for(provider) or "API_KEY"
        raise ArenaLLMError(
            f"No API key for '{provider}'. Add it via the Keys panel in the app "
            f"or set the {env_var} environment variable."
        )


def _call_kwargs(model: str, provider: str, messages: list[dict[str, str]],
                 max_tokens: int, temperature: float) -> dict[str, Any]:
    resolved = catalog.resolve_call(model, provider)
    kwargs: dict[str, Any] = {"model": resolved["litellm_model"], "messages": messages,
                              "max_tokens": max_tokens, "temperature": temperature}
    if vault.needs_key(provider):
        kwargs["api_key"] = vault.get_key(provider)
    if resolved["api_base"]:
        kwargs["api_base"] = resolved["api_base"]
    if provider == "ollama" and "api_base" not in kwargs:
        kwargs["api_base"] = catalog.OLLAMA_BASE
    return kwargs


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
            **_call_kwargs(model, provider, messages, max_tokens, temperature))
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
    # Every LLM call is tracked centrally (tokens only, never content).
    usage_mod.record(
        model=str(resp.model or model), provider=provider,
        prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
        completion_tokens=int(usage.get("completion_tokens", 0) or 0), stream=False,
    )
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
            **_call_kwargs(model, provider, messages, max_tokens, temperature), stream=True)
        async for chunk in resp:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
    except ArenaLLMError:
        raise
    except Exception as exc:  # noqa: BLE001 — converted to friendly error
        raise _friendly_error(exc, provider) from exc

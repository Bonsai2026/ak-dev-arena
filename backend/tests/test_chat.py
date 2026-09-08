"""Chat endpoint tests with a mocked LLM (no network, no API keys)."""

import pytest
from fastapi.testclient import TestClient

from backend.app import llm
from backend.app.main import app

client = TestClient(app)


async def _fake_completion(model, messages, max_tokens=2048, temperature=0.7):
    last = messages[-1]["content"] if messages else ""
    return {
        "content": f"[mock:{model}] echo: {last}",
        "model": model,
        "provider": "mock",
        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
    }


async def _fake_stream(model, messages, max_tokens=2048, temperature=0.7):
    yield "Hello"
    yield " Arena"


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", _fake_completion)
    monkeypatch.setattr(llm, "chat_stream", _fake_stream)


def test_chat_returns_mocked_reply():
    res = client.post(
        "/api/chat",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert res.status_code == 200
    body = res.json()
    assert "echo: hi" in body["content"]


def test_chat_rejects_bad_body():
    res = client.post("/api/chat", json={"model": "x", "messages": []})
    assert res.status_code == 422


def test_chat_stream_emits_tokens_and_done():
    res = client.post(
        "/api/chat/stream",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert res.status_code == 200
    assert "Hello" in res.text
    assert "Arena" in res.text
    assert "[DONE]" in res.text


def test_chat_surfaces_friendly_llm_error(monkeypatch):
    async def _boom(*a, **k):
        raise llm.ArenaLLMError("No API key for 'openai'.")

    monkeypatch.setattr(llm, "chat_completion", _boom)
    res = client.post(
        "/api/chat",
        json={"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]},
    )
    assert res.status_code == 400
    assert "No API key" in res.json()["detail"]


def test_provider_resolution():
    assert llm.provider_for_model("gpt-4o-mini") == "openai"
    assert llm.provider_for_model("claude-opus-4-8") == "anthropic"
    assert llm.provider_for_model("gemini/gemini-3-pro") == "gemini"
    assert llm.provider_for_model("ollama/llama3.1") == "ollama"
    assert llm.provider_for_model("openrouter/some/new-model") == "openrouter"

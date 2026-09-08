"""Usage tracker tests: chat calls are counted (mocked LLM)."""

import pytest
from fastapi.testclient import TestClient

from backend.app import llm, usage
from backend.app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean():
    usage.reset()
    yield
    usage.reset()


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    async def _fake(model, messages, max_tokens=2048, temperature=0.7):
        return {"content": "ok", "model": model, "provider": "mock",
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}}

    async def _stream(model, messages, max_tokens=2048, temperature=0.7):
        yield "ok"

    monkeypatch.setattr(llm, "chat_completion", _fake)
    monkeypatch.setattr(llm, "chat_stream", _stream)


def test_chat_call_recorded():
    client.post("/api/chat", json={
        "model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]})
    res = client.get("/api/usage")
    assert res.status_code == 200
    body = res.json()
    assert body["totals"]["calls"] == 1
    assert body["totals"]["total"] == 30
    assert body["by_model"][0]["model"] == "gpt-4o-mini"


def test_stream_call_recorded():
    client.post("/api/chat/stream", json={
        "model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]})
    res = client.get("/api/usage")
    assert res.json()["totals"]["calls"] == 1


def test_usage_reset():
    client.post("/api/chat", json={
        "model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]})
    assert client.delete("/api/usage").status_code == 200
    assert client.get("/api/usage").json()["totals"]["calls"] == 0

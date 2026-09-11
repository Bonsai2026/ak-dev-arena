"""Phase D tests: custom providers, usage estimates, context compaction."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.app import agent, catalog, usage
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def local_cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_LOCAL_CONFIG", str(tmp_path / "config.local.yaml"))
    catalog.clear_custom_cache()
    yield tmp_path
    catalog.clear_custom_cache()


# ------------------------------------------------------- custom providers ---


def test_normalize_base_url():
    assert catalog.normalize_base_url("https://api.xyz.com") == "https://api.xyz.com"
    assert catalog.normalize_base_url("https://api.xyz.com/") == "https://api.xyz.com"
    assert catalog.normalize_base_url("https://api.xyz.com/v1") == "https://api.xyz.com/v1"
    assert catalog.normalize_base_url("api.xyz.com") == "https://api.xyz.com"


def test_custom_provider_crud(local_cfg):
    res = client.post("/api/providers/custom", json={
        "id": "myai", "name": "My AI", "base_url": "https://api.myai.dev/v1",
        "model": "my-model"})
    assert res.status_code == 200
    p = res.json()["provider"]
    assert p["base_url"] == "https://api.myai.dev/v1"

    listed = client.get("/api/providers/custom").json()["providers"]
    assert any(x["id"] == "myai" for x in listed)

    assert catalog.resolve_call("myai/model-x", "myai") == {
        "litellm_model": "openai/model-x",
        "api_base": "https://api.myai.dev/v1"}
    assert catalog.is_custom_provider("myai") is True

    res = client.delete("/api/providers/custom/myai")
    assert res.json() == {"deleted": True, "id": "myai"}
    assert catalog.custom_providers() == {}


def test_custom_provider_rejects_bad_url(local_cfg):
    res = client.post("/api/providers/custom", json={
        "id": "bad", "base_url": "ftp://nope"})
    assert res.status_code == 400


def test_custom_provider_key_env(local_cfg):
    from backend.app import vault
    client.post("/api/providers/custom", json={
        "id": "myai", "base_url": "https://api.myai.dev/v1"})
    assert vault.env_var_for("myai") == "ARENA_CUSTOM_MYAI_KEY"
    # existing provider still resolves from registry first
    assert vault.env_var_for("anthropic") == "ANTHROPIC_API_KEY"


# --------------------------------------------------------------- usage -----


def test_usage_estimate_zero_for_unknown():
    usage.reset()
    usage.record("unknown/model-1", "unknown", prompt_tokens=1000,
                 completion_tokens=2000)
    s = usage.summary()
    assert s["totals"]["calls"] == 1
    assert s["totals"]["total"] == 3000
    assert s["totals"]["cost"] == 0.0  # unknown pricing → 0, never fake


def test_usage_estimate_known_model():
    usage.reset()
    cost = catalog.cost_for("openai/gpt-4o-mini")
    if cost == (0.0, 0.0):
        pytest.skip("registry pricing unavailable offline")
    usage.record("openai/gpt-4o-mini", "openai", prompt_tokens=1_000_000,
                 completion_tokens=1_000_000)
    s = usage.summary()
    assert s["totals"]["cost"] == pytest.approx(cost[0] + cost[1], rel=1e-6)


# ------------------------------------------------------ compaction --------


def test_compact_messages():
    messages = [{"role": "system", "content": "sys"},
                {"role": "user", "content": "task"}]
    for i in range(30):
        messages.append({"role": "assistant", "content": '{"thought":"t","tool":"run","args":{"cmd":"pwd"}}'})
        messages.append({"role": "user", "content": f"OBSERVATION: ok {i}"})
    out = agent._compact_messages(messages)
    assert len(out) < len(messages)
    assert out[0] == messages[0]
    assert out[1] == messages[1]
    assert any("compacted" in m["content"] for m in out)


def test_compact_keeps_short():
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    assert agent._compact_messages(messages) == messages


async def _smoke():
    # run_agent must import & loop one step without crashing (mock LLM)
    from backend.app import llm

    async def fake(model, messages, **kw):
        return {"content": '{"thought":"t","tool":"done","args":{"summary":"ok"}}',
                "model": model, "provider": "mock", "usage": {}}

    llm.chat_completion = fake
    result = await agent.run_agent("say ok", "mock/model", max_steps=2)
    return result


def test_agent_smoke_done():
    res = asyncio.run(_smoke())
    assert res["status"] == "complete"
    assert res["summary"] == "ok"
    assert res["verification"]["has_evidence"] is False  # honest: nothing ran

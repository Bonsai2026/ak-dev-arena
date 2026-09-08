"""Catalog tests: 200+ providers, auto-detect, free flags (mocked registry)."""

import json

import pytest
from fastapi.testclient import TestClient

from backend.app import catalog, vault
from backend.app.main import app

client = TestClient(app)

FAKE_REGISTRY = {
    "_meta": {"source": "test"},
    "providers": {
        "testpro": {
            "id": "testpro", "name": "TestPro", "env": ["TESTPRO_API_KEY"],
            "api": "https://api.testpro.ai/v1",
            "models": {
                "flash": {"id": "flash", "name": "Flash", "cost": {"input": 0, "output": 0},
                          "free": True, "tool_call": True, "reasoning": False, "context": 128000},
                "pro": {"id": "pro", "name": "Pro", "cost": {"input": 5, "output": 15},
                        "free": False, "tool_call": True, "reasoning": True, "context": 200000},
            },
        },
        "nokey": {
            "id": "nokey", "name": "NoKey Local", "env": [], "api": None,
            "models": {
                "tiny": {"id": "tiny", "name": "Tiny", "cost": {"input": 0, "output": 0},
                         "free": True, "tool_call": False, "reasoning": False, "context": 8000},
            },
        },
    },
}


@pytest.fixture(autouse=True)
def _fake_catalog(monkeypatch, tmp_path):
    snap = tmp_path / "snap.json"
    snap.write_text(json.dumps(FAKE_REGISTRY))
    monkeypatch.setenv("ARENA_CATALOG_SNAPSHOT", str(snap))
    monkeypatch.setenv("ARENA_NO_OLLAMA_PROBE", "1")
    monkeypatch.setenv("ARENA_LOCAL_CONFIG", str(tmp_path / "local.yaml"))
    catalog.reset_for_tests()
    yield
    catalog.reset_for_tests()


def test_providers_include_registry_with_counts():
    res = client.get("/api/providers")
    assert res.status_code == 200
    by_id = {p["provider"]: p for p in res.json()["providers"]}
    assert by_id["testpro"]["models"] == 2
    assert by_id["testpro"]["free_models"] == 1
    assert by_id["testpro"]["env_var"] == "TESTPRO_API_KEY"
    assert by_id["testpro"]["configured"] is False
    assert by_id["nokey"]["needs_key"] is False
    assert by_id["nokey"]["configured"] is True


def test_adding_key_configures_provider_models():
    res = client.post("/api/keys", json={"provider": "testpro", "key": "tp-123"})
    assert res.status_code == 200
    res = client.get("/api/models", params={"provider": "testpro"})
    models = res.json()["models"]
    assert len(models) == 2
    assert all(m["configured"] for m in models)
    assert res.json()["total"] == 2


def test_free_only_filter():
    res = client.get("/api/models", params={"free_only": True})
    models = res.json()["models"]
    assert models
    assert all(m["free"] for m in models)
    assert any(m["id"] == "testpro/flash" for m in models)


def test_search_filter():
    res = client.get("/api/models", params={"search": "tiny"})
    ids = [m["id"] for m in res.json()["models"]]
    assert ids == ["nokey/tiny"]


def test_resolve_call_strategies():
    assert catalog.resolve_call("openai/gpt-4o", "openai") == {
        "litellm_model": "openai/gpt-4o", "api_base": None}
    assert catalog.resolve_call("testpro/flash", "testpro") == {
        "litellm_model": "openai/flash", "api_base": "https://api.testpro.ai/v1"}
    assert catalog.resolve_call("gpt-4o-mini", "openai") == {
        "litellm_model": "gpt-4o-mini", "api_base": None}
    assert catalog.resolve_call("ollama/llama3.1", "ollama")["api_base"] == catalog.OLLAMA_BASE


def test_vault_accepts_any_catalog_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_LOCAL_CONFIG", str(tmp_path / "k.yaml"))
    vault.set_key("testpro", "abc")
    assert vault.get_key("testpro") == "abc"
    assert vault.is_configured("testpro") is True
    assert vault.delete_key("testpro") is True
    assert vault.is_configured("testpro") is False


def test_catalog_refresh(monkeypatch, tmp_path):
    async_payload = {"qx": {"id": "qx", "name": "QX", "env": ["QX_KEY"], "api": None,
                             "models": {"m1": {"id": "m1", "name": "M1",
                                               "cost": {"input": 0, "output": 0},
                                               "tool_call": True, "reasoning": False,
                                               "limit": {"context": 1000}}}}}
    monkeypatch.setattr(catalog, "_fetch_remote", lambda: async_payload)
    monkeypatch.setenv("ARENA_CATALOG_SNAPSHOT", str(tmp_path / "new.json"))
    catalog.reset_for_tests()
    res = client.post("/api/catalog/refresh")
    assert res.status_code == 200
    assert res.json()["providers"] >= 1
    assert catalog.get_provider("qx")["name"] == "QX"

"""Health / config / catalog endpoint tests (no network, no API keys)."""

from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_public_config_has_no_secrets():
    res = client.get("/api/config")
    assert res.status_code == 200
    body = res.json()
    assert body["app_name"] == "AK Dev Arena"
    blob = str(body).lower()
    assert "api_key" not in blob
    assert "sk-" not in blob


def test_models_catalog():
    res = client.get("/api/models")
    assert res.status_code == 200
    body = res.json()
    assert len(body["models"]) >= 5
    assert "defaults" in body and "chat" in body["defaults"]
    for entry in body["models"]:
        assert {"id", "label", "provider", "configured"} <= set(entry)


def test_providers_status_has_no_key_values():
    res = client.get("/api/providers")
    assert res.status_code == 200
    body = res.json()
    assert len(body["providers"]) >= 5
    for entry in body["providers"]:
        assert "configured" in entry
        assert "key" not in str(entry).lower() or "needs_key" in entry or "env_var" in entry

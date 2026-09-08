"""Build Mode tests: templates, scaffolding, AI fix loop (mocked LLM)."""

import json

import pytest
from fastapi.testclient import TestClient

from backend.app import files, llm
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    return tmp_path


def test_templates_listed(ws):
    res = client.get("/api/build/templates")
    assert res.status_code == 200
    ids = {t["id"] for t in res.json()["templates"]}
    assert {"static-html", "vite-react", "fastapi-py"} <= ids


def test_generate_static_site(ws):
    res = client.post("/api/build/generate", json={
        "name": "my-site", "template": "static-html", "description": "My cool site"})
    assert res.status_code == 200
    body = res.json()
    assert body["path"] == "builds/my-site"
    index = ws / "builds" / "my-site" / "index.html"
    assert index.exists()
    assert "My cool site" in index.read_text()

    res = client.get("/api/build/list")
    assert any(b["name"] == "my-site" for b in res.json()["builds"])


def test_generate_rejects_bad_name(ws):
    res = client.post("/api/build/generate", json={"name": "../evil", "template": "static-html"})
    assert res.status_code == 400


def test_generate_rejects_duplicate(ws):
    client.post("/api/build/generate", json={"name": "dup", "template": "static-html"})
    res = client.post("/api/build/generate", json={"name": "dup", "template": "static-html"})
    assert res.status_code == 400


def test_fix_loop_applies_patch(ws, monkeypatch):
    client.post("/api/build/generate", json={"name": "fixme", "template": "static-html"})

    async def _fake(model, messages, max_tokens=1500, temperature=0.2):
        return {"content": json.dumps({
            "path": "app.js",
            "old_text": "console.log('fixme ready');",
            "new_text": "console.log('fixme fixed!');"}),
            "model": model, "provider": "mock", "usage": {}}

    monkeypatch.setattr(llm, "chat_completion", _fake)
    res = client.post("/api/build/fix", json={"name": "fixme", "error": "wrong log message"})
    assert res.status_code == 200
    assert res.json()["applied"] is True
    assert "fixed!" in (ws / "builds" / "fixme" / "app.js").read_text()

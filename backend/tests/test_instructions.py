"""Tests for chat instructions (Cursor/Claude/Codex-style): global + .akrules.

Global instructions persist in git-ignored config.local.yaml (ARENA_LOCAL_CONFIG
in tests). Project rules persist as .akrules in the workspace root. Both are
injected into every LLM context: chat, composer, build-fix and review.
"""

import json

import pytest
from fastapi.testclient import TestClient

from backend.app import contextx, files, llm, manager, workflows
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    monkeypatch.setenv("ARENA_LOCAL_CONFIG", str(tmp_path / "local.yaml"))
    return tmp_path


@pytest.fixture(autouse=True)
def _clean_state():
    manager.reset_for_tests()
    workflows.reset_for_tests()
    yield
    manager.reset_for_tests()
    workflows.reset_for_tests()


def _script(content, capture=None):
    async def _fake(model, messages, *a, **k):
        if capture is not None:
            capture.append(messages)
        return {"content": content, "model": model, "provider": "mock", "usage": {}}

    return _fake


# ------------------------------------------------ instructions endpoints ---


def test_get_instructions_empty(ws):
    res = client.get("/api/context/instructions")
    assert res.status_code == 200
    body = res.json()
    assert body == {"global": "", "project": "", "global_found": False, "project_found": False}


def test_save_global_instructions_persists(ws):
    res = client.put("/api/context/instructions", json={"content": "Always use tabs."})
    assert res.status_code == 200
    assert res.json()["global_found"] is True
    assert "Always use tabs." in res.json()["global"]
    # survives a fresh read (persisted on disk, not in memory)
    assert "Always use tabs." in contextx.load_global_instructions()
    assert (ws / "local.yaml").exists()


def test_save_global_instructions_preserves_keys(ws):
    (ws / "local.yaml").write_text("keys:\n  openai: sk-test-123\n")
    contextx.save_global_instructions("be concise")
    import yaml
    raw = yaml.safe_load((ws / "local.yaml").read_text())
    assert raw["keys"]["openai"] == "sk-test-123"
    assert raw["arena_instructions"] == "be concise"


def test_clear_global_instructions(ws):
    contextx.save_global_instructions("hello")
    res = client.put("/api/context/instructions", json={"content": ""})
    assert res.json()["global_found"] is False


def test_post_rules_writes_akrules(ws):
    res = client.post("/api/context/rules", json={"content": "Python 3.11 only"})
    assert res.status_code == 200
    assert res.json()["project_found"] is True
    assert "Python 3.11 only" in (ws / ".akrules").read_text()


def test_delete_rules(ws):
    (ws / ".akrules").write_text("old rules")
    res = client.delete("/api/context/rules")
    assert res.status_code == 200
    assert res.json()["project_found"] is False
    assert not (ws / ".akrules").exists()


# --------------------------------------------- injection across engines ---


def test_global_instructions_injected_in_chat(ws, monkeypatch):
    contextx.save_global_instructions("GLOBAL-MARK-1")
    (ws / ".akrules").write_text("PROJECT-MARK-1")
    captured = []
    monkeypatch.setattr(llm, "chat_completion", _script("hi", captured))
    client.post("/api/chat", json={
        "model": "x", "messages": [{"role": "user", "content": "hello"}]})
    system = captured[0][0]
    assert system["role"] == "system"
    assert "GLOBAL-MARK-1" in system["content"]
    assert "PROJECT-MARK-1" in system["content"]


def test_rules_injected_in_composer(ws, monkeypatch):
    (ws / "a.py").write_text("x = 1\n")
    (ws / ".akrules").write_text("COMPOSER-RULES-1")
    captured = []
    content = json.dumps({"patches": [{"path": "a.py", "old_text": "x = 1", "new_text": "x = 2"}]})
    monkeypatch.setattr(llm, "chat_completion", _script(content, captured))
    res = client.post("/api/code/composer", json={"instructions": "bump x"})
    assert res.status_code == 200
    assert "COMPOSER-RULES-1" in json.dumps(captured[0])


def test_rules_injected_in_review(ws, monkeypatch):
    (ws / ".akrules").write_text("REVIEW-RULES-1")
    captured = []
    content = json.dumps({"summary": "ok", "findings": []})
    monkeypatch.setattr(llm, "chat_completion", _script(content, captured))
    res = client.post("/api/review", json={"diff": "--- a/x\n+++ b/x\n+1", "model": "x"})
    assert res.status_code == 200
    assert "REVIEW-RULES-1" in json.dumps(captured[0])


def test_rules_injected_in_build_fix(ws, monkeypatch):
    from backend.app import builder

    builder.generate("demo", "static-html", "demo", root=ws)
    (ws / ".akrules").write_text("BUILD-RULES-1")
    captured = []
    content = json.dumps({"path": "index.html", "old_text": "<h1>demo</h1>",
                          "new_text": "<h1>fixed</h1>"})
    monkeypatch.setattr(llm, "chat_completion", _script(content, captured))
    res = client.post("/api/build/fix", json={"name": "demo", "error": "boom", "model": "x"})
    assert res.status_code == 200
    assert "BUILD-RULES-1" in json.dumps(captured[0])

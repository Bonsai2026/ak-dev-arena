"""Agent Mode tests with scripted (mocked) LLM responses."""

import json

import pytest
from fastapi.testclient import TestClient

from backend.app import agent, files, llm
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    return tmp_path


def _script(responses):
    it = iter(responses)

    async def _fake(model, messages, max_tokens=1500, temperature=0.3):
        try:
            content = next(it)
        except StopIteration:
            content = json.dumps({"thought": "done", "tool": "done", "args": {"summary": "ok"}})
        return {"content": content, "model": model, "provider": "mock", "usage": {}}

    return _fake


def test_agent_lists_and_finishes(ws, monkeypatch):
    (ws / "a.txt").write_text("hello")
    monkeypatch.setattr(llm, "chat_completion", _script([
        json.dumps({"thought": "list files", "tool": "list_files", "args": {}}),
        json.dumps({"thought": "saw a.txt", "tool": "done", "args": {"summary": "found a.txt"}}),
    ]))
    res = client.post("/api/agent/run", json={"task": "what files exist?", "max_steps": 5})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "complete"
    assert "a.txt" in body["summary"]
    assert len(body["steps"]) == 2


def test_agent_writes_file(ws, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", _script([
        json.dumps({"thought": "write", "tool": "write_file",
                    "args": {"path": "out.txt", "content": "arena wins"}}),
        json.dumps({"thought": "done", "tool": "done", "args": {"summary": "wrote out.txt"}}),
    ]))
    res = client.post("/api/agent/run", json={"task": "create out.txt", "max_steps": 5})
    assert res.status_code == 200
    assert (ws / "out.txt").read_text() == "arena wins"


def test_agent_blocks_disallowed_command():
    with pytest.raises(agent.AgentError):
        agent.run_command("rm -rf /", cwd=files.WORKSPACE)


def test_agent_allows_safe_command(ws):
    out = agent.run_command("echo hello", cwd=ws)
    assert "hello" in out


def test_agent_bad_json_recovers(ws, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", _script([
        "this is not json at all",
        json.dumps({"thought": "ok", "tool": "done", "args": {"summary": "recovered"}}),
    ]))
    res = client.post("/api/agent/run", json={"task": "hi", "max_steps": 4})
    assert res.status_code == 200
    assert res.json()["status"] == "complete"

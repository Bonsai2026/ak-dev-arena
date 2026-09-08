"""Real-mixing tests: Cursor/Claude/Manus/FreeBuff features (mocked LLM)."""

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import agent, contextx, files, llm, manager, workflows
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    monkeypatch.setenv("ARENA_LOCAL_CONFIG", str(tmp_path / "local.yaml"))
    return tmp_path


@pytest.fixture(autouse=True)
def _clean_state():
    agent.ASK_LOG.clear()
    agent.APPROVALS.clear()
    workflows.reset_for_tests()
    manager.reset_for_tests()
    yield
    agent.ASK_LOG.clear()
    agent.APPROVALS.clear()
    workflows.reset_for_tests()
    manager.reset_for_tests()


def _script(responses, capture=None):
    it = iter(responses)

    async def _fake(model, messages, *a, **k):
        if capture is not None:
            capture.append(messages)
        try:
            content = next(it)
        except StopIteration:
            content = json.dumps({"thought": "t", "tool": "done",
                                  "args": {"summary": "ok"}})
        return {"content": content, "model": model, "provider": "mock", "usage": {}}

    return _fake


def _done(summary="ok"):
    return json.dumps({"thought": "t", "tool": "done", "args": {"summary": summary}})


# ------------------------------------------------------- mentions + rules ---


def test_mention_expands_file_context(ws, monkeypatch):
    (ws / "note.txt").write_text("SECRET-777")
    captured = []
    monkeypatch.setattr(llm, "chat_completion", _script(["hi"], captured))
    res = client.post("/api/chat", json={
        "model": "x", "messages": [{"role": "user", "content": "read @note.txt please"}]})
    assert res.status_code == 200
    sent = json.dumps(captured[0])
    assert "SECRET-777" in sent
    assert "[context @note.txt]" in sent


def test_rules_auto_injected(ws, monkeypatch):
    (ws / ".akrules").write_text("Always answer: RULES-42")
    captured = []
    monkeypatch.setattr(llm, "chat_completion", _script(["hi"], captured))
    client.post("/api/chat", json={
        "model": "x", "messages": [{"role": "user", "content": "hello"}]})
    assert captured[0][0]["role"] == "system"
    assert "RULES-42" in captured[0][0]["content"]


def test_rules_endpoint(ws):
    (ws / ".akrules").write_text("be nice")
    res = client.get("/api/context/rules")
    assert res.json()["found"] is True
    assert "be nice" in res.json()["rules"]


def test_codebase_mention(ws):
    (ws / "a.py").write_text("x=1")
    text, toks = contextx.resolve_mentions("summarize @codebase", root=ws)
    assert toks == ["codebase"]
    assert "a.py" in text


# ------------------------------------------------------------- repomap ---


def test_repomap_always_works(ws):
    (ws / "app.py").write_text("print(1)\n")
    res = client.get("/api/code/repomap")
    assert res.status_code == 200
    body = res.json()
    assert body["engine"] in ("aider", "fallback")
    assert "app.py" in body["map"]


# ------------------------------------------------------------- composer ---


def _composer_script(old, new, path="a.py"):
    return _script([json.dumps(
        {"patches": [{"path": path, "old_text": old, "new_text": new}]})])


def test_composer_preview_and_apply(ws, monkeypatch):
    (ws / "a.py").write_text("x = 1\n")
    monkeypatch.setattr(llm, "chat_completion", _composer_script("x = 1", "x = 2"))
    res = client.post("/api/code/composer", json={"instructions": "bump x"})
    assert res.status_code == 200
    patch = res.json()["patches"][0]
    assert patch["ok"] is True
    assert "x = 2" in patch["diff"]
    assert (ws / "a.py").read_text() == "x = 1\n"  # preview writes nothing

    res = client.post("/api/code/composer/apply", json={
        "patches": [{"path": "a.py", "old_text": "x = 1", "new_text": "x = 2"}]})
    assert res.status_code == 200
    assert res.json()["applied"] == ["a.py"]
    assert (ws / "a.py").read_text() == "x = 2\n"


def test_composer_new_file(ws, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion",
                        _composer_script("", "hello", path="new.txt"))
    res = client.post("/api/code/composer", json={"instructions": "make new.txt"})
    assert res.json()["patches"][0]["ok"] is True
    res = client.post("/api/code/composer/apply", json={
        "patches": [{"path": "new.txt", "old_text": "", "new_text": "hello"}]})
    assert res.json()["applied"] == ["new.txt"]
    assert (ws / "new.txt").read_text() == "hello"


def test_complete(ws, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", _script(["    return x + 1"]))
    res = client.post("/api/code/complete", json={"file": "a.py", "prefix": "def f(x):\n"})
    assert res.status_code == 200
    assert "return x + 1" in res.json()["suggestion"]


# ---------------------------------------------------------------- slash ---


def test_slash_list(ws):
    res = client.get("/api/slash/list")
    names = {c["name"] for c in res.json()["commands"]}
    assert {"/commit", "/review", "/test", "/explain", "/help"} <= names


def test_slash_help(ws):
    res = client.post("/api/slash/run", json={"command": "help"})
    assert "/commit" in res.json()["output"]


def test_slash_custom_command(ws, monkeypatch):
    (ws / ".arena" / "commands").mkdir(parents=True)
    (ws / ".arena" / "commands" / "poem.md").write_text("Write a poem about {args}.")
    monkeypatch.setattr(llm, "chat_completion", _script(["roses are red"]))
    res = client.get("/api/slash/list")
    assert "/poem" in {c["name"] for c in res.json()["commands"]}
    res = client.post("/api/slash/run", json={"command": "poem", "args": "arena"})
    assert res.json()["output"] == "roses are red"


def test_slash_commit(ws, monkeypatch):
    (ws / "f.txt").write_text("v1")
    client.post("/api/git/checkpoint", json={"message": "base"})
    (ws / "f.txt").write_text("v2")
    monkeypatch.setattr(llm, "chat_completion", _script(["feat: bump f"]))
    res = client.post("/api/slash/run", json={"command": "commit"})
    assert res.status_code == 200
    assert "feat: bump f" in res.json()["output"]


# ------------------------------------------------------- profiles/plan ---


def test_profiles_list(ws):
    res = client.get("/api/agent/profiles")
    ids = {p["id"] for p in res.json()["profiles"]}
    assert ids == {"coder", "researcher", "reviewer", "planner"}


def test_plan_creates_todos(ws, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion",
                        _script([json.dumps({"steps": ["one", "two"]})]))
    res = client.post("/api/agent/plan", json={"task": "do things"})
    assert res.status_code == 200
    assert res.json()["plan"] == ["one", "two"]
    res = client.get("/api/todos")
    assert len(res.json()["todos"]) == 2


def test_profile_restricts_tools(ws, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", _script([
        json.dumps({"thought": "t", "tool": "write_file",
                    "args": {"path": "x.txt", "content": "no"}}),
        _done("stopped"),
    ]))
    res = asyncio.run(agent.run_agent("write x", "m", 4, work_dir=ws, profile="reviewer"))
    assert "not allowed" in res["steps"][0]["result"]
    assert not (ws / "x.txt").exists()


# -------------------------------------------------- permissions/approvals ---


def test_permission_deny_blocks(ws, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", _script([
        json.dumps({"thought": "t", "tool": "write_file",
                    "args": {"path": "x.txt", "content": "no"}}),
        _done("stopped"),
    ]))
    res = asyncio.run(agent.run_agent("write x", "m", 4, work_dir=ws,
                                      permissions={"write_file": "deny"}))
    assert "BLOCKED" in res["steps"][0]["result"]
    assert not (ws / "x.txt").exists()


def test_ask_then_approve(ws, monkeypatch):
    script = [_script([
        json.dumps({"thought": "t", "tool": "run", "args": {"cmd": "echo hi"}}),
        _done("ok")])]
    monkeypatch.setattr(llm, "chat_completion", script[0])
    res = asyncio.run(agent.run_agent("run echo", "m", 4, work_dir=ws,
                                      permissions={"run": "ask"}))
    assert "NEEDS APPROVAL" in res["steps"][0]["result"]
    pending = client.get("/api/agent/pending").json()["pending"]
    assert any(p["tool"] == "run" for p in pending)

    res = client.post("/api/agent/approve", json={"tool": "run"})
    assert res.json()["tool"] == "run"

    monkeypatch.setattr(llm, "chat_completion", _script([
        json.dumps({"thought": "t", "tool": "run", "args": {"cmd": "echo hi"}}),
        _done("ok")]))
    res = asyncio.run(agent.run_agent("run echo", "m", 4, work_dir=ws,
                                      permissions={"run": "ask"}))
    assert "hi" in res["steps"][0]["result"]


# ---------------------------------------------------------------- todos ---


def test_todos_crud(ws):
    res = client.post("/api/todos", json={"text": "first"})
    tid = res.json()["id"]
    assert client.get("/api/todos").json()["todos"][0]["done"] is False
    res = client.patch(f"/api/todos/{tid}", json={"done": True})
    assert res.json()["done"] is True
    res = client.post("/api/todos/clear")
    assert res.json()["cleared"] == 1
    assert client.get("/api/todos").json()["todos"] == []


# ------------------------------------------------------------ workflows ---


def _wait_run(c, run_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = c.get(f"/api/workflows/runs/{run_id}")
        if res.json()["status"] in ("done", "failed"):
            return res.json()
        time.sleep(0.1)
    raise AssertionError("workflow run did not finish")


def test_workflow_save_run(ws, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", _script([_done("s1"), _done("s2")]))
    with TestClient(app) as c:
        res = c.post("/api/workflows", json={
            "name": "demo",
            "steps": [{"task": "step one"}, {"task": "step two", "profile": "planner"}]})
        assert res.status_code == 200
        res = c.post("/api/workflows/demo/run", json={})
        run_id = res.json()["id"]
        run = _wait_run(c, run_id)
        assert run["status"] == "done"
        assert [r["summary"] for r in run["results"]] == ["s1", "s2"]


# ------------------------------------------------------------------ mcp ---


def test_mcp_status_shape(ws):
    res = client.get("/api/mcp/status")
    assert res.status_code == 200
    assert "installed" in res.json()
    assert isinstance(res.json()["servers"], list)


def test_mcp_call_unknown_server(ws):
    res = client.post("/api/mcp/call", json={"server": "nope", "tool": "t"})
    assert res.status_code == 400


# ------------------------------------------------------------------ web ---


def test_web_search_mocked(ws, monkeypatch):
    from backend.app import web as web_mod

    monkeypatch.setattr(web_mod, "web_search",
                        lambda q, max_results=5: [{"title": "T", "url": "u", "snippet": "s"}])
    res = client.post("/api/web/search", json={"q": "arena"})
    assert res.json()["results"][0]["title"] == "T"


def test_web_fetch_rejects_bad_url(ws):
    res = client.post("/api/web/fetch", json={"url": "notaurl-at-all"})
    assert res.status_code == 400


# ------------------------------------------------------------ artifacts ---


def test_job_artifacts(ws, monkeypatch):
    async def _fake(model, messages, *a, **k):
        if len(messages) <= 2:
            return {"content": json.dumps(
                {"thought": "t", "tool": "write_file",
                 "args": {"path": "made.txt", "content": "hi"}}),
                "model": model, "provider": "mock", "usage": {}}
        return {"content": _done("ok"), "model": model, "provider": "mock", "usage": {}}

    monkeypatch.setattr(llm, "chat_completion", _fake)
    with TestClient(app) as c:
        job_id = c.post("/api/jobs", json={"task": "make file", "max_steps": 3}).json()["id"]
        deadline = time.time() + 10
        while time.time() < deadline:
            if c.get(f"/api/jobs/{job_id}").json()["status"] in ("done", "complete", "failed"):
                break
            time.sleep(0.1)
        res = c.get(f"/api/jobs/{job_id}/artifacts")
        assert res.status_code == 200
        assert any(a["path"] == "made.txt" for a in res.json()["artifacts"])

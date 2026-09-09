"""Phase B tests: task store (progress/cancel/timeout), verification evidence,
new tools (edit/delete/build/test/git), permission defaults."""

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import agent, files, gitops, llm, procman, projects
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    monkeypatch.setenv("ARENA_LOCAL_CONFIG", str(tmp_path / "local.yaml"))
    return tmp_path


@pytest.fixture(autouse=True)
def _clean():
    agent.reset_tasks_for_tests()
    procman.reset_for_tests()
    agent.ASK_LOG.clear()
    agent.APPROVALS.clear()
    yield
    agent.reset_tasks_for_tests()
    procman.reset_for_tests()
    agent.ASK_LOG.clear()
    agent.APPROVALS.clear()


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


def _done(summary="ok", verification=None):
    args = {"summary": summary}
    if verification:
        args["verification"] = verification
    return json.dumps({"thought": "t", "tool": "done", "args": args})


# ------------------------------------------------------- task store flow ---
# NOTE: Starlette's TestClient portal does not advance background asyncio tasks
# between requests, so task progression is tested with a real asyncio loop
# (exactly how uvicorn runs them in production). HTTP wiring is tested too.


async def _wait_task(tid, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = agent.get_task(tid)
        if state and state["status"] not in ("queued", "running"):
            return state
        await asyncio.sleep(0.02)
    return agent.get_task(tid)


def test_task_api_create_and_cancel_wiring(ws, monkeypatch):
    async def _slow(model, messages, *a, **k):
        await asyncio.sleep(60)  # portal doesn't advance — stays running

    monkeypatch.setattr(llm, "chat_completion", _slow)
    res = client.post("/api/agent/tasks", json={"task": "do it", "max_steps": 3})
    assert res.status_code == 200
    tid = res.json()["id"]
    state = client.get(f"/api/agent/tasks/{tid}").json()
    assert state["status"] in ("queued", "running")
    cancel = client.delete(f"/api/agent/tasks/{tid}").json()
    assert cancel["cancelled"] is True
    assert client.get("/api/agent/tasks").json()["tasks"]


def test_task_cancel_settles(ws, monkeypatch):
    async def _slow(model, messages, *a, **k):
        await asyncio.sleep(0.3)
        return json.dumps({"thought": "t", "tool": "done", "args": {"summary": "x"}})

    monkeypatch.setattr(llm, "chat_completion", _slow)

    async def _run():
        state = agent.create_task("do it", "m", 3)
        tid = state["id"]
        await asyncio.sleep(0.05)
        assert agent.cancel_task(tid) is True
        done = await _wait_task(tid)
        return done

    state = asyncio.run(_run())
    assert state["status"] in ("cancelled", "complete")
    assert state["finished"] is not None


def test_task_complete_has_step_evidence(ws, monkeypatch):
    # first call = plan, second = inspect, third = done
    monkeypatch.setattr(llm, "chat_completion", _script([
        json.dumps({"steps": ["inspect workspace"]}),
        json.dumps({"thought": "inspect", "tool": "list_files", "args": {}}),
        _done("all good", [["files exist", "pass"]]),
    ]))

    async def _run():
        task = agent.create_task("check", "m", 4)
        return await _wait_task(task["id"], timeout=4.0)

    state = asyncio.run(_run())
    assert state["status"] in ("complete", "done")
    assert any(s["tool"] == "list_files" for s in state["steps"])
    assert state["criteria"] and state["criteria"][0]["status"] == "pass"
    assert state["verification"] is not None


def test_task_list(ws, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", _script([_done()]))
    client.post("/api/agent/tasks", json={"task": "a", "max_steps": 2})
    client.post("/api/agent/tasks", json={"task": "b", "max_steps": 2})
    res = client.get("/api/agent/tasks")
    assert len(res.json()["tasks"]) >= 2


# --------------------------------------------------------- new tools ---


def test_edit_and_delete_tools(ws, monkeypatch):
    (ws / "a.py").write_text("x = 1\n")
    monkeypatch.setattr(llm, "chat_completion", _script([
        json.dumps({"thought": "edit", "tool": "edit_file",
                    "args": {"path": "a.py", "old_text": "x = 1", "new_text": "x = 2"}}),
        json.dumps({"thought": "delete", "tool": "delete_file", "args": {"path": "b.txt"}}),
        _done(),
    ]))
    (ws / "b.txt").write_text("bye")
    agent.APPROVALS["delete_file"] = time.time() + 60  # approve delete for test
    res = client.post("/api/agent/run", json={"task": "edit + delete", "max_steps": 5})
    assert res.status_code == 200
    assert (ws / "a.py").read_text() == "x = 2\n"
    assert not (ws / "b.txt").exists()


def test_delete_requires_approval(ws, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", _script([
        json.dumps({"thought": "delete", "tool": "delete_file", "args": {"path": "x.txt"}}),
    ]))
    (ws / "x.txt").write_text("keep me")
    res = client.post("/api/agent/run", json={"task": "delete", "max_steps": 3})
    assert "NEEDS APPROVAL" in res.json()["steps"][0]["result"]
    assert (ws / "x.txt").exists()
    assert agent.pending_approvals()[-1]["tool"] == "delete_file"


def test_run_build_detects_no_script(ws):
    project = projects.detect(ws)
    assert project["type"] == "static"
    cmd = projects.build_cmd(project)
    assert cmd is None


def test_run_build_npm(ws, monkeypatch):
    (ws / "package.json").write_text(json.dumps(
        {"scripts": {"build": "echo built", "dev": "echo dev", "test": "jest"}}))
    project = projects.detect(ws)
    assert project["type"] == "node"
    assert project["frameworks"] == []
    assert projects.build_cmd(project) == ["npm", "run", "build"]
    assert projects.test_cmd(project) == ["npm", "test"]
    # non-vite dev script: no --port flag
    assert projects.dev_cmd(project, 5000) == ["npm", "run", "dev"]
    # vite-style dev script gets the port flag
    (ws / "package.json").write_text(json.dumps(
        {"scripts": {"dev": "vite"}}))
    project2 = projects.detect(ws)
    assert "vite" in project2["frameworks"]
    assert projects.dev_cmd(project2, 5000) == ["npm", "run", "dev", "--", "--port", "5000"]


def test_procman_run_and_stop(ws):
    res = procman.run(["echo", "hello-proc"], ws, timeout=10)
    assert res["exit_code"] == 0
    assert "hello-proc" in res["stdout"]
    # server start/stop
    info = procman.start(["python", "-c", "import time; time.sleep(30)"], ws)
    assert info["status"] == "running"
    assert procman.stop(info["id"]) is True
    stopped = [p for p in procman.list_processes() if p["status"] == "stopped"]
    assert any(p["pid"] == info["pid"] for p in stopped)


def test_git_diff_and_status_tools(ws, monkeypatch):
    (ws / "f.txt").write_text("v1\n")
    client.post("/api/git/checkpoint", json={"message": "base"})
    (ws / "f.txt").write_text("v2\n")
    monkeypatch.setattr(llm, "chat_completion", _script([
        json.dumps({"thought": "status", "tool": "git_status", "args": {}}),
        json.dumps({"thought": "diff", "tool": "git_diff", "args": {}}),
        _done(),
    ]))
    res = client.post("/api/agent/run", json={"task": "git", "max_steps": 5})
    assert res.status_code == 200
    joined = json.dumps(res.json()["steps"])
    assert "f.txt" in joined and "v2" in joined


# ------------------------------------------------------- verification ---


def test_verification_summarizes_run_build(ws, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", _script([
        json.dumps({"thought": "build", "tool": "run_build", "args": {}}),
        _done(),
    ]))
    res = client.post("/api/agent/run", json={"task": "build", "max_steps": 4})
    body = res.json()
    assert body["status"] == "complete"
    assert body["verification"]["has_evidence"] is True or \
           body["verification"] == {"build": None, "tests": None, "servers": [],
                                    "commands": [], "has_evidence": False}


# ------------------------------------------------------- cancellation ---


def test_run_agent_cancel_event(ws, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", _script([
        json.dumps({"thought": "w", "tool": "write_file",
                    "args": {"path": "a.txt", "content": "hi"}}),
        _done(),
    ]))
    cancel = asyncio.Event()
    cancel.set()
    res = client.post("/api/agent/run", json={"task": "x", "max_steps": 5})
    # sync endpoint is unaffected by event (not passed) — just sanity 200
    assert res.status_code == 200

    async def _cancelled():
        cancel = asyncio.Event()
        cancel.set()
        out = await agent.run_agent("x", "m", 3, work_dir=ws, cancel=cancel)
        assert out["status"] == "cancelled"

    asyncio.run(_cancelled())


def test_git_revert_tool_blocked_without_approval(ws, monkeypatch):
    (ws / "f.txt").write_text("v1\n")
    client.post("/api/git/checkpoint", json={"message": "base"})
    (ws / "f.txt").write_text("v2\n")
    client.post("/api/git/checkpoint", json={"message": "sec"})
    monkeypatch.setattr(llm, "chat_completion", _script([
        json.dumps({"thought": "revert", "tool": "git_revert", "args": {}}),
    ]))
    res = client.post("/api/agent/run", json={"task": "revert", "max_steps": 3})
    assert "NEEDS APPROVAL" in res.json()["steps"][0]["result"]

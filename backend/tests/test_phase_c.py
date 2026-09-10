"""Phase C tests: workspace layout/cleanup, run/build jobs, browser inspection."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import browser, execjobs, files, procman, workspacex
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    monkeypatch.setenv("ARENA_LOCAL_CONFIG", str(tmp_path / "local.yaml"))
    return tmp_path


@pytest.fixture(autouse=True)
def _clean():
    execjobs.reset_for_tests()
    procman.reset_for_tests()
    yield
    execjobs.reset_for_tests()
    procman.reset_for_tests()


# ------------------------------------------------------ workspace layout ---


def test_workspace_layout_created(ws):
    res = client.get("/api/workspace")
    assert res.status_code == 200
    body = res.json()
    assert set(body["layout"]) == {"temp", "cache", "logs", "artifacts", "runtime"}
    for sub, p in body["layout"].items():
        assert (ws / ".akdev" / sub).is_dir()
    assert "akdev_bytes" in body["usage"]


def test_cleanup_removes_old_temp_only(ws):
    ws.mkdir  # noqa: B018 — clarity
    workspacex.ensure()
    old = ws / ".akdev" / "temp" / "old.txt"
    old.write_text("x" * 100)
    # make it look 2 days old
    import os
    os.utime(old, (time.time() - 48 * 3600, time.time() - 48 * 3600))
    fresh = ws / ".akdev" / "temp" / "fresh.txt"
    fresh.write_text("y")
    user = ws / "user-project.txt"
    user.write_text("keep me")

    result = workspacex.cleanup(max_age_hours=24)
    assert result["removed_files"] == 1
    assert not old.exists()
    assert fresh.exists()
    assert user.exists()


# ------------------------------------------------------- run/build jobs ---


def test_run_build_not_detected(ws):
    res = client.post("/api/run", json={"action": "build"})
    assert res.status_code == 400
    assert "No build command" in res.json()["detail"]


def test_run_api_wiring(ws, monkeypatch):
    (ws / "package.json").write_text('{"scripts": {"test": "echo tests-ok"}}')
    res = client.post("/api/run", json={"action": "test"})
    assert res.status_code == 200
    job = res.json()
    assert job["action"] == "test"
    assert job["status"] == "queued"
    got = client.get(f"/api/run/{job['id']}").json()
    assert got["id"] == job["id"]
    assert "jobs" in client.get("/api/run").json()
    # 404 for unknown
    assert client.get("/api/run/nope").status_code == 404


def test_run_test_job_node_progresses(ws, monkeypatch):
    (ws / "package.json").write_text('{"scripts": {"test": "echo tests-ok"}}')

    async def _go():
        job = execjobs.start("test", str(ws))
        for _ in range(100):
            state = execjobs.get(job["id"])
            if state["status"] in ("passed", "failed", "cancelled"):
                return state
            await asyncio.sleep(0.05)
        return execjobs.get(job["id"])

    state = asyncio.run(_go())
    assert state["status"] == "passed"
    assert "tests-ok" in state["output"]
    assert state["exit_code"] == 0


def test_run_serve_then_stop(ws):
    import socket
    import sys
    # static project → no dev cmd → ExecError (no fake serving)
    with pytest.raises(execjobs.ExecError):
        execjobs.start("serve", str(ws))
    # node project whose dev script REALLY binds a port → serving → stop
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    (ws / "package.json").write_text(
        '{"scripts": {"dev": "sh -c \\"%s -m http.server %d\\""}}' % (sys.executable, port))
    execjobs.reset_for_tests()

    async def _go():
        job = execjobs.start("serve", str(ws), port=port)
        for _ in range(100):
            state = execjobs.get(job["id"])
            if state["status"] in ("serving", "failed", "cancelled"):
                break
            await asyncio.sleep(0.05)
        return execjobs.get(job["id"])

    state = asyncio.run(_go())
    assert state["status"] == "serving", state  # port actually opened — no fake
    assert state["url"] and state["pid"]
    assert procman.is_port_open(port) is True
    assert execjobs.cancel(state["id"]) is True
    assert execjobs.get(state["id"])["status"] == "stopped"
    for _ in range(40):  # tree-killed children → port freed
        if not procman.is_port_open(port):
            break
        import time
        time.sleep(0.1)
    assert procman.is_port_open(port) is False  # no orphan


# ------------------------------------------------------ browser inspect ---


def test_browser_inspect_install_hint(ws):
    res = client.post("/api/browser/inspect", json={"url": "http://127.0.0.1:1420"})
    if browser.is_available():
        # real browsers can still be tested when playwright is installed
        assert res.status_code in (200, 400)
    else:
        assert res.status_code == 400
        assert "Playwright" in res.json()["detail"]


def test_browser_rejects_bad_url():
    with pytest.raises(browser.BrowserError):
        asyncio.run(browser.inspect("file:///etc/passwd"))


def test_browser_tool_needs_permission(ws, monkeypatch):
    from backend.app import agent, llm
    import json as _json

    agent.APPROVALS.clear()
    monkeypatch.setattr(files, "WORKSPACE", ws)
    monkeypatch.setattr(llm, "chat_completion", _script_browser([_json.dumps(
        {"thought": "inspect", "tool": "browser_inspect",
         "args": {"url": "http://127.0.0.1:1420"}})]))
    res = client.post("/api/agent/run", json={"task": "check", "max_steps": 3})
    assert "NEEDS APPROVAL" in res.json()["steps"][0]["result"]


def _script_browser(responses):
    it = iter(responses)

    async def _fake(model, messages, *a, **k):
        try:
            content = next(it)
        except StopIteration:
            content = '{"thought": "t", "tool": "done", "args": {"summary": "ok"}}'
        return {"content": content, "model": model, "provider": "mock", "usage": {}}

    return _fake

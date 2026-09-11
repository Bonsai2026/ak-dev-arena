"""Continuation, .akrules project memory, and verified-only auto-commit."""

import asyncio
import subprocess

import pytest

from backend.app import agent, files


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _clean():
    agent.reset_tasks_for_tests()
    yield
    agent.reset_tasks_for_tests()


def _git(ws, *args):
    subprocess.run(["git", *args], cwd=ws, capture_output=True, check=True)


# ------------------------------------------------------------- .akrules ----

def test_akrules_loaded_and_capped(ws):
    (ws / ".akrules").write_text("always use TypeScript strict mode", encoding="utf-8")
    assert "strict mode" in agent._load_rules(ws)
    (ws / ".akrules").write_text("x" * 9000, encoding="utf-8")
    assert len(agent._load_rules(ws)) == agent._RULES_CAP
    (ws / ".akrules").unlink()
    assert agent._load_rules(ws) == ""  # missing → silent empty


# --------------------------------------------------------- continuation ----

def _finished_task(tid, ws):
    state = {"id": tid, "task": "build the login page", "model": "m/x",
             "profile": "coder", "status": "done", "created": 1.0,
             "started": 1.0, "finished": 2.0, "steps": [],
             "summary": "login page done", "error": "",
             "verification": {"tests": "pass"}, "criteria": [], "plan": [],
             "files": ["src/login.tsx"], "_work_dir": str(ws),
             "_cancel": asyncio.Event()}
    agent._TASKS[tid] = state
    return state


def test_continue_task_carries_context(ws):
    _finished_task("c1", ws)

    async def _go():
        return agent.continue_task("c1", "now add logout too")

    new = asyncio.run(_go())
    assert new["id"] != "c1"
    assert "New request: now add logout too" in new["task"]
    assert "build the login page" in new["task"]
    assert "login page done" in new["task"]
    assert "src/login.tsx" in new["task"]
    assert new["model"] == "m/x"  # inherited
    agent.reset_tasks_for_tests()


def test_continue_refuses_running_task(ws):
    state = _finished_task("c2", ws)
    state["status"] = "running"
    with pytest.raises(agent.AgentError) as exc:
        asyncio.run(agent.continue_task("c2", "x"))
    assert "still running" in str(exc.value)


def test_continue_404_unknown(ws):
    from fastapi.testclient import TestClient
    from backend.app.main import app
    client = TestClient(app)
    r = client.post("/api/agent/tasks/nope/continue", json={"follow_up": "x"})
    assert r.status_code == 400


# ---------------------------------------------------------- auto-commit ----

def test_auto_commit_only_when_verified(ws):
    _git(ws, "init", "-q")
    _git(ws, "config", "user.email", "t@t.t")
    _git(ws, "config", "user.name", "t")
    (ws / "file.txt").write_text("work", encoding="utf-8")

    state = _finished_task("a1", ws)
    state["_auto_commit"] = True
    agent._maybe_auto_commit(state, ws)
    assert state.get("auto_committed")  # verified done → committed
    log = subprocess.run(["git", "log", "--oneline"], cwd=ws,
                         capture_output=True, text=True).stdout
    assert "auto-commit after verified task a1" in log

    # unverified → NO commit even if flag set
    (ws / "file2.txt").write_text("more", encoding="utf-8")
    state2 = _finished_task("a2", ws)
    state2["_auto_commit"] = True
    state2["verification"] = {"tests": "fail"}
    agent._maybe_auto_commit(state2, ws)
    assert "auto_committed" not in state2
    log2 = subprocess.run(["git", "log", "--oneline"], cwd=ws,
                          capture_output=True, text=True).stdout
    assert "a2" not in log2


def test_no_auto_commit_flag_means_no_commit(ws):
    _git(ws, "init", "-q")
    _git(ws, "config", "user.email", "t@t.t")
    _git(ws, "config", "user.name", "t")
    state = _finished_task("a3", ws)  # verified but flag NOT set
    agent._maybe_auto_commit(state, ws)
    assert "auto_committed" not in state

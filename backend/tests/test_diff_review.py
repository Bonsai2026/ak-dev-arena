"""Diff review + 1-click undo: every agent write/edit/delete is tracked with a
before-snapshot, exposed as diffs, and individually revertable with a
conflict guard."""

import asyncio

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


def _task(tmp_path):
    state = {"id": "dt1", "task": "t", "model": "m", "status": "running",
             "created": 1.0, "_work_dir": str(tmp_path), "_file_changes": {}}
    agent._TASKS["dt1"] = state
    return state


def test_write_creates_then_revert_deletes(ws):
    _task(ws)
    asyncio.run(agent._dispatch("write_file",
                                {"path": "new.txt", "content": "hello"}, ws, "dt1"))
    assert (ws / "new.txt").read_text() == "hello"
    changes = agent.task_changes("dt1")
    assert len(changes) == 1
    assert changes[0]["path"] == "new.txt"
    assert changes[0]["status"] == "added"

    res = agent.revert_change("dt1", "new.txt")
    assert "deleted" in res["action"]
    assert not (ws / "new.txt").exists()
    # change entry cleared after revert
    assert agent.task_changes("dt1") == []


def test_edit_records_before_and_revert_restores(ws):
    _task(ws)
    (ws / "code.py").write_text("print('old')\n", encoding="utf-8")
    asyncio.run(agent._dispatch(
        "edit_file", {"path": "code.py", "old_text": "old", "new_text": "new"},
        ws, "dt1"))
    assert (ws / "code.py").read_text() == "print('new')\n"
    ch = agent.task_changes("dt1")[0]
    assert ch["status"] == "modified"
    assert ch["additions"] >= 1 and ch["deletions"] >= 1
    assert "print('new')" in ch["diff"]

    res = agent.revert_change("dt1", "code.py")
    assert "restored" in res["action"]
    assert (ws / "code.py").read_text() == "print('old')\n"


def test_delete_records_before_and_revert_restores(ws):
    _task(ws)
    (ws / "gone.txt").write_text("keep me", encoding="utf-8")
    asyncio.run(agent._dispatch("delete_file", {"path": "gone.txt"}, ws, "dt1"))
    assert not (ws / "gone.txt").exists()
    ch = agent.task_changes("dt1")[0]
    assert ch["status"] == "deleted"

    agent.revert_change("dt1", "gone.txt")
    assert (ws / "gone.txt").read_text() == "keep me"


def test_revert_refuses_on_conflict(ws):
    _task(ws)
    asyncio.run(agent._dispatch("write_file",
                                {"path": "f.txt", "content": "agent"}, ws, "dt1"))
    # user edits the file AFTER the agent wrote it → revert must refuse
    (ws / "f.txt").write_text("user-touched", encoding="utf-8")
    with pytest.raises(agent.AgentError) as exc:
        agent.revert_change("dt1", "f.txt")
    assert "changed since" in str(exc.value)
    assert (ws / "f.txt").read_text() == "user-touched"  # untouched


def test_endpoints(ws):
    from fastapi.testclient import TestClient
    from backend.app.main import app
    client = TestClient(app)
    _task(ws)
    asyncio.run(agent._dispatch("write_file",
                                {"path": "a.txt", "content": "x"}, ws, "dt1"))
    r = client.get("/api/agent/tasks/dt1/changes")
    assert r.status_code == 200
    assert r.json()["changes"][0]["path"] == "a.txt"

    r = client.post("/api/agent/tasks/dt1/changes/revert", json={"path": "a.txt"})
    assert r.status_code == 200
    assert not (ws / "a.txt").exists()

    # unknown task → 404; unknown file → 400
    assert client.get("/api/agent/tasks/nope/changes").status_code == 404
    r = client.post("/api/agent/tasks/dt1/changes/revert", json={"path": "nope.txt"})
    assert r.status_code == 400

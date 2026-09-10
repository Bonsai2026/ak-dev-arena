"""SSE streaming of agent task state (replaces UI polling)."""

import pytest
from fastapi.testclient import TestClient

from backend.app import agent, files
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _clean():
    agent.reset_tasks_for_tests()
    yield
    agent.reset_tasks_for_tests()


def _done_task(tid):
    return {"id": tid, "task": "t", "model": "m", "status": "done",
            "created": 1.0, "started": 1.0, "finished": 2.0, "steps": [],
            "summary": "ok", "error": "", "verification": None,
            "criteria": [], "plan": [], "files": []}


def test_events_stream_terminal_state_then_close(ws):
    agent._TASKS["s1"] = _done_task("s1")
    with client.stream("GET", "/api/agent/tasks/s1/events") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        data_frames = [ln for ln in r.iter_lines() if ln.startswith("data:")]
    assert data_frames, "expected at least one data frame"
    assert '"id": "s1"' in data_frames[0] or '"id":"s1"' in data_frames[0]
    assert '"done"' in data_frames[-1]  # terminal frame, then stream closed


def test_events_404_for_unknown_task(ws):
    assert client.get("/api/agent/tasks/nope/events").status_code == 404

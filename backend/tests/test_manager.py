"""Manager tests: parallel jobs with isolated workspaces (mocked LLM)."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from backend.app import files, llm, manager
from backend.app.main import app


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    manager.reset_for_tests()
    yield tmp_path
    manager.reset_for_tests()


def _done_script(summary="job done"):
    async def _fake(model, messages, max_tokens=1500, temperature=0.3):
        return {"content": json.dumps(
            {"thought": "t", "tool": "done", "args": {"summary": summary}}),
            "model": model, "provider": "mock", "usage": {}}
    return _fake


def _wait_done(client, job_id, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        res = client.get(f"/api/jobs/{job_id}")
        assert res.status_code == 200
        if res.json()["status"] in ("done", "complete", "failed"):
            return res.json()
        time.sleep(0.1)
    raise AssertionError("job did not finish in time")


def test_job_lifecycle(ws, monkeypatch):
    monkeypatch.setattr(llm, "chat_completion", _done_script("alpha finished"))
    with TestClient(app) as c:
        res = c.post("/api/jobs", json={"task": "do alpha", "max_steps": 3})
        assert res.status_code == 200
        job_id = res.json()["id"]

        job = _wait_done(c, job_id)
        assert job["summary"] == "alpha finished"

        res = c.get("/api/jobs")
        assert any(j["id"] == job_id for j in res.json()["jobs"])


def test_jobs_have_isolated_workspaces(ws, monkeypatch):
    async def _fake(model, messages, max_tokens=1500, temperature=0.3):
        return {"content": json.dumps(
            {"thought": "t", "tool": "write_file",
             "args": {"path": "whoami.txt", "content": model}}),
            "model": model, "provider": "mock", "usage": {}}

    async def _fake2(model, messages, max_tokens=1500, temperature=0.3):
        if len(messages) <= 2:
            return await _fake(model, messages)
        return {"content": json.dumps(
            {"thought": "t", "tool": "done", "args": {"summary": "ok"}}),
            "model": model, "provider": "mock", "usage": {}}

    monkeypatch.setattr(llm, "chat_completion", _fake2)
    with TestClient(app) as c:
        ids = [c.post("/api/jobs", json={"task": f"job{i}", "max_steps": 3}).json()["id"]
               for i in range(2)]
        for job_id in ids:
            _wait_done(c, job_id)
    assert ids[0] != ids[1]
    assert (ws / "jobs" / ids[0] / "whoami.txt").exists()
    assert (ws / "jobs" / ids[1] / "whoami.txt").exists()


def test_unknown_job_404(ws):
    res = TestClient(app).get("/api/jobs/nope")
    assert res.status_code == 404

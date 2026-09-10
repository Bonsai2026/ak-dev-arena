"""Persistence — tasks + run jobs survive a restart; mid-flight work is
honestly marked 'interrupted' (never re-labelled done/passed)."""

import asyncio
import json

import pytest

from backend.app import agent, execjobs, files, store


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _clean():
    agent.reset_tasks_for_tests()
    execjobs.reset_for_tests()
    yield
    agent.reset_tasks_for_tests()
    execjobs.reset_for_tests()


def _mk_task(tid, status, summary="did work"):
    return {"id": tid, "task": "t", "model": "m", "status": status,
            "created": 1.0, "started": 1.0, "finished": 2.0,
            "steps": [], "summary": summary, "error": "",
            "verification": {"tests": "pass"}, "criteria": [], "plan": [],
            "files": []}


def _mk_job(jid, status):
    return {"id": jid, "action": "build", "status": status, "created": 1.0,
            "finished": 2.0 if status not in ("running", "serving") else None,
            "exit_code": 0 if status == "passed" else None, "output": "ok",
            "error": "", "pid": 123 if status == "serving" else None,
            "port": None, "url": None, "cmd": "npm run build", "path": "/x"}


def test_finished_state_survives_restart(ws):
    agent._TASKS["t1"] = _mk_task("t1", "done")
    execjobs._jobs["j1"] = _mk_job("j1", "passed")
    assert store.save_state() is True
    assert store.state_path().is_file()

    # simulate restart: wipe in-memory stores, then restore
    agent._TASKS.clear()
    execjobs._jobs.clear()
    stats = store.restore_state()
    assert stats["tasks"] == 1 and stats["jobs"] == 1
    assert agent.get_task("t1")["summary"] == "did work"
    assert agent.get_task("t1")["status"] == "done"
    assert execjobs.get("j1")["status"] == "passed"
    assert stats["interrupted"] == 0


def test_midflight_marked_interrupted_not_done(ws):
    agent._TASKS["t2"] = _mk_task("t2", "running")
    execjobs._jobs["j2"] = _mk_job("j2", "serving")
    execjobs._jobs["j3"] = _mk_job("j3", "running")
    store.save_state()
    agent._TASKS.clear()
    execjobs._jobs.clear()
    stats = store.restore_state()
    assert stats["interrupted"] == 3
    assert agent.get_task("t2")["status"] == "interrupted"
    assert "restarted" in agent.get_task("t2")["error"]
    assert execjobs.get("j2")["status"] == "interrupted"
    assert execjobs.get("j2")["pid"] is None  # process died with the app
    assert execjobs.get("j3")["status"] == "interrupted"


def test_corrupt_state_is_safe(ws):
    store.state_path().parent.mkdir(parents=True, exist_ok=True)
    store.state_path().write_text("{{{not json", encoding="utf-8")
    stats = store.restore_state()  # must not raise
    assert stats == {"tasks": 0, "jobs": 0, "interrupted": 0}


def test_missing_state_is_safe(ws):
    stats = store.restore_state()  # no file yet
    assert stats == {"tasks": 0, "jobs": 0, "interrupted": 0}


def test_private_and_unserializable_fields_stripped(ws):
    task = _mk_task("t3", "done")
    task["_cancel"] = object()
    task["_task"] = object()
    task["weird"] = object()  # not JSON-able
    agent._TASKS["t3"] = task
    assert store.save_state() is True
    raw = json.loads(store.state_path().read_text())
    saved = raw["tasks"][0]
    assert "_cancel" not in saved and "_task" not in saved
    assert isinstance(saved["weird"], str)  # coerced, not dropped silently


def test_duplicate_ids_not_double_restored(ws):
    agent._TASKS["t4"] = _mk_task("t4", "done")
    store.save_state()
    # don't clear → restore must not overwrite the live entry
    stats = store.restore_state()
    assert stats["tasks"] == 0


def test_steps_are_bounded(ws):
    task = _mk_task("t5", "done")
    task["steps"] = [{"tool": "x", "i": i} for i in range(500)]
    agent._TASKS["t5"] = task
    store.save_state()
    raw = json.loads(store.state_path().read_text())
    assert len(raw["tasks"][0]["steps"]) == store.MAX_STEPS_KEPT

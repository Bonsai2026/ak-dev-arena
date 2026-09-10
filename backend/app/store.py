"""Persistence — agent tasks + run-job history survive restarts.

The in-memory stores are lost when the sidecar restarts, so this module
snapshots them to `<workspace>/.akdev/state/ak_state.json` (atomic write)
and restores them on startup. Live PROCESSES cannot survive a restart, so
anything restored that was mid-flight is honestly marked `interrupted` —
never re-labelled as done/passed.

Never raises: persistence is best-effort and must not break the app.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from . import files

MAX_TASKS = 100
MAX_JOBS = 200
MAX_STEPS_KEPT = 100

# statuses that mean "was alive when the app died"
LIVE_TASK_STATUSES = ("queued", "running", "starting")
LIVE_JOB_STATUSES = ("queued", "running", "starting", "serving")


def state_path() -> Path:
    return files.WORKSPACE / ".akdev" / "state" / "ak_state.json"


def _serializable(d: dict[str, Any]) -> dict[str, Any]:
    """Drop private keys, coerce anything JSON can't take (Popen, Events…)."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        if k.startswith("_"):
            continue
        try:
            json.dumps(v)
            out[k] = v
        except (TypeError, ValueError):
            out[k] = str(v)
    if isinstance(out.get("steps"), list):
        out["steps"] = out["steps"][-MAX_STEPS_KEPT:]
    return out


def snapshot(tasks: dict[str, dict], jobs: dict[str, dict]) -> dict[str, Any]:
    return {
        "version": 1,
        "saved": time.time(),
        "tasks": [_serializable(t) for t in tasks.values()],
        "jobs": [_serializable(j) for j in jobs.values()],
    }


def save(tasks: dict[str, dict], jobs: dict[str, dict]) -> bool:
    """Atomic best-effort snapshot. Returns False on any I/O problem."""
    try:
        path = state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(snapshot(tasks, jobs), default=str),
                       encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:  # pragma: no cover — defensive
        return False


def load() -> dict[str, list]:
    try:
        raw = json.loads(state_path().read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {"tasks": [], "jobs": []}
        return {"tasks": list(raw.get("tasks") or []),
                "jobs": list(raw.get("jobs") or [])}
    except (OSError, json.JSONDecodeError):
        return {"tasks": [], "jobs": []}


def restore(tasks_store: dict[str, dict], jobs_store: dict[str, dict]) -> dict[str, int]:
    """Merge the snapshot back into the live stores. Mid-flight entries become
    'interrupted' (their processes died with the app). Returns counts."""
    import asyncio

    data = load()
    stats = {"tasks": 0, "jobs": 0, "interrupted": 0}
    tasks = sorted((t for t in data["tasks"] if isinstance(t, dict) and t.get("id")),
                   key=lambda t: t.get("created") or 0)[-MAX_TASKS:]
    for t in tasks:
        tid = str(t["id"])
        if tid in tasks_store:
            continue
        if t.get("status") in LIVE_TASK_STATUSES:
            t["status"] = "interrupted"
            t["error"] = "App restarted while this task was running."
            t["finished"] = t.get("finished") or time.time()
            stats["interrupted"] += 1
        t.setdefault("_cancel", asyncio.Event())
        tasks_store[tid] = t
        stats["tasks"] += 1
    jobs = sorted((j for j in data["jobs"] if isinstance(j, dict) and j.get("id")),
                  key=lambda j: j.get("created") or 0)[-MAX_JOBS:]
    for j in jobs:
        jid = str(j["id"])
        if jid in jobs_store:
            continue
        if j.get("status") in LIVE_JOB_STATUSES:
            j["status"] = "interrupted"
            j["error"] = "App restarted while this job was running."
            j["finished"] = j.get("finished") or time.time()
            j["pid"] = None
            j["proc_id"] = None
            stats["interrupted"] += 1
        jobs_store[jid] = j
        stats["jobs"] += 1
    return stats


# ------------------------------------------------------- lazy wiring --------
# Imported inside functions to avoid import cycles (agent/execjobs import
# store at call time only).

def save_state() -> bool:
    from . import agent, execjobs  # noqa: PLC0415
    return save(agent._TASKS, execjobs._jobs)  # noqa: SLF001


def restore_state() -> dict[str, int]:
    from . import agent, execjobs  # noqa: PLC0415
    return restore(agent._TASKS, execjobs._jobs)  # noqa: SLF001

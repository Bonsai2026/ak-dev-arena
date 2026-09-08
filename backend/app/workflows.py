"""Arena workflows (FreeBuff-style reusable multi-step jobs). Sequential runner.

Save once: {name, steps:[{task, profile, max_steps}]} → run anytime.
Steps execute sequentially in a background task; poll the run for progress.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from . import files

FILE = ".arena/workflows.json"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-_]{1,39}$")


class WorkflowError(Exception):
    """User-friendly workflow failure (safe to show in UI)."""


def _path(root) -> Path:
    base = files._root(root)
    p = base / FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load(root) -> dict[str, Any]:
    p = _path(root)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(root, data: dict[str, Any]) -> None:
    _path(root).write_text(json.dumps(data, indent=1), encoding="utf-8")


def list_workflows(root=None) -> list[dict[str, Any]]:
    data = _load(root)
    return [{"name": name, "steps": wf.get("steps", []), "created": wf.get("created", 0)}
            for name, wf in sorted(data.items())]


def get_workflow(name: str, root=None) -> dict[str, Any] | None:
    return _load(root).get(name)


def save_workflow(name: str, steps: list[dict[str, Any]], root=None) -> dict[str, Any]:
    name = (name or "").strip().lower()
    if not _NAME_RE.match(name):
        raise WorkflowError("Invalid name — lowercase letters, numbers, - and _ (2-40 chars).")
    if not steps or len(steps) > 20:
        raise WorkflowError("Workflows need 1-20 steps.")
    clean = []
    for s in steps:
        task = str((s or {}).get("task", "")).strip()
        if not task:
            raise WorkflowError("Every step needs a task.")
        clean.append({"task": task[:2000],
                      "profile": str(s.get("profile", "coder") or "coder")[:20],
                      "max_steps": max(1, min(int(s.get("max_steps", 6) or 6), 25))})
    data = _load(root)
    data[name] = {"steps": clean, "created": time.time()}
    _save(root, data)
    return {"name": name, "steps": clean}


def delete_workflow(name: str, root=None) -> bool:
    data = _load(root)
    if name not in data:
        return False
    del data[name]
    _save(root, data)
    return True


_RUNS: dict[str, dict[str, Any]] = {}


def _public(run: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in run.items() if not k.startswith("_")}


async def _runner(run_id: str, name: str, steps: list[dict[str, Any]],
                  model: str, root: Path) -> None:
    from . import agent as agent_mod  # deferred to avoid import cycles

    run = _RUNS[run_id]
    run["status"] = "running"
    results: list[dict[str, Any]] = []
    try:
        for i, step in enumerate(steps):
            run["current"] = i
            res = await agent_mod.run_agent(step["task"], model, step.get("max_steps", 6),
                                            work_dir=root, profile=step.get("profile", "coder"))
            results.append({"task": step["task"], "status": res.get("status"),
                            "summary": res.get("summary", "")})
            run["results"] = results
            if res.get("status") == "error":
                break
        run["status"] = "done"
    except asyncio.CancelledError:
        run["status"] = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001 — runs must never crash the server
        run["status"] = "failed"
        run["error"] = str(exc)[:300]
    finally:
        run["finished_at"] = time.time()


def start_run(name: str, model: str, root=None) -> dict[str, Any]:
    wf = get_workflow(name, root)
    if not wf:
        raise WorkflowError("Workflow not found.")
    run_id = uuid.uuid4().hex[:8]
    base = files._root(root)
    _RUNS[run_id] = {"id": run_id, "workflow": name, "status": "queued", "current": 0,
                     "total": len(wf["steps"]), "results": [], "error": "",
                     "started_at": time.time(), "finished_at": None}
    _RUNS[run_id]["_task"] = asyncio.create_task(
        _runner(run_id, name, wf["steps"], model, base))
    return _public(_RUNS[run_id])


def get_run(run_id: str) -> dict[str, Any] | None:
    run = _RUNS.get(run_id)
    return _public(run) if run else None


def reset_for_tests() -> None:
    for run in _RUNS.values():
        task = run.get("_task")
        if task:
            task.cancel()
    _RUNS.clear()

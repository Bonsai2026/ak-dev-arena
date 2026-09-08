"""Arena Manager — parallel agent jobs, each in an isolated workspace.

Jobs run as background asyncio tasks (max 3 concurrently). Each job gets its
own directory: ./workspace/jobs/<job_id>/ so parallel agents never clash.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from . import agent, files

MAX_PARALLEL = 3

_jobs: dict[str, dict[str, Any]] = {}
_tasks: dict[str, asyncio.Task] = {}
_sem = asyncio.Semaphore(MAX_PARALLEL)


def job_dir(job_id: str) -> Path:
    path = files.WORKSPACE / "jobs" / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return {k: job.get(k) for k in
            ("id", "task", "model", "status", "created_at", "finished_at", "summary", "error")}


async def _runner(job_id: str, task: str, model: str, max_steps: int) -> None:
    job = _jobs[job_id]
    job["status"] = "running"
    try:
        async with _sem:
            result = await agent.run_agent(task, model, max_steps, work_dir=job_dir(job_id))
        job["result"] = result
        job["summary"] = result.get("summary", "")
        job["status"] = "done" if result.get("status") == "complete" else result.get("status", "done")
    except asyncio.CancelledError:
        job["status"] = "cancelled"
        raise
    except Exception as exc:  # noqa: BLE001 — jobs must never crash the server
        job["status"] = "failed"
        job["error"] = str(exc)[:500]
    finally:
        job["finished_at"] = time.time()


def create_job(task: str, model: str, max_steps: int = 8) -> dict[str, Any]:
    job_id = uuid.uuid4().hex[:8]
    _jobs[job_id] = {"id": job_id, "task": task, "model": model, "status": "queued",
                     "created_at": time.time(), "finished_at": None,
                     "summary": "", "error": "", "result": None}
    _tasks[job_id] = asyncio.create_task(_runner(job_id, task, model, max_steps))
    return _public(_jobs[job_id])


def list_jobs() -> list[dict[str, Any]]:
    return [_public(j) for j in sorted(_jobs.values(), key=lambda j: j["created_at"], reverse=True)]


def get_job(job_id: str) -> dict[str, Any] | None:
    job = _jobs.get(job_id)
    if not job:
        return None
    full = _public(job)
    full["steps"] = (job.get("result") or {}).get("steps", [])
    return full


def cancel_job(job_id: str) -> bool:
    task = _tasks.get(job_id)
    job = _jobs.get(job_id)
    if not task or not job or job["status"] in ("done", "failed", "cancelled", "complete"):
        return False
    task.cancel()
    job["status"] = "cancelled"
    job["finished_at"] = time.time()
    return True


def reset_for_tests() -> None:
    for task in _tasks.values():
        task.cancel()
    _jobs.clear()
    _tasks.clear()

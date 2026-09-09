"""Execution jobs — every build/test/install/serve run is a cancellable job.

Action → command mapping (via projects adapters):
  install  → npm install / pip install -r requirements.txt
  build    → npm run build (or error if none)
  test     → npm test / pytest -q
  serve    → dev server started in background (job stays 'serving'); port+url
  stop     → stops the serving job (or any job by id)
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

from . import files, procman, projects

_jobs: dict[str, dict[str, Any]] = {}
_TASKS: dict[str, asyncio.Task] = {}
_MAX = 100


class ExecError(Exception):
    """User-friendly execution failure."""


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in job.items() if not k.startswith("_")}


def _prune() -> None:
    if len(_jobs) <= _MAX:
        return
    old = sorted((j for j in _jobs.values() if j.get("finished")),
                 key=lambda j: j["finished"] or 0)
    for j in old[: len(_jobs) - _MAX]:
        _jobs.pop(j["id"], None)


def _resolve_path(path: str | None, root: Path | None = None) -> Path:
    base_root = (root or files.WORKSPACE).resolve()  # noqa: SLF001 — same package
    if path:
        p = Path(path)
        if p.is_absolute():
            resolved = p.resolve()
            if base_root != resolved and base_root not in resolved.parents:
                raise ExecError("Path escapes the workspace.")
            base = resolved
        else:
            base = files._resolve(path, root)  # noqa: SLF001 — same package
    else:
        base = base_root
    if not base.is_dir():
        raise ExecError("Path is not a directory.")
    return base


async def _runner(job: dict[str, Any]) -> None:
    job["status"] = "running"
    try:
        cmd = job["_cmd"]
        if job["action"] == "serve":
            info = procman.start(cmd, job["_cwd"], task_id=job["id"], port=job.get("port"))
            job["pid"] = info["pid"]
            job["proc_id"] = info["id"]
            job["port"] = info.get("port") or job.get("port")
            job["url"] = projects.browser_url(job["port"]) if job["port"] else None
            job["status"] = "serving"
            job["output"] = f"Server running: pid={info['pid']} url={job['url']}"
            return
        res = await asyncio.to_thread(procman.run, cmd, job["_cwd"],
                                      timeout=job.get("timeout", 600), task_id=job["id"])
        job["exit_code"] = res["exit_code"]
        job["duration"] = res["duration"]
        job["timed_out"] = res["timed_out"]
        job["output"] = ((res.get("stdout") or "") + "\n" + (res.get("stderr") or ""))[-20000:]
        job["status"] = "passed" if res["exit_code"] == 0 else "failed"
    except asyncio.CancelledError:
        job["status"] = "cancelled"
        procman.stop_all_for_task(job["id"])
    except Exception as exc:  # noqa: BLE001 — jobs must never crash the server
        job["status"] = "failed"
        job["error"] = str(exc)[:400]
        job["output"] = str(exc)
    finally:
        job["finished"] = time.time()


def start(action: str, path: str = "", root: Path | None = None,
          port: int | None = None, timeout: int = 600) -> dict[str, Any]:
    action = (action or "").lower()
    if action not in ("install", "build", "test", "serve", "stop"):
        raise ExecError(f"Unknown action '{action}'. Use install|build|test|serve|stop.")
    if action == "stop":
        raise ExecError("'stop' needs a job id — use DELETE /api/run/{id}.")
    cwd = _resolve_path(path, root)
    project = projects.detect(cwd)
    cmd: list[str] | None = None
    if action == "install":
        cmd = projects.install_cmd(project)
    elif action == "build":
        cmd = projects.build_cmd(project)
    elif action == "test":
        cmd = projects.test_cmd(project)
    elif action == "serve":
        port = port or procman.find_free_port()
        cmd = projects.dev_cmd(project, port)
    if not cmd:
        raise ExecError(
            f"No {action} command for this project (type={project['type']}, "
            f"scripts={project['scripts'] or 'none'}).")
    job_id = uuid.uuid4().hex[:8]
    job: dict[str, Any] = {
        "id": job_id, "action": action, "path": str(cwd), "project_type": project["type"],
        "status": "queued", "created": time.time(), "finished": None,
        "exit_code": None, "duration": None, "timed_out": False,
        "output": "", "error": "", "pid": None, "proc_id": None, "port": port,
        "url": None, "cmd": " ".join(cmd), "_cmd": cmd, "_cwd": cwd,
    }
    _jobs[job_id] = job
    _TASKS[job_id] = asyncio.get_running_loop().create_task(_runner(job))
    _prune()
    return _public(job)


def get(job_id: str) -> dict[str, Any] | None:
    job = _jobs.get(job_id)
    return _public(job) if job else None


def list_jobs() -> list[dict[str, Any]]:
    return [_public(j) for j in sorted(_jobs.values(), key=lambda j: j["created"], reverse=True)]


def cancel(job_id: str) -> bool:
    job = _jobs.get(job_id)
    if not job or job["status"] in ("passed", "failed", "cancelled"):
        return False
    if job["status"] == "serving" and job.get("proc_id"):
        procman.stop(job["proc_id"])
        job["status"] = "stopped"
        job["finished"] = time.time()
        return True
    task = _TASKS.get(job_id)
    if task:
        task.cancel()
    job["status"] = "cancelled"
    job["finished"] = time.time()
    return True


def reset_for_tests() -> None:
    for t in _TASKS.values():
        t.cancel()
    for j in _jobs.values():
        if j.get("proc_id"):
            # best-effort cleanup of any started servers
            pass
    _jobs.clear()
    _TASKS.clear()

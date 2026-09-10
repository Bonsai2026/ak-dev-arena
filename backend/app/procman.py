"""AK Dev Studio Process Manager.

Tracks every process the agent/tools start (PID, command, cwd, parent task,
start time, port) so nothing becomes an orphan:
  - blocking `run()` with timeout, exit-code capture
  - `start()` long-lived servers with PID + auto port discovery
  - `stop()` / `stop_all_for_task()` for cancellation & cleanup
  - `list()` / `orphans()` for the resource panel

No shell is ever used: commands are token lists (no injection).
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from . import files

TIMEOUT_DEFAULT = 120
_MAX_HISTORY = 200

_procs: dict[str, dict[str, Any]] = {}


class ProcError(Exception):
    """User-friendly process failure."""


def find_free_port(preferred: int = 0) -> int:
    """Ask the OS for a free TCP port (0 = any)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", preferred))
        return s.getsockname()[1]


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) == 0


def _popen_kwargs() -> dict[str, Any]:
    """Every tracked process gets its own session/group so stopping it also
    kills its whole subtree (npm → sh → python) — no orphans."""
    if os.name == "posix":
        return {"start_new_session": True}
    return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # win32


def _kill_tree(proc: subprocess.Popen, force: bool = False,
               pgid: int | None = None) -> None:
    """Terminate the WHOLE process group (POSIX) or tree (Windows).

    pgid is captured at spawn: after the leader exits, os.getpgid() is no
    longer possible, but the group (and its children) may still be alive.
    """
    try:
        if os.name == "posix":
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.killpg(pgid if pgid is not None else os.getpgid(proc.pid), sig)
        else:
            flags = "/F" if force else ""
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", flags],
                           capture_output=True, timeout=15, check=False)
    except (ProcessLookupError, PermissionError):
        pass  # already dead


def _record(proc: subprocess.Popen, command: list[str], cwd: Path,
            task_id: str | None, port: int | None) -> dict[str, Any]:
    pid = proc.pid
    try:
        pgid = os.getpgid(pid) if os.name == "posix" else None
    except (ProcessLookupError, PermissionError):
        pgid = None
    entry: dict[str, Any] = {
        "id": f"p{uuid.uuid4().hex[:8]}",
        "pid": pid,
        "command": " ".join(command)[:300],
        "argv": command,
        "cwd": str(cwd),
        "task_id": task_id,
        "port": port,
        "started": time.time(),
        "status": "running",
        "proc": proc,
        "_pgid": pgid,
    }
    _procs[entry["id"]] = entry
    return entry


def run(command: list[str], cwd: Path, timeout: int = TIMEOUT_DEFAULT,
        task_id: str | None = None) -> dict[str, Any]:
    """Run a command to completion with timeout + exit code. Returns evidence."""
    if not command:
        raise ProcError("Empty command.")
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    started = time.time()
    try:
        proc = subprocess.Popen(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, shell=False, **_popen_kwargs(),
        )
    except FileNotFoundError as exc:
        raise ProcError(f"Executable not found: {command[0]}") from None
    entry = _record(proc, command, cwd, task_id, None)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc, force=True)
        out, err = proc.communicate()
        entry["status"] = "timeout"
        duration = round(time.time() - started, 2)
        return {"exit_code": -1, "stdout": (out or "")[-20000:],
                "stderr": (err or "")[-20000:], "duration": duration,
                "timed_out": True, "pid": proc.pid}
    entry["status"] = "exited"
    entry["exit_code"] = proc.returncode
    return {
        "exit_code": proc.returncode,
        "stdout": (out or "")[-20000:],
        "stderr": (err or "")[-20000:],
        "duration": round(time.time() - started, 2),
        "timed_out": False,
        "pid": proc.pid,
    }


def start(command: list[str], cwd: Path, task_id: str | None = None,
          port: int | None = None) -> dict[str, Any]:
    """Start a long-lived server process (npm run dev, uvicorn, ...)."""
    if not command:
        raise ProcError("Empty command.")
    cwd = Path(cwd)
    cwd.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.Popen(
            command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, shell=False, bufsize=1, **_popen_kwargs(),
        )
    except FileNotFoundError as exc:
        raise ProcError(f"Executable not found: {command[0]}") from None
    entry = _record(proc, command, cwd, task_id, port)
    return _public(entry)


def stop(proc_id: str) -> bool:
    entry = _procs.get(proc_id)
    if not entry or entry["status"] != "running":
        return False
    proc: subprocess.Popen = entry["proc"]
    pgid = entry.get("_pgid")
    try:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _kill_tree(proc, force=True, pgid=pgid)
            proc.wait(timeout=3)
    except Exception:  # noqa: BLE001, S110 — already dead
        pass
    # Parent may have exited but left children — sweep the whole tree.
    _kill_tree(proc, force=True, pgid=pgid)
    entry["status"] = "stopped"
    return True


def stop_by_port(port: int) -> bool:
    for entry in list(_procs.values()):
        if entry.get("port") == port:
            return stop(entry["id"])
    return False


def stop_all_for_task(task_id: str) -> int:
    n = 0
    for entry in list(_procs.values()):
        if entry.get("task_id") == task_id and entry["status"] == "running":
            if stop(entry["id"]):
                n += 1
    return n


def get(proc_id: str) -> dict[str, Any] | None:
    entry = _procs.get(proc_id)
    return _public(entry) if entry else None


def list_processes() -> list[dict[str, Any]]:
    _prune_history()
    return [_public(e) for e in sorted(
        _procs.values(), key=lambda e: e["started"], reverse=True)]


def orphans() -> list[dict[str, Any]]:
    """Processes still running after their task finished (leaks)."""
    return [_public(e) for e in _procs.values()
            if e["status"] == "running" and not e.get("task_id")]


def _public(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k not in ("proc", "argv")}


def clear_finished() -> int:
    """Drop finished entries (keeps running ones)."""
    done = [k for k, e in _procs.items()
            if e["status"] in ("exited", "stopped", "timeout")]
    for k in done:
        del _procs[k]
    return len(done)


def _prune_history() -> None:
    """Bounded memory: finished entries beyond MAX_HISTORY are dropped."""
    finished = [k for k, e in _procs.items()
                if e.get("status") in ("exited", "stopped", "timeout")]
    if len(finished) <= _MAX_HISTORY:
        return
    finished.sort(key=lambda k: _procs[k].get("started", 0))
    for k in finished[: len(finished) - _MAX_HISTORY]:
        del _procs[k]


def reset_for_tests() -> None:
    for entry in list(_procs.values()):
        if entry["status"] == "running":
            try:
                entry["proc"].kill()
            except Exception:  # noqa: BLE001, S110
                pass
    _procs.clear()

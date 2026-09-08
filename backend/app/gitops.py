"""Arena git checkpoints — safe undo for everything the AI touches.

Convention: Arena's own commits start with "arena:". `undo()` only ever
reverts Arena commits, never the user's own history.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from . import files

ARENA_PREFIX = "arena:"
_TIMEOUT = 30


class GitError(Exception):
    """User-friendly git failure (safe to show in UI)."""


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=_TIMEOUT,
    )


def _repo_root(path: str = "", root: Path | None = None) -> Path:
    target = files._resolve(path, root)  # noqa: SLF001 — same package
    return target if target.is_dir() else target.parent


def is_repo(path: str = "", root: Path | None = None) -> bool:
    return (_repo_root(path, root) / ".git").exists()


def init(path: str = "", root: Path | None = None) -> dict:
    repo = _repo_root(path, root)
    proc = _run(["init"], repo)
    if proc.returncode != 0:
        raise GitError(f"git init failed: {proc.stderr.strip()[:200]}")
    return {"initialized": True, "path": str(repo)}


def status(path: str = "", root: Path | None = None) -> dict:
    repo = _repo_root(path, root)
    if not is_repo(path, root):
        return {"is_repo": False, "branch": "", "clean": True, "changed": [], "untracked": []}
    branch = _run(["rev-parse", "--abbrev-ref", "HEAD"], repo).stdout.strip()
    porcelain = _run(["status", "--porcelain"], repo).stdout.splitlines()
    changed = [line[3:] for line in porcelain if not line.startswith("??")]
    untracked = [line[3:] for line in porcelain if line.startswith("??")]
    return {"is_repo": True, "branch": branch or "main", "clean": not porcelain,
            "changed": changed[:100], "untracked": untracked[:100]}


def checkpoint(path: str = "", message: str = "arena: checkpoint",
               root: Path | None = None) -> dict:
    repo = _repo_root(path, root)
    if not is_repo(path, root):
        init(path, root)
    _run(["add", "-A"], repo)
    msg = message if message.startswith(ARENA_PREFIX) else f"{ARENA_PREFIX} {message}"
    proc = _run(["-c", "user.name=arena", "-c", "user.email=arena@local",
                 "commit", "-m", msg], repo)
    if proc.returncode != 0:
        if "nothing to commit" in (proc.stdout + proc.stderr):
            return {"hash": None, "message": "Nothing to commit — working tree clean."}
        raise GitError(f"Commit failed: {proc.stderr.strip()[:200]}")
    commit_hash = _run(["rev-parse", "--short", "HEAD"], repo).stdout.strip()
    return {"hash": commit_hash, "message": msg}


def undo(path: str = "", root: Path | None = None) -> dict:
    repo = _repo_root(path, root)
    if not is_repo(path, root):
        raise GitError("Not a git repository.")
    last_msg = _run(["log", "-1", "--pretty=%s"], repo).stdout.strip()
    if not last_msg.startswith(ARENA_PREFIX):
        raise GitError("Last commit is not an Arena checkpoint — refusing to undo user history.")
    proc = _run(["reset", "--hard", "HEAD~1"], repo)
    if proc.returncode != 0:
        raise GitError(f"Undo failed: {proc.stderr.strip()[:200]}")
    return {"undone": True, "reverted": last_msg}

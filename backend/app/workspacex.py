"""Workspace manager — clean local layout + safe cleanup + storage usage.

Layout under ./workspace:
    .akdev/
      temp/      agent scratch files (auto-cleaned)
      cache/     reusable caches
      logs/      task logs
      artifacts/ deliverables (builds, reports, screenshots)
      runtime/   dev servers, sockets, pid files

User projects stay in the workspace root (or ./builds for generated apps).
Cleanup NEVER touches user files — only .akdev subdirs.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from . import files

AKDEV = ".akdev"
SUBDIRS = ("temp", "cache", "logs", "artifacts", "runtime")

DEFAULT_MAX_AGE_HOURS = 24
DEFAULT_MAX_BYTES = 200 * 1024 * 1024  # 200 MB of .akdev is plenty


class WorkspaceError(Exception):
    """User-friendly workspace failure."""


def root() -> Path:
    return files._root(None)  # noqa: SLF001 — same package


def _akdev() -> Path:
    base = root()
    d = base / AKDEV
    for sub in SUBDIRS:
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def ensure() -> dict[str, str]:
    """Create the standard layout. Returns dirs (safe to call anytime)."""
    d = _akdev()
    return {sub: str(d / sub) for sub in SUBDIRS}


def task_dir(task_id: str, sub: str = "logs") -> Path:
    d = _akdev() / sub / "tasks" / task_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def usage() -> dict[str, Any]:
    base = root()
    akdev = base / AKDEV
    total = 0
    by_dir: dict[str, int] = {}
    if akdev.is_dir():
        for child in akdev.iterdir():
            if child.is_dir():
                size = _dir_size(child)
                by_dir[child.name] = size
                total += size
    return {"workspace": str(base), "akdev_bytes": total,
            "by_dir": by_dir,
            "limit_bytes": DEFAULT_MAX_BYTES,
            "user_files_bytes": _dir_size(base) - total}


def _dir_size(path: Path) -> int:
    try:
        return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    except OSError:
        return 0


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


def cleanup(max_age_hours: int = DEFAULT_MAX_AGE_HOURS,
            max_bytes: int = DEFAULT_MAX_BYTES) -> dict[str, Any]:
    """Delete OLD .akdev content only. Never touches user projects."""
    ensure()
    akdev = root() / AKDEV
    cutoff = time.time() - max(max_age_hours, 1) * 3600
    removed_bytes = 0
    removed_files = 0
    scanned_bytes = 0
    # 1. age-based (temp/logs/artifacts/runtime — NOT cache by default)
    for sub in ("temp", "logs", "artifacts", "runtime"):
        path = akdev / sub
        if not path.is_dir():
            continue
        for p in sorted(path.rglob("*"), reverse=True):
            try:
                if p.is_file() and _mtime(p) < cutoff:
                    removed_bytes += p.stat().st_size
                    removed_files += 1
                    p.unlink()
                elif p.is_dir() and not any(p.iterdir()):
                    p.rmdir()
            except OSError:
                continue
    # 2. total-size cap (oldest first across .akdev)
    if max_bytes > 0:
        current = usage()
        excess = current["akdev_bytes"] - max_bytes
        if excess > 0:
            all_files: list[tuple[float, int, Path]] = []
            for p in akdev.rglob("*"):
                if p.is_file():
                    try:
                        all_files.append((_mtime(p), p.stat().st_size, p))
                    except OSError:
                        continue
            freed = 0
            for _, size, p in sorted(all_files):
                if freed >= excess:
                    break
                try:
                    p.unlink()
                    removed_bytes += size
                    removed_files += 1
                    freed += size
                except OSError:
                    continue
    return {"removed_files": removed_files, "removed_bytes": removed_bytes,
            "usage": usage()}


def reset_for_tests() -> None:
    pass  # nothing global to reset

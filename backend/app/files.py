"""Arena file tools — workspace-scoped file ops with diff preview.

Every function is rooted in a workspace directory (default: ./workspace).
Path traversal outside the root is blocked. Used by Code Mode, Agent Mode,
Manager jobs and Build Mode.
"""

from __future__ import annotations

import difflib
import os
from pathlib import Path

from .config import REPO_ROOT

WORKSPACE = Path(os.environ.get("ARENA_WORKSPACE", REPO_ROOT / "workspace"))
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
               "build", "target", ".next", ".turbo", "out", "coverage"}
MAX_READ_BYTES = 500_000
MAX_HITS = 100
MAX_SCAN_FILES = 2000


class FileError(Exception):
    """User-friendly file failure (safe to show in UI)."""


def _root(root: Path | None) -> Path:
    base = (root or WORKSPACE).resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _resolve(path: str, root: Path | None = None) -> Path:
    base = _root(root)
    rel = (path or "").strip().lstrip("/").replace("\\", "/")
    target = (base / rel).resolve() if rel else base
    if target != base and base not in target.parents:
        raise FileError("Path escapes the workspace.")
    return target


def _rel(target: Path, base: Path) -> str:
    return target.relative_to(base).as_posix()


def list_files(path: str = "", root: Path | None = None) -> list[dict]:
    base = _root(root)
    target = _resolve(path, base)
    if not target.is_dir():
        raise FileError("Not a directory.")
    entries = []
    for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
        if child.name in IGNORE_DIRS or child.name.startswith("."):
            continue
        entries.append({
            "name": child.name,
            "path": _rel(child, base),
            "type": "dir" if child.is_dir() else "file",
            "size": child.stat().st_size if child.is_file() else 0,
        })
        if len(entries) >= 500:
            break
    return entries


def read_file(path: str, root: Path | None = None) -> dict:
    base = _root(root)
    target = _resolve(path, base)
    if not target.is_file():
        raise FileError("File not found.")
    raw = target.read_bytes()
    if len(raw) > MAX_READ_BYTES:
        raise FileError("File too large to open (>500KB).")
    if b"\x00" in raw[:8192]:
        raise FileError("Binary file — cannot display as text.")
    return {"path": _rel(target, base), "content": raw.decode("utf-8", errors="replace"),
            "size": len(raw)}


def write_file(path: str, content: str, root: Path | None = None) -> dict:
    base = _root(root)
    target = _resolve(path, base)
    if not path.strip():
        raise FileError("Empty path.")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode("utf-8")
    target.write_bytes(data)
    return {"path": _rel(target, base), "bytes": len(data)}


def search(query: str, path: str = "", root: Path | None = None) -> list[dict]:
    if not query.strip():
        raise FileError("Empty search query.")
    base = _root(root)
    start = _resolve(path, base)
    hits, scanned = [], 0
    stack = [start if start.is_dir() else start.parent]
    while stack and len(hits) < MAX_HITS and scanned < MAX_SCAN_FILES:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.name in IGNORE_DIRS or child.name.startswith("."):
                continue
            if child.is_dir():
                stack.append(child)
            elif child.is_file():
                scanned += 1
                try:
                    if child.stat().st_size > 512_000:
                        continue
                    raw = child.read_bytes()
                    if b"\x00" in raw[:4096]:
                        continue
                    for lineno, line in enumerate(raw.decode("utf-8", errors="replace").splitlines(), 1):
                        if query in line:
                            hits.append({"path": _rel(child, base), "line": lineno,
                                         "text": line.strip()[:300]})
                            if len(hits) >= MAX_HITS:
                                break
                except OSError:
                    continue
    return hits


def make_diff(path: str, old_text: str, new_text: str) -> str:
    diff = difflib.unified_diff(
        old_text.splitlines(), new_text.splitlines(),
        fromfile=f"a/{path}", tofile=f"b/{path}", lineterm="",
    )
    return "\n".join(diff)


def delete_file(path: str, root: Path | None = None) -> dict:
    """Delete a file (or empty directory) INSIDE the workspace only."""
    base = _root(root)
    target = _resolve(path, root)
    if target == base:
        raise FileError("Refusing to delete the workspace root.")
    if target.name == ".akrules":
        raise FileError("Use the instructions UI to remove project rules.")
    if target.is_file():
        target.unlink()
        return {"path": _rel(target, base), "deleted": True, "type": "file"}
    if target.is_dir():
        if any(target.iterdir()):
            raise FileError("Directory is not empty — delete files inside first.")
        target.rmdir()
        return {"path": _rel(target, base), "deleted": True, "type": "dir"}
    raise FileError("Path not found.")


def apply_edit(path: str, old_text: str, new_text: str, root: Path | None = None) -> dict:
    base = _root(root)
    current = read_file(path, base)["content"]
    if not old_text:
        raise FileError("old_text is empty — nothing to replace.")
    if old_text not in current:
        raise FileError("old_text not found in file — it may have changed.")
    updated = current.replace(old_text, new_text, 1)
    write_file(path, updated, base)
    return {"path": path, "diff": make_diff(path, current, updated), "applied": True}

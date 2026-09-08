"""Arena todos (Manus-style task lists). Stored in <root>/.arena/todos.json."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from . import files

FILE = ".arena/todos.json"


class TodoError(Exception):
    """User-friendly todo failure (safe to show in UI)."""


def _path(root) -> Path:
    base = files._root(root)
    p = base / FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load(root) -> list[dict[str, Any]]:
    p = _path(root)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8")) or []
    except (OSError, json.JSONDecodeError):
        return []


def _save(root, items: list[dict[str, Any]]) -> None:
    _path(root).write_text(json.dumps(items, indent=1), encoding="utf-8")


def list_todos(root=None) -> list[dict[str, Any]]:
    return _load(root)


def create(text: str, job: str | None = None, root=None) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise TodoError("Empty todo.")
    items = _load(root)
    item = {"id": uuid.uuid4().hex[:6], "text": text[:500], "done": False,
            "job": job, "ts": time.time()}
    items.append(item)
    _save(root, items)
    return item


def set_done(todo_id: str, done: bool = True, root=None) -> dict[str, Any]:
    items = _load(root)
    for it in items:
        if it["id"] == todo_id:
            it["done"] = bool(done)
            _save(root, items)
            return it
    raise TodoError("Todo not found.")


def remove(todo_id: str, root=None) -> bool:
    items = _load(root)
    kept = [it for it in items if it["id"] != todo_id]
    if len(kept) == len(items):
        return False
    _save(root, kept)
    return True


def clear_done(root=None) -> int:
    items = _load(root)
    kept = [it for it in items if not it["done"]]
    _save(root, kept)
    return len(items) - len(kept)

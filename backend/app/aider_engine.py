"""Arena repo-map engine — Aider's real tree-sitter maps when installed.

Optional dep: pip install aider-chat  (best on Python 3.11/3.12)
Without it, a smart fallback tree is returned — the endpoint never breaks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import files


def is_available() -> bool:
    try:
        import aider.repomap  # noqa: F401
        return True
    except ImportError:
        return False


def _fallback_tree(start: Path, cap: int = 400) -> str:
    lines = [f"Workspace tree: {start.name}/"]
    count = 0
    for p in sorted(start.rglob("*")):
        if count >= cap:
            lines.append("... (truncated)")
            break
        rel = p.relative_to(start).as_posix()
        if any(part in files.IGNORE_DIRS or part.startswith(".") for part in rel.split("/")):
            continue
        if p.is_file():
            try:
                size = p.stat().st_size
            except OSError:
                continue
            lines.append(f"  {rel} ({size}b)")
            count += 1
    return "\n".join(lines)


def repo_map(path: str = "", root: Path | None = None, max_chars: int = 12000) -> dict[str, Any]:
    base = files._root(root)
    target = files._resolve(path, root)
    start = target if target.is_dir() else target.parent
    if is_available():
        try:
            from aider.models import Model
            from aider.repomap import RepoMap

            others: list[str] = []
            for p in sorted(start.rglob("*")):
                if len(others) >= 300:
                    break
                if not p.is_file():
                    continue
                rel = p.relative_to(start).as_posix()
                if any(part in files.IGNORE_DIRS or part.startswith(".") for part in rel.split("/")):
                    continue
                try:
                    if p.stat().st_size > 200_000:
                        continue
                except OSError:
                    continue
                others.append(str(p))
            rm = RepoMap(Model("gpt-4o"), root=str(start))
            text = (rm.get_repo_map([], others) or "").strip()
            if text:
                return {"map": text[:max_chars], "engine": "aider", "files": len(others)}
        except Exception:  # noqa: BLE001 — any aider hiccup → fallback
            pass
    return {"map": _fallback_tree(start)[:max_chars], "engine": "fallback", "files": 0,
            "hint": None if is_available() else "Install Aider for tree-sitter maps: pip install aider-chat"}

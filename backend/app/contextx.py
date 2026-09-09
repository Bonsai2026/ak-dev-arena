"""Arena context engine (Cursor/Claude/Codex-style): chat instructions + rules.

- Global "chat instructions" (like Cursor rules / Claude CLAUDE.md / Codex AGENTS.md)
  — stored in config.local.yaml (git-ignored), editable from the app.
- .akrules project rules (workspace root) — like .cursorrules.
- @path/to/file, @dir/ → contents injected as context (truncated).
- @codebase → workspace file tree injected.

Both instruction layers are injected as the system prompt everywhere the LLM
is used: Chat, Agent, Code Composer, Build and Review.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml

from . import files
from .config import REPO_ROOT

MENTION_RE = re.compile(r"(?<![\w/])@([A-Za-z0-9_.\-/]+)")
MAX_ATTACH = 5
MAX_CHARS = 6000
MAX_INSTRUCTIONS_CHARS = 20_000


def _local_path() -> Path:
    override = os.environ.get("ARENA_LOCAL_CONFIG")
    return Path(override) if override else REPO_ROOT / "config.local.yaml"


def load_global_instructions() -> str:
    """User-level instructions (Cursor/Claude-style) — secret-free, git-ignored."""
    path = _local_path()
    if not path.exists():
        return ""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — corrupt local config → treat as empty
        return ""
    return str(data.get("arena_instructions", "") or "")[:MAX_INSTRUCTIONS_CHARS]


def save_global_instructions(text: str) -> str:
    """Persist global instructions, preserving any API keys already stored."""
    text = (text or "").strip()[:MAX_INSTRUCTIONS_CHARS]
    path = _local_path()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 — corrupt local config → start fresh
            data = {}
    if text:
        data["arena_instructions"] = text
    else:
        data.pop("arena_instructions", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # non-POSIX filesystem; file is still git-ignored
    return text


def load_rules(root=None) -> str:
    try:
        return files.read_file(".akrules", root=root)["content"][:8000]
    except files.FileError:
        return ""


def save_rules(content: str, root=None) -> str:
    """Save project rules to .akrules (workspace root, git-ignored via workspace/*)."""
    files.write_file(".akrules", (content or "").strip()[:8000], root=root)
    return load_rules(root)


def delete_rules(root=None) -> bool:
    base = files._root(root)  # noqa: SLF001 — same package
    target = base / ".akrules"
    if target.is_file():
        target.unlink()
        return True
    return False


def rules_summary(root=None) -> dict[str, Any]:
    """Instructions state, safe for the API (no secrets, no keys)."""
    global_text = load_global_instructions()
    project_text = load_rules(root)
    return {
        "global": global_text,
        "project": project_text,
        "global_found": bool(global_text),
        "project_found": bool(project_text),
    }


def _system_block(root=None) -> str:
    parts: list[str] = []
    global_text = load_global_instructions()
    if global_text:
        parts.append(f"User instructions — always follow:\n{global_text}")
    project_text = load_rules(root)
    if project_text:
        parts.append(f"Project rules (.akrules) — always follow:\n{project_text}")
    return "\n\n".join(parts)


def _tree_text(root, cap_files: int = 250) -> str:
    base = files._root(root)
    lines, n = [], 0
    for p in sorted(base.rglob("*")):
        if n >= cap_files:
            break
        if not p.is_file():
            continue
        rel = p.relative_to(base).as_posix()
        if any(part in files.IGNORE_DIRS or part.startswith(".") for part in rel.split("/")):
            continue
        lines.append(rel)
        n += 1
    return "\n".join(lines) or "(empty workspace)"


def _attach(token: str, root) -> str | None:
    tok = token.rstrip("/")
    if tok == "codebase":
        return f"[context @codebase — file tree]\n{_tree_text(root)}"
    try:
        target = files._resolve(tok, root)
    except files.FileError:
        return f"[context @{tok} — not found]"
    if target.is_dir():
        try:
            entries = files.list_files(tok, root=root)
        except files.FileError as exc:
            return f"[context @{tok} — {exc}]"
        names = [e["name"] + ("/" if e["type"] == "dir" else "") for e in entries[:100]]
        return f"[context @{tok}/]\n" + "\n".join(names)
    try:
        content = files.read_file(tok, root=root)["content"][:MAX_CHARS]
    except files.FileError as exc:
        return f"[context @{tok} — {exc}]"
    return f"[context @{tok}]\n{content}"


def resolve_mentions(text: str, root=None) -> tuple[str, list[str]]:
    tokens: list[str] = []
    for m in MENTION_RE.finditer(text or ""):
        tok = m.group(1).rstrip("/")
        if tok and tok not in tokens:
            tokens.append(tok)
    tokens = tokens[:MAX_ATTACH]
    if not tokens:
        return text, []
    blocks = [_attach(t, root) for t in tokens]
    return text + "\n\n" + "\n\n".join(b for b in blocks if b), tokens


def inject_context(messages: list[dict[str, Any]], root=None) -> list[dict[str, Any]]:
    out = []
    for msg in messages:
        role, content = msg.get("role"), msg.get("content", "")
        if role == "user" and isinstance(content, str):
            content, _ = resolve_mentions(content, root)
        out.append({**msg, "content": content})
    block = _system_block(root)
    if block:
        if out and out[0].get("role") == "system":
            out[0] = {**out[0], "content": f"{block}\n\n{out[0]['content']}"}
        else:
            out.insert(0, {"role": "system", "content": block})
        return out
    return out

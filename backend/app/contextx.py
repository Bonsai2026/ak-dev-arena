"""Arena context engine (Cursor-style): @-mentions + .akrules project rules.

- @path/to/file, @dir/ → contents injected as context (truncated).
- @codebase → workspace file tree injected.
- .akrules (workspace root) → auto system-prompt rules (like .cursorrules).
"""

from __future__ import annotations

import re
from typing import Any

from . import files

MENTION_RE = re.compile(r"(?<![\w/])@([A-Za-z0-9_.\-/]+)")
MAX_ATTACH = 5
MAX_CHARS = 6000


def load_rules(root=None) -> str:
    try:
        return files.read_file(".akrules", root=root)["content"][:8000]
    except files.FileError:
        return ""


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
    rules = load_rules(root)
    if rules:
        block = f"Project rules (.akrules) — always follow:\n{rules}"
        if out and out[0].get("role") == "system":
            out[0] = {**out[0], "content": f"{block}\n\n{out[0]['content']}"}
        else:
            out.insert(0, {"role": "system", "content": block})
    return out

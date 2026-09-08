"""Arena slash commands (Claude-Code-style): /commit /review /test /explain + custom.

Custom commands: drop a markdown file in <workspace>/.arena/commands/<name>.md
(use {args} inside) and it becomes /<name> instantly.
"""

from __future__ import annotations

import subprocess
from typing import Any

from . import files, gitops, llm, review as review_mod

COMMANDS_DIR = ".arena/commands"

BUILTINS = {
    "commit": "Commit workspace changes with an AI message.",
    "review": "AI-review the current workspace diff.",
    "test": "Run backend tests and show results.",
    "explain": "Explain a file. Usage: /explain <path>",
    "help": "List all commands.",
}


def list_commands(root=None) -> list[dict[str, Any]]:
    out = [{"name": f"/{k}", "description": v, "builtin": True} for k, v in BUILTINS.items()]
    base = files._root(root)
    folder = base / COMMANDS_DIR
    if folder.is_dir():
        for f in sorted(folder.glob("*.md")):
            first = (f.read_text(encoding="utf-8", errors="replace").splitlines() or [""])[0][:120]
            out.append({"name": f"/{f.stem}", "description": first or "Custom command.",
                        "builtin": False})
    return out


def _git_diff(root) -> str:
    base = files._root(root)
    if not (base / ".git").exists():
        return ""
    proc = subprocess.run(["git", "diff", "HEAD"], cwd=base, capture_output=True,
                          text=True, timeout=20)
    return (proc.stdout or "")[:12000]


async def run_slash(command: str, args: str, model: str, root=None) -> dict[str, Any]:
    name = (command or "").strip().lstrip("/").split()
    name = name[0].lower() if name else "help"
    args = (args or "").strip()

    if name == "help":
        lines = [f"{c['name']} — {c['description']}" for c in list_commands(root)]
        return {"command": "/help", "output": "\n".join(lines)}

    if name == "commit":
        diff = _git_diff(root)
        if not diff:
            return {"command": "/commit", "output": "No changes to commit."}
        resp = await llm.chat_completion(model, [
            {"role": "system", "content": "Write ONE conventional-commit line (e.g. 'feat: ...'). Only the line."},
            {"role": "user", "content": f"DIFF:\n{diff}"}], max_tokens=200, temperature=0.2)
        lines = (resp.get("content") or "").strip().splitlines()
        msg = lines[0][:150] if lines else "arena: update"
        cp = gitops.checkpoint("", msg, root=root)
        return {"command": "/commit", "output": f"{msg}\n[{cp.get('hash') or 'clean'}]"}

    if name == "review":
        diff = _git_diff(root)
        if not diff:
            return {"command": "/review", "output": "No changes to review."}
        res = await review_mod.review_diff(diff, model)
        lines = [res.get("summary", "")] + [
            f"- [{f['severity']}] {f['file']}:{f['line']} {f['message']}"
            for f in res.get("findings", [])]
        return {"command": "/review", "output": "\n".join(lines)}

    if name == "test":
        from .config import REPO_ROOT

        proc = subprocess.run(["python", "-m", "pytest", "backend/tests", "-q"],
                              cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
        tail = ((proc.stdout or "") + (proc.stderr or ""))[-3000:]
        return {"command": "/test", "output": f"exit={proc.returncode}\n{tail}"}

    if name == "explain":
        if not args:
            return {"command": "/explain", "output": "Usage: /explain <path>"}
        try:
            content = files.read_file(args, root=root)["content"][:8000]
        except files.FileError as exc:
            return {"command": "/explain", "output": f"Error: {exc}"}
        resp = await llm.chat_completion(model, [
            {"role": "system", "content": "Explain this file briefly: purpose, key parts, how to use."},
            {"role": "user", "content": content}], max_tokens=800, temperature=0.3)
        return {"command": "/explain", "output": resp.get("content", "")}

    base = files._root(root)
    tmpl = base / COMMANDS_DIR / f"{name}.md"
    if not tmpl.is_file():
        return {"command": f"/{name}", "output": "Unknown command. Try /help."}
    prompt = tmpl.read_text(encoding="utf-8", errors="replace").replace("{args}", args)
    resp = await llm.chat_completion(
        model, [{"role": "user", "content": prompt}], max_tokens=1500, temperature=0.5)
    return {"command": f"/{name}", "output": resp.get("content", "")}

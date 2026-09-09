"""Arena Agent — plan → act → verify loop (Manus/Claude-style + profiles).

The LLM replies with ONE JSON object per step:
  {"thought": "...", "tool": "<tool>|done", "args": {...}}

Profiles (FreeBuff-style): coder / researcher / reviewer / planner — each with
its own system prompt + restricted toolset.
Permissions (OpenCode-style): config.yaml -> permissions: {tool: allow|ask|deny}
Hooks (Claude-Code-style): config.yaml -> hooks: {pre_tool, post_tool} shell cmds.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from . import config as config_mod
from . import contextx, files, llm, mcp_client, profiles, todos, web

BASE_SYSTEM = """You are the AK Dev Arena agent. Solve the user's task step by step.
Reply with EXACTLY ONE JSON object per step, no other text:
{"thought": "short reasoning", "tool": "<tool>", "args": {...}}"""

TOOL_DOCS = {
    "list_files": 'list_files {"path": "optional subdir"}',
    "read_file": 'read_file {"path": "file"}',
    "write_file": 'write_file {"path": "file", "content": "full new content"}',
    "search": 'search {"q": "text"}',
    "run": 'run {"cmd": "allow-listed shell command"}',
    "web_search": 'web_search {"q": "query", "max_results": 5}',
    "web_fetch": 'web_fetch {"url": "https://..."}',
    "todo": 'todo {"action": "add|done|list", "text": "...", "id": "..."}',
    "mcp": 'mcp {"server": "id", "tool": "name", "args": {...}}',
    "done": 'done {"summary": "what was accomplished"}',
}

# Token-based command safety: only known-safe base commands, with sub-command
# allow-lists for multi-purpose tools (git/npm/python). File-reading commands
# (ls/cat) are constrained to paths inside the workspace. Everything else —
# delete, install, push, shell pipes, redirects — is rejected outright.
ALLOWED_BASES = {
    "ls", "cat", "echo", "pwd", "git", "pytest", "npm", "node",
    "python", "python3", "dir", "type",
}
GIT_SUBS = {"status", "log", "diff"}
NPM_SUBS = {"test", "run"}
PYMOD_SUBS = {"pytest"}
READ_ONLY_BASES = {"ls", "cat", "dir", "type"}

PLAN_PROMPT = """You are a planner. Output EXACTLY ONE JSON object and nothing else:
{"steps": ["concrete step 1", "concrete step 2", ...]} — 3 to 10 steps."""


class AgentError(Exception):
    """User-friendly agent failure (safe to show in UI)."""


ASK_LOG: list[dict[str, Any]] = []
APPROVALS: dict[str, float] = {}  # tool -> expiry timestamp


def default_permissions() -> dict[str, str]:
    return {t: "allow" for t in TOOL_DOCS if t != "done"}


def effective_permissions(overrides: dict[str, str] | None = None) -> dict[str, str]:
    perms = default_permissions()
    try:
        cfg = config_mod.get_config().permissions or {}
    except Exception:  # noqa: BLE001 — config failure → safe defaults
        cfg = {}
    perms.update({str(k).lower(): str(v).lower() for k, v in cfg.items()})
    if overrides:
        perms.update({str(k).lower(): str(v).lower() for k, v in overrides.items()})
    return perms


def pending_approvals() -> list[dict[str, Any]]:
    return list(ASK_LOG)[-50:]


def approve_tool(tool: str, minutes: int = 10) -> dict[str, Any]:
    tool = (tool or "").lower()
    APPROVALS[tool] = time.time() + max(1, minutes) * 60
    ASK_LOG[:] = [a for a in ASK_LOG if a.get("tool") != tool]
    return {"tool": tool, "approved_for_minutes": max(1, minutes)}


def _run_hook(cmd: str, tool: str, args: dict[str, Any]) -> str:
    if not (cmd or "").strip():
        return ""
    env = {**os.environ, "ARENA_TOOL": tool, "ARENA_ARGS": json.dumps(args)[:2000]}
    try:
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=10, env=env)
        return (((proc.stdout or "") + (proc.stderr or "")).strip())[:1000]
    except Exception as exc:  # noqa: BLE001 — hook failure is advisory
        return f"(hook error: {exc})"


def _validate_command(cmd: str, cwd: Path) -> list[str]:
    """Tokenize and validate a shell command against the safe allow-list."""
    try:
        parts = shlex.split(cmd)
    except ValueError as exc:
        raise AgentError(f"Unparsable command: {exc}") from None
    if not parts:
        raise AgentError("Empty command.")
    base = parts[0].lower()
    if base not in ALLOWED_BASES:
        raise AgentError(f"Command not allowed: '{base}'")
    if base in READ_ONLY_BASES:
        # every path argument must stay inside the workspace (no abs, no ..)
        for arg in parts[1:]:
            if arg.startswith(("/", "\\", "~")):
                raise AgentError(f"Absolute paths not allowed in '{base}'.")
            resolved = (cwd / arg).resolve()
            if cwd.resolve() not in [resolved] + list(resolved.parents):
                raise AgentError(f"Path escapes the workspace in '{base}'.")
    if base == "git" and (len(parts) < 2 or parts[1].lower() not in GIT_SUBS):
        raise AgentError("git: only status/log/diff are allowed.")
    if base == "npm" and (len(parts) < 2 or parts[1].lower() not in NPM_SUBS):
        raise AgentError("npm: only test/run are allowed.")
    if base in ("python", "python3"):
        if len(parts) < 3 or parts[1] != "-m" or parts[2].lower() not in PYMOD_SUBS:
            raise AgentError("python: only 'python -m pytest ...' is allowed.")
    if base == "node":
        if "--version" not in parts and "-v" not in parts:
            raise AgentError("node: only --version is allowed.")
    if base in ("echo", "pwd", "dir", "type"):
        pass  # inherently safe
    if any(ch in cmd for ch in ("|", ">", "&", ";", "`", "$(")):
        raise AgentError("Shell metacharacters are not allowed.")
    return parts


def run_command(cmd: str, cwd: Path, timeout: int = 60) -> str:
    cmd = (cmd or "").strip()
    if not cmd:
        raise AgentError("Empty command.")
    parts = _validate_command(cmd, cwd)
    try:
        proc = subprocess.run(parts, cwd=cwd, capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise AgentError(f"Command timed out after {timeout}s.") from None
    out = (proc.stdout + proc.stderr).strip()
    return (out or "(no output)")[:8000]


def _extract_json(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise AgentError("Agent returned invalid JSON.")
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise AgentError(f"Agent returned invalid JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise AgentError("Agent step must be a JSON object.")
    return obj


async def _dispatch(tool: str, args: dict[str, Any], work_dir: Path) -> str:
    if tool == "list_files":
        entries = files.list_files(args.get("path", ""), root=work_dir)
        return json.dumps(entries)[:4000]
    if tool == "read_file":
        return files.read_file(args.get("path", ""), root=work_dir)["content"][:4000]
    if tool == "write_file":
        res = files.write_file(args.get("path", ""), args.get("content", ""), root=work_dir)
        return f"Wrote {res['path']} ({res['bytes']} bytes)."
    if tool == "search":
        return json.dumps(files.search(args.get("q", ""), root=work_dir))[:4000]
    if tool == "run":
        return run_command(args.get("cmd", ""), cwd=work_dir)
    if tool == "web_search":
        try:
            return json.dumps(web.web_search(
                args.get("q", ""), int(args.get("max_results", 5) or 5)))[:4000]
        except (web.WebError, ValueError) as exc:
            return f"ERROR: {exc}"
    if tool == "web_fetch":
        try:
            page = web.web_fetch(args.get("url", ""))
            return f"{page['title']}\n{page['url']}\n{page['text']}"[:4000]
        except web.WebError as exc:
            return f"ERROR: {exc}"
    if tool == "todo":
        action = str(args.get("action", "list")).lower()
        try:
            if action == "add":
                item = todos.create(args.get("text", ""), root=work_dir)
                return f"Added todo {item['id']}: {item['text']}"
            if action == "done":
                item = todos.set_done(args.get("id", ""), True, root=work_dir)
                return f"Done: {item['text']}"
            return json.dumps(todos.list_todos(root=work_dir))[:4000] or "No todos."
        except todos.TodoError as exc:
            return f"ERROR: {exc}"
    if tool == "mcp":
        try:
            return await mcp_client.call_tool(args.get("server", ""), args.get("tool", ""),
                                              args.get("args") or {})
        except mcp_client.McpError as exc:
            return f"ERROR: {exc}"
    raise AgentError(f"Unknown tool: {tool}")


async def _execute(tool: str, args: dict[str, Any], work_dir: Path,
                   permissions: dict[str, str]) -> str:
    args = args if isinstance(args, dict) else {}
    perm = permissions.get(tool, "allow")
    if perm == "deny":
        raise AgentError(f"BLOCKED by permissions: '{tool}' is set to deny in config.yaml.")
    if perm == "ask" and APPROVALS.get(tool, 0) < time.time():
        ASK_LOG.append({"tool": tool, "args": args, "ts": time.time()})
        raise AgentError(f"NEEDS APPROVAL for '{tool}'. Approve via "
                         f"POST /api/agent/approve {{\"tool\": \"{tool}\"}} then continue.")
    try:
        hooks = config_mod.get_config().hooks or {}
    except Exception:  # noqa: BLE001 — config failure → no hooks
        hooks = {}
    pre = _run_hook(str(hooks.get("pre_tool", "")), tool, args)
    try:
        result = await _dispatch(tool, args, work_dir)
    finally:
        post = _run_hook(str(hooks.get("post_tool", "")), tool, args)
    extra = "".join(f"\n[hook:{k}] {v}" for k, v in (("pre", pre), ("post", post)) if v)
    return result + extra[:2000]


async def run_agent(task: str, model: str, max_steps: int = 8,
                    work_dir: Path | None = None, profile: str = "coder",
                    permissions: dict[str, str] | None = None) -> dict[str, Any]:
    """Run the agent loop. Returns steps + status + summary."""
    try:
        prof = profiles.get_profile(profile or "coder")
    except KeyError as exc:
        return {"status": "error", "steps": [], "summary": str(exc)}
    pid = (profile or "coder").lower()
    work_dir = (work_dir or files.WORKSPACE).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    perms = effective_permissions(permissions)
    allowed = set(prof["tools"])
    tools_doc = "\n".join(f"- {TOOL_DOCS[t]}" for t in prof["tools"] if t in TOOL_DOCS)
    system = (f"{BASE_SYSTEM}\n\nYour profile: {prof['name']} — {prof['system']}\n"
              f"Allowed tools (use ONLY these + done):\n{tools_doc}\n- {TOOL_DOCS['done']}")
    messages: list[dict[str, str]] = contextx.inject_context(
        [{"role": "system", "content": system}, {"role": "user", "content": task}],
        root=work_dir)
    steps: list[dict[str, Any]] = []
    for _ in range(max(1, min(max_steps, 25))):
        try:
            resp = await llm.chat_completion(model, messages, max_tokens=1500, temperature=0.3)
        except llm.ArenaLLMError as exc:
            return {"status": "error", "steps": steps, "summary": str(exc)}
        raw = resp.get("content", "")
        try:
            step = _extract_json(raw)
        except AgentError as exc:
            steps.append({"thought": "", "tool": "error", "args": {}, "result": str(exc)})
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": "ERROR: reply with ONE valid JSON object."})
            continue
        thought = str(step.get("thought", ""))[:500]
        tool = str(step.get("tool", ""))
        args = step.get("args", {})
        if tool == "done":
            summary = str(args.get("summary", "Done.") if isinstance(args, dict) else "Done.")
            steps.append({"thought": thought, "tool": "done", "args": {}, "result": summary})
            return {"status": "complete", "steps": steps, "summary": summary}
        if tool not in allowed:
            result = (f"ERROR: tool '{tool}' not allowed for profile '{pid}'. "
                      f"Allowed: {sorted(allowed)}")
        else:
            try:
                result = await _execute(tool, args if isinstance(args, dict) else {},
                                        work_dir, perms)
            except (AgentError, files.FileError) as exc:
                result = f"ERROR: {exc}"
        steps.append({"thought": thought, "tool": tool,
                      "args": args if isinstance(args, dict) else {}, "result": result[:4000]})
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"OBSERVATION:\n{result[:3000]}"})
    return {"status": "max_steps", "steps": steps,
            "summary": f"Stopped after {len(steps)} steps (limit reached)."}


async def plan_task(task: str, model: str, work_dir: Path | None = None) -> dict[str, Any]:
    """Plan mode (Claude-Code-style): no tools, just a numbered plan → saved as todos."""
    work_dir = (work_dir or files.WORKSPACE).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    messages = contextx.inject_context(
        [{"role": "system", "content": PLAN_PROMPT},
         {"role": "user", "content": task}], root=work_dir)
    try:
        resp = await llm.chat_completion(model, messages, max_tokens=1200, temperature=0.3)
    except llm.ArenaLLMError as exc:
        return {"plan": [], "todos": [], "error": str(exc)}
    raw = resp.get("content", "")
    steps: list[str] = []
    try:
        obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        steps = [str(s)[:300] for s in obj.get("steps", [])][:12]
    except (json.JSONDecodeError, ValueError, AttributeError):
        for line in raw.splitlines():
            line = line.strip()
            if line:
                cleaned = line.lstrip("-*0123456789.() ").strip()
                if cleaned:
                    steps.append(cleaned[:300])
            if len(steps) >= 12:
                break
    if not steps:
        steps = [(raw.strip() or "No plan returned.")[:300]]
    created = []
    for s in steps:
        try:
            created.append(todos.create(s, root=work_dir))
        except todos.TodoError:
            pass
    return {"plan": steps, "todos": created}

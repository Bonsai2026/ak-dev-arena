"""AK Dev Studio Agent — plan → act → observe → verify loop with real evidence.

The LLM replies with ONE JSON object per step:
  {"thought": "...", "tool": "<tool>", "args": {...}}

Hard rule ("I verified it"): after code changes the agent MUST run the build /
tests and report the actual exit output. `done` may carry a verification list:
  done {"summary": "...", "verification": [["criteria", "pass"|"fail"|"unverified"]]}

Profiles (FreeBuff-style): coder / researcher / reviewer / planner.
Permissions (OpenCode-style): config.yaml -> permissions: {tool: allow|ask|deny}
Hooks (Claude-Code-style): config.yaml -> hooks: {pre_tool, post_tool}.
Cancellation + timeouts + task state: see TaskStore at the bottom.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from . import config as config_mod
from . import (browser, contextx, files, gitops, llm, mcp_client, procman,
               profiles, projects, todos, web)

BASE_SYSTEM = """You are the AK Dev Studio agent — an AI engineer working on the user's PC.
Solve the task step by step, using tools to inspect, edit, build and test.
Hard rule: NEVER claim something works unless you actually ran it. After code
changes run the build/tests and report real output. Finish ONLY with:
{"thought": "short reasoning", "tool": "done", "args": {"summary": "...",
 "verification": [["criteria", "pass"|"fail"|"unverified"]]}}"""

TOOL_DOCS = {
    "list_files": 'list_files {"path": "optional subdir"}',
    "read_file": 'read_file {"path": "file"}',
    "write_file": 'write_file {"path": "file", "content": "full new content"}',
    "edit_file": 'edit_file {"path": "file", "old_text": "exact snippet", "new_text": "replacement"}',
    "delete_file": 'delete_file {"path": "file"}',
    "search": 'search {"q": "text"}',
    "run": 'run {"cmd": "allow-listed command"}',
    "run_build": 'run_build {} (detects package.json/pyproject)',
    "run_tests": 'run_tests {} (npm test / pytest)',
    "install_dependency": 'install_dependency {"pkg": "name|name@version"}',
    "start_server": 'start_server {} — starts the dev server, returns port',
    "stop_server": 'stop_server {"port": 1420}',
    "git_status": 'git_status {}',
    "git_diff": 'git_diff {}',
    "git_checkpoint": 'git_checkpoint {"message": "arena: ..."}',
    "git_revert": 'git_revert {} — safe undo of the last arena checkpoint',
    "web_search": 'web_search {"q": "query", "max_results": 5}',
    "web_fetch": 'web_fetch {"url": "https://..."}',
    "browser_inspect": 'browser_inspect {"url": "http://127.0.0.1:PORT", "actions": [{"type": "click|fill|text|wait", "selector": "...", "value": "..."}]}',
    "todo": 'todo {"action": "add|done|list", "text": "...", "id": "..."}',
    "mcp": 'mcp {"server": "id", "tool": "name", "args": {...}}',
    "done": 'done {"summary": "...", "verification": [["criteria", "pass"]]}',
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
_running_servers: dict[str, str] = {}  # task_id -> proc id (one server per task)
_VERIFICATION_TOOLS = {"run_build", "run_tests", "start_server", "git_checkpoint", "git_revert"}


def default_permissions() -> dict[str, str]:
    perms = {t: "allow" for t in TOOL_DOCS if t != "done"}
    # dangerous-by-default tools request approval unless explicitly allowed
    perms.update({"delete_file": "ask", "install_dependency": "ask",
                  "start_server": "ask", "git_revert": "ask", "git_checkpoint": "ask",
                  "browser_inspect": "ask"})
    return perms


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


async def _dispatch(tool: str, args: dict[str, Any], work_dir: Path,
                    task_id: str | None = None) -> str:
    if tool == "list_files":
        entries = files.list_files(args.get("path", ""), root=work_dir)
        return json.dumps(entries)[:4000]
    if tool == "read_file":
        return files.read_file(args.get("path", ""), root=work_dir)["content"][:4000]
    if tool == "write_file":
        res = files.write_file(args.get("path", ""), args.get("content", ""), root=work_dir)
        return f"Wrote {res['path']} ({res['bytes']} bytes)."
    if tool == "edit_file":
        res = files.apply_edit(args.get("path", ""), args.get("old_text", ""),
                               args.get("new_text", ""), root=work_dir)
        return f"Edited {res['path']}.\n{res['diff']}"[:4000]
    if tool == "delete_file":
        res = files.delete_file(args.get("path", ""), root=work_dir)
        return f"Deleted {res['path']}."
    if tool == "search":
        return json.dumps(files.search(args.get("q", ""), root=work_dir))[:4000]
    if tool == "run":
        return run_command(args.get("cmd", ""), cwd=work_dir)
    if tool in ("run_build", "run_tests"):
        project = projects.detect(work_dir)
        cmd = projects.build_cmd(project) if tool == "run_build" else projects.test_cmd(project)
        if not cmd:
            return (f"ERROR: no {tool.replace('run_', '')} command detected for this project "
                    f"(type={project['type']}, scripts={project['scripts'] or 'none'}).")
        res = procman.run(cmd, work_dir, timeout=600, task_id=task_id)
        tail = ((res.get("stdout") or "") + "\n" + (res.get("stderr") or "")).strip()[-4000:]
        return f"exit={res['exit_code']} duration={res['duration']}s\n{tail}"
    if tool == "install_dependency":
        pkg = str(args.get("pkg", "") or "").strip()
        if not re.match(r"^[A-Za-z0-9_@.\-/\[\]=<>,~^]+$", pkg):
            return "ERROR: invalid package name."
        project = projects.detect(work_dir)
        if project["type"] == "node":
            cmd = ["npm", "install", pkg]
        elif project["type"] == "python":
            cmd = ["python", "-m", "pip", "install", pkg]
        else:
            return "ERROR: unsupported project type for install."
        res = procman.run(cmd, work_dir, timeout=600, task_id=task_id)
        tail = ((res.get("stdout") or "") + "\n" + (res.get("stderr") or "")).strip()[-3000:]
        return f"exit={res['exit_code']}\n{tail}"
    if tool == "start_server":
        if _running_servers.get(task_id or "global"):
            return "ERROR: a server is already running for this task. Stop it first."
        project = projects.detect(work_dir)
        port = procman.find_free_port()
        cmd = projects.dev_cmd(project, port)
        if not cmd:
            return f"ERROR: no dev/start script detected (type={project['type']})."
        info = procman.start(cmd, work_dir, task_id=task_id, port=port)
        _running_servers[task_id or "global"] = info["id"]
        return (f"Server started: pid={info['pid']} id={info['id']} "
                f"url=http://127.0.0.1:{port} (cmd: {info['command']})")
    if tool == "stop_server":
        port = int(args.get("port", 0) or 0)
        stopped = False
        if port:
            stopped = procman.stop_by_port(port)
        for tid, pid in list(_running_servers.items()):
            if not port or _running_servers.get(tid) == pid:
                stopped = procman.stop(pid) or stopped
                del _running_servers[tid]
        return "Server stopped." if stopped else ("No server running on that port." if port
                                                  else "No server running.")
    if tool in ("git_status", "git_diff", "git_checkpoint", "git_revert"):
        try:
            if tool == "git_status":
                return json.dumps(gitops.status(root=work_dir))[:4000]
            if tool == "git_diff":
                return gitops.diff(root=work_dir) or "No changes."
            if tool == "git_checkpoint":
                msg = args.get("message", "arena: agent checkpoint")[:200]
                cp = gitops.checkpoint("", msg, root=work_dir)
                return f"Checkpoint {cp['hash'] or 'clean'}: {cp['message']}"
            return json.dumps(gitops.undo(root=work_dir))[:4000]
        except gitops.GitError as exc:
            return f"ERROR: {exc}"
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
    if tool == "browser_inspect":
        try:
            report = await browser.inspect(str(args.get("url", "")),
                                           args.get("actions") or [])
            return json.dumps(report)[:6000]
        except browser.BrowserError as exc:
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
                   permissions: dict[str, str],
                   task_id: str | None = None) -> str:
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
        result = await _dispatch(tool, args, work_dir, task_id=task_id)
    finally:
        post = _run_hook(str(hooks.get("post_tool", "")), tool, args)
    extra = "".join(f"\n[hook:{k}] {v}" for k, v in (("pre", pre), ("post", post)) if v)
    return result + extra[:2000]


async def _llm_call_with_retry(model: str, messages: list[dict[str, str]],
                               max_tokens: int, temperature: float,
                               cancel: asyncio.Event | None) -> dict[str, Any]:
    """One LLM call with 1 retry for transient failures (rate limit / network)."""
    last: Exception | None = None
    for attempt in range(2):
        if cancel is not None and cancel.is_set():
            raise asyncio.CancelledError()
        try:
            return await llm.chat_completion(model, messages,
                                             max_tokens=max_tokens, temperature=temperature)
        except llm.ArenaLLMError as exc:
            msg = str(exc).lower()
            transient = ("rate limit" in msg or "cannot reach" in msg
                         or "connection" in msg or "timeout" in msg)
            if not transient or attempt >= 1:
                raise
            last = exc
            await asyncio.sleep(1.5 * (attempt + 1))
    if last:  # pragma: no cover — unreachable, kept for type safety
        raise last
    raise RuntimeError("LLM call failed")  # pragma: no cover


def _summarize_evidence(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive verification evidence from what the agent ACTUALLY ran."""
    evidence: dict[str, Any] = {"build": None, "tests": None, "servers": [],
                                "commands": [], "has_evidence": False}
    for s in steps:
        tool, result = s.get("tool"), s.get("result", "")
        status = "unverified"
        if tool in ("run_build", "run_tests") and result.startswith("exit="):
            try:
                code = int(result.split()[0].split("=")[1])
                status = "pass" if code == 0 else "fail"
                evidence["has_evidence"] = True
            except (ValueError, IndexError):
                pass
            (evidence.__setitem__("build" if tool == "run_build" else "tests", status))
        elif tool == "start_server" and "Server started" in result:
            evidence["servers"].append(result.split("pid=")[1].split()[0])
            evidence["has_evidence"] = True
        elif tool == "run":
            if "exit=" in result:
                try:
                    code = int(result.split("exit=")[1].split()[0])
                    if code == 0:
                        evidence["commands"].append({"ok": True})
                        evidence["has_evidence"] = True
                except (ValueError, IndexError):
                    pass
    return evidence


async def run_agent(task: str, model: str, max_steps: int = 8,
                    work_dir: Path | None = None, profile: str = "coder",
                    permissions: dict[str, str] | None = None,
                    cancel: asyncio.Event | None = None,
                    on_step: Callable[[dict[str, Any]], None] | None = None,
                    task_id: str | None = None) -> dict[str, Any]:
    """Run the agent loop. Returns steps + status + summary + verification.

    Cancellation: pass an asyncio.Event — checked before every LLM call/step.
    Callbacks: on_step(step) is invoked after each tool finishes.
    """
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
    started = time.time()
    for idx in range(max(1, min(max_steps, 25))):
        if cancel is not None and cancel.is_set():
            return {"status": "cancelled", "steps": steps,
                    "summary": f"Cancelled after {len(steps)} steps.",
                    "verification": _summarize_evidence(steps)}
        try:
            resp = await _llm_call_with_retry(model, messages, 1500, 0.3, cancel)
        except asyncio.CancelledError:
            return {"status": "cancelled", "steps": steps,
                    "summary": "Cancelled.", "verification": _summarize_evidence(steps)}
        except llm.ArenaLLMError as exc:
            return {"status": "error", "steps": steps, "summary": str(exc),
                    "verification": _summarize_evidence(steps)}
        raw = resp.get("content", "")
        try:
            step = _extract_json(raw)
        except AgentError as exc:
            error_step = {"thought": "", "tool": "error", "args": {}, "result": str(exc)}
            steps.append(error_step)
            if on_step:
                on_step({**error_step, "index": idx})
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": "ERROR: reply with ONE valid JSON object."})
            continue
        thought = str(step.get("thought", ""))[:500]
        tool = str(step.get("tool", ""))
        args = step.get("args", {})
        if tool == "done":
            summary = str(args.get("summary", "Done.") if isinstance(args, dict) else "Done.")
            verification = (args.get("verification", []) if isinstance(args, dict) else [])
            steps.append({"thought": thought, "tool": "done", "args": {}, "result": summary})
            if on_step:
                on_step({"thought": thought, "tool": "done", "args": {}, "result": summary,
                         "index": idx})
            return {"status": "complete", "steps": steps, "summary": summary,
                    "verification": _summarize_evidence(steps),
                    "criteria": _normalize_criteria(verification)}
        if tool not in allowed:
            result = (f"ERROR: tool '{tool}' not allowed for profile '{pid}'. "
                      f"Allowed: {sorted(allowed)}")
        else:
            try:
                result = await _execute(tool, args if isinstance(args, dict) else {},
                                        work_dir, perms, task_id=task_id)
            except (AgentError, files.FileError, gitops.GitError) as exc:
                result = f"ERROR: {exc}"
        step_entry = {"thought": thought, "tool": tool,
                      "args": args if isinstance(args, dict) else {}, "result": result[:4000]}
        steps.append(step_entry)
        if on_step:
            on_step({**step_entry, "index": idx})
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"OBSERVATION:\n{result[:3000]}"})
    return {"status": "max_steps", "steps": steps,
            "summary": f"Stopped after {len(steps)} steps (limit reached).",
            "verification": _summarize_evidence(steps),
            "elapsed": round(time.time() - started, 1)}


def _normalize_criteria(raw: Any) -> list[dict[str, str]]:
    """done verification arg → [{criteria, status}] with strict status labels."""
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return out
    for item in raw[:15]:
        if isinstance(item, list) and len(item) >= 2:
            criteria, status = str(item[0])[:200], str(item[1]).lower()
        elif isinstance(item, dict):
            criteria = str(item.get("criteria", ""))[:200]
            status = str(item.get("status", "")).lower()
        else:
            continue
        if status not in ("pass", "fail", "unverified"):
            status = "unverified"
        out.append({"criteria": criteria or "?", "status": status})
    return out


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


# ========================================================================
# Task Store — long-running agent tasks: progress, cancellation, timeouts.
# ========================================================================

TASK_TIMEOUT_SECONDS = int(os.environ.get("ARENA_AGENT_TIMEOUT", "900"))
_TASKS: dict[str, dict[str, Any]] = {}
_MAX_TASKS = 100


def _task_public(state: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in state.items() if not k.startswith("_")}


def _prune_tasks() -> None:
    if len(_TASKS) <= _MAX_TASKS:
        return
    finished = sorted(
        (s for s in _TASKS.values() if s.get("finished")),
        key=lambda s: s["finished"] or 0)
    for s in finished[: len(_TASKS) - _MAX_TASKS]:
        _TASKS.pop(s["id"], None)


async def _task_runner(state: dict[str, Any], task: str, model: str,
                       max_steps: int, profile: str, work_dir: Path) -> None:
    cancel: asyncio.Event = state["_cancel"]
    state["status"] = "running"
    state["started"] = time.time()
    # Step 1 — plan (goals + todos), best-effort
    try:
        plan = await plan_task(task, model, work_dir=work_dir)
        state["plan"] = plan.get("plan", [])
    except Exception:  # noqa: BLE001, S110 — planning must never kill the task
        pass

    def _on_step(step: dict[str, Any]) -> None:
        tool = step.get("tool", "")
        args = step.get("args") or {}
        if tool in ("write_file", "edit_file") and args.get("path"):
            path = str(args["path"])
            if path not in state["files"]:
                state["files"].append(path)
        elif tool == "delete_file" and args.get("path"):
            path = str(args["path"])
            if path in state["files"]:
                state["files"].remove(path)
            state["files"].append(f"{path} (deleted)")
        state["current"] = {"tool": tool, "thought": step.get("thought", ""),
                            "result": step.get("result", "")[:2000]}
        state["steps"].append({k: v for k, v in step.items() if k != "index"})

    try:
        result = await asyncio.wait_for(
            run_agent(task, model, max_steps, work_dir=work_dir, profile=profile,
                      cancel=cancel, on_step=_on_step, task_id=state["id"]),
            timeout=TASK_TIMEOUT_SECONDS)
        state.update({k: result.get(k) for k in
                      ("status", "summary", "verification", "criteria", "error")})
        state["status"] = result.get("status", "done")
        state["summary"] = result.get("summary", "")
        state["verification"] = result.get("verification")
        state["criteria"] = result.get("criteria", [])
        if result.get("status") in ("error",):
            state["error"] = result.get("summary", "")
    except asyncio.TimeoutError:
        cancel.set()
        state["status"] = "timeout"
        state["summary"] = f"Stopped after {TASK_TIMEOUT_SECONDS}s (global timeout)."
        state["error"] = state["summary"]
    except asyncio.CancelledError:
        cancel.set()
        state["status"] = "cancelled"
        state["summary"] = "Cancelled by user."
    except Exception as exc:  # noqa: BLE001 — tasks must never crash the server
        state["status"] = "failed"
        state["error"] = str(exc)[:400]
        state["summary"] = "Task failed — see error."
    finally:
        procman.stop_all_for_task(state["id"])
        state["finished"] = time.time()
        state["current"] = None
        state["status"] = state["status"] if state["status"] != "running" else "failed"


def create_task(task: str, model: str, max_steps: int = 8,
                profile: str = "coder", work_dir: Path | None = None) -> dict[str, Any]:
    tid = uuid.uuid4().hex[:8]
    state: dict[str, Any] = {
        "id": tid, "task": task, "model": model, "profile": profile,
        "status": "queued", "created": time.time(), "started": None, "finished": None,
        "steps": [], "current": None, "summary": "", "error": "",
        "verification": None, "criteria": [], "plan": [], "files": [],
        "_cancel": asyncio.Event(),
    }
    _TASKS[tid] = state
    base = (work_dir or files.WORKSPACE).resolve()
    base.mkdir(parents=True, exist_ok=True)
    state["_task"] = asyncio.get_running_loop().create_task(
        _task_runner(state, task, model, max_steps, profile, base))
    _prune_tasks()
    return _task_public(state)


def get_task(task_id: str) -> dict[str, Any] | None:
    state = _TASKS.get(task_id)
    return _task_public(state) if state else None


def list_tasks() -> list[dict[str, Any]]:
    return [_task_public(s) for s in sorted(
        _TASKS.values(), key=lambda s: s["created"], reverse=True)]


def cancel_task(task_id: str) -> bool:
    state = _TASKS.get(task_id)
    if not state or state["status"] in ("done", "failed", "cancelled", "timeout"):
        return False
    state["_cancel"].set()
    return True


def reset_tasks_for_tests() -> None:
    for state in list(_TASKS.values()):
        task = state.get("_task")
        if task:
            task.cancel()
        state["_cancel"].set()
        procman.stop_all_for_task(state.get("id", ""))
    _TASKS.clear()

"""Arena Agent — plan → act → verify loop over workspace tools.

The LLM must reply with ONE JSON object per step:
  {"thought": "...", "tool": "<tool>|done", "args": {...}}

Tools: list_files, read_file, write_file, search, run.
Shell commands are allow-listed AND confined to the workspace directory.
"""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from . import files, llm

SYSTEM_PROMPT = """You are the AK Dev Arena agent. Solve the user's task step by step.

Reply with EXACTLY ONE JSON object per step, no other text:
{"thought": "short reasoning", "tool": "<tool>", "args": {...}}

Tools:
- list_files {"path": "optional subdir"}
- read_file {"path": "file"}
- write_file {"path": "file", "content": "full new content"}
- search {"q": "text"}
- run {"cmd": "shell command (allow-listed only: ls, cat, echo, pwd, git status/log/diff, python/node/npm --version, pytest, npm test, npm run build)"}
- done {"summary": "what was accomplished"}

When the task is complete, use tool "done". Keep steps small and verify your work."""

ALLOWED_CMD_PREFIXES = (
    "ls", "cat ", "cat", "echo", "pwd", "python --version", "python3 --version",
    "pip --version", "node --version", "npm --version", "git status", "git log",
    "git diff", "pytest", "npm test", "npm run build", "dir", "type ",
)


class AgentError(Exception):
    """User-friendly agent failure (safe to show in UI)."""


def run_command(cmd: str, cwd: Path, timeout: int = 60) -> str:
    cmd = (cmd or "").strip()
    if not cmd:
        raise AgentError("Empty command.")
    if not cmd.startswith(ALLOWED_CMD_PREFIXES):
        raise AgentError(f"Command not allow-listed: {cmd.split()[0]}")
    try:
        proc = subprocess.run(shlex.split(cmd), cwd=cwd, capture_output=True,
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


def _execute(tool: str, args: dict[str, Any], work_dir: Path) -> str:
    args = args if isinstance(args, dict) else {}
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
    raise AgentError(f"Unknown tool: {tool}")


async def run_agent(task: str, model: str, max_steps: int = 8,
                    work_dir: Path | None = None) -> dict[str, Any]:
    """Run the agent loop. Returns steps + status + summary."""
    work_dir = (work_dir or files.WORKSPACE).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
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
        try:
            result = _execute(tool, args if isinstance(args, dict) else {}, work_dir)
        except (AgentError, files.FileError) as exc:
            result = f"ERROR: {exc}"
        steps.append({"thought": thought, "tool": tool,
                      "args": args if isinstance(args, dict) else {}, "result": result[:4000]})
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": f"OBSERVATION:\n{result[:3000]}"})
    return {"status": "max_steps", "steps": steps,
            "summary": f"Stopped after {len(steps)} steps (limit reached)."}

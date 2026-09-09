"""Arena agent profiles — specialized agents (FreeBuff-style division of labor).

Instead of one agent doing everything, each profile gets its own system
prompt + restricted toolset: researchers can't edit, reviewers can't write.
"""

from __future__ import annotations

from typing import Any

PROFILES: dict[str, dict[str, Any]] = {
    "coder": {
        "name": "Coder",
        "description": "Reads, edits, deletes, builds, tests and runs code. Default builder.",
        "tools": [
            "list_files", "read_file", "write_file", "edit_file", "delete_file",
            "search", "run", "run_build", "run_tests", "install_dependency",
            "start_server", "stop_server",
            "git_status", "git_diff", "git_checkpoint", "git_revert",
            "todo", "mcp",
        ],
        "system": ("You are a coding specialist. Make minimal, correct changes, then ACTUALLY "
                   "run the build/tests and verify before reporting done."),
    },
    "researcher": {
        "name": "Researcher",
        "description": "Web + codebase research. Never modifies files.",
        "tools": ["list_files", "read_file", "search", "web_search", "web_fetch", "todo"],
        "system": ("You are a research specialist. Investigate docs, code and the web, "
                   "then summarize findings. NEVER modify files."),
    },
    "reviewer": {
        "name": "Reviewer",
        "description": "Strict code review. Read-only.",
        "tools": ["list_files", "read_file", "search", "run"],
        "system": ("You are a strict reviewer. Inspect code and tests, then end with a "
                   "findings summary via done. Change nothing."),
    },
    "planner": {
        "name": "Planner",
        "description": "Plans only — explores briefly, outputs a numbered plan.",
        "tools": ["list_files", "read_file", "search"],
        "system": ("You are a planner. Explore briefly, then output a numbered plan "
                   "via done. Change nothing."),
    },
}


def list_profiles() -> list[dict[str, Any]]:
    return [{"id": pid, **p} for pid, p in PROFILES.items()]


def get_profile(pid: str) -> dict[str, Any]:
    pid = (pid or "").lower()
    if pid not in PROFILES:
        raise KeyError(f"Unknown profile '{pid}'. Pick: {', '.join(PROFILES)}")
    return PROFILES[pid]

"""Project adapters — detect what kind of project lives in a workspace and
produce the right install/build/test/dev commands.

Extensible: add an entry to ADAPTERS to support another ecosystem. Kept
deliberately small — one detect() + per-adapter command builders.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import files


def detect(root) -> dict[str, Any]:
    """Best-effort project detection. Returns a normalized descriptor."""
    base = files._root(root)  # noqa: SLF001 — same package
    pkg = base / "package.json"
    pyproject = base / "pyproject.toml"
    reqs = base / "requirements.txt"
    adapter: dict[str, Any] = {
        "type": "static", "name": "static", "package_manager": None,
        "scripts": {}, "python": False, "supported": True,
    }
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            scripts = data.get("scripts") or {}
            adapter.update({
                "type": "node", "name": "node",
                "package_manager": "npm",
                "scripts": {str(k): str(v) for k, v in scripts.items()},
                "frameworks": _node_frameworks(scripts),
            })
        except (OSError, json.JSONDecodeError):
            pass
    if pyproject.is_file() or reqs.is_file():
        adapter.update({"type": "python", "name": "python", "python": True,
                        "package_manager": "pip"})
    return adapter


def _node_frameworks(scripts: dict[str, str]) -> list[str]:
    blob = " ".join(f"{k} {v}" for k, v in scripts.items()).lower()
    out = []
    for name, hint in (("vite", "vite"), ("next", "next"), ("react", "react"),
                       ("webpack", "webpack"), ("tsc", "tsc")):
        if hint in blob:
            out.append(name)
    return out


def install_cmd(project) -> list[str]:
    if project["type"] == "node":
        return ["npm", "install"]
    if project["type"] == "python":
        return ["python", "-m", "pip", "install", "-r", "requirements.txt"]
    return []


def build_cmd(project) -> list[str] | None:
    if project["type"] == "node":
        if "build" in project["scripts"]:
            return ["npm", "run", "build"]
        return None
    return None  # python build varies (no universal default)


def test_cmd(project) -> list[str] | None:
    if project["type"] == "node":
        if "test" in project["scripts"]:
            return ["npm", "test"]
        return None
    if project["type"] == "python":
        return ["python", "-m", "pytest", "-q"]
    return None


def dev_cmd(project, port: int) -> list[str] | None:
    if project["type"] == "node":
        if "dev" in project["scripts"]:
            script = project["scripts"]["dev"]
            if "vite" in script or "next" in script:
                return ["npm", "run", "dev", "--", "--port", str(port)]
            return ["npm", "run", "dev"]
        if "start" in project["scripts"]:
            return ["npm", "run", "start", "--", "--port", str(port)]
        return None
    return None


def browser_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"

"""Arena Build Mode — prompt-to-project scaffolding + AI fix loop.

Templates generate real starter projects under ./workspace/builds/<name>/.
The fix loop asks the LLM for a surgical old_text/new_text patch and applies
it with the same safe edit engine as Code Mode.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import files, llm

BUILDS_DIR = "builds"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-_]{0,60}$")

TEMPLATES: dict[str, dict[str, Any]] = {
    "static-html": {
        "description": "Single-page static site (HTML + CSS + JS)",
        "files": {
            "index.html": (
                "<!doctype html>\n<html lang=\"en\">\n<head>\n"
                "  <meta charset=\"utf-8\" />\n"
                "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
                "  <title>{{NAME}}</title>\n"
                "  <link rel=\"stylesheet\" href=\"style.css\" />\n</head>\n<body>\n"
                "  <main>\n    <h1>{{NAME}}</h1>\n    <p>{{DESC}}</p>\n"
                "  </main>\n  <script src=\"app.js\"></script>\n</body>\n</html>\n"
            ),
            "style.css": (
                "body { font-family: system-ui, sans-serif; background: #0f0f13; color: #f4f4f5;"
                " display: grid; place-items: center; min-height: 100vh; margin: 0; }\n"
                "main { text-align: center; }\nh1 { font-size: 3rem; margin-bottom: .5rem; }\n"
            ),
            "app.js": "console.log('{{NAME}} ready');\n",
            "README.md": "# {{NAME}}\n\n{{DESC}}\n\nBuilt with AK Dev Arena 🏟️\n",
        },
    },
    "vite-react": {
        "description": "Vite + React starter (npm install && npm run dev)",
        "files": {
            "package.json": (
                '{\n  "name": "{{NAME}}",\n  "private": true,\n  "version": "0.1.0",\n'
                '  "type": "module",\n'
                '  "scripts": { "dev": "vite", "build": "vite build", "preview": "vite preview" },\n'
                '  "dependencies": { "react": "^18.3.1", "react-dom": "^18.3.1" },\n'
                '  "devDependencies": { "@vitejs/plugin-react": "^4.3.0", "vite": "^6.0.0" }\n}\n'
            ),
            "index.html": (
                "<!doctype html>\n<html>\n<head><meta charset=\"utf-8\" />\n"
                "<title>{{NAME}}</title></head>\n<body>\n<div id=\"root\"></div>\n"
                "<script type=\"module\" src=\"/src/main.jsx\"></script>\n</body>\n</html>\n"
            ),
            "src/main.jsx": (
                "import React from 'react';\nimport ReactDOM from 'react-dom/client';\n"
                "import App from './App.jsx';\n"
                "ReactDOM.createRoot(document.getElementById('root')).render(<App />);\n"
            ),
            "src/App.jsx": (
                "export default function App() {\n"
                "  return (<main style={{fontFamily:'system-ui',padding:40}}>\n"
                "    <h1>{{NAME}}</h1>\n    <p>{{DESC}}</p>\n  </main>);\n}\n"
            ),
            "README.md": "# {{NAME}}\n\n{{DESC}}\n\n```bash\nnpm install\nnpm run dev\n```\n",
        },
    },
    "fastapi-py": {
        "description": "FastAPI micro-service (pip install -r requirements.txt)",
        "files": {
            "main.py": (
                "\"\"\"{{NAME}} — {{DESC}}\"\"\"\nfrom fastapi import FastAPI\n\n"
                "app = FastAPI(title='{{NAME}}')\n\n"
                "@app.get('/')\ndef root():\n"
                "    return {'app': '{{NAME}}', 'status': 'ok'}\n\n"
                "@app.get('/health')\ndef health():\n    return {'status': 'ok'}\n"
            ),
            "requirements.txt": "fastapi>=0.115\nuvicorn[standard]>=0.30\n",
            "README.md": "# {{NAME}}\n\n{{DESC}}\n\n```bash\npip install -r requirements.txt\nuvicorn main:app --reload\n```\n",
        },
    },
}


class BuildError(Exception):
    """User-friendly build failure (safe to show in UI)."""


def list_templates() -> list[dict[str, Any]]:
    return [{"id": tid, "description": t["description"], "files": sorted(t["files"])}
            for tid, t in TEMPLATES.items()]


def _build_root(name: str, root: Path | None = None) -> Path:
    if not _NAME_RE.match(name or ""):
        raise BuildError("Invalid project name — use lowercase letters, numbers, - and _.")
    base = (root or files.WORKSPACE).resolve()
    target = (base / BUILDS_DIR / name).resolve()
    if base not in target.parents:
        raise BuildError("Invalid project path.")
    return target


def generate(name: str, template: str, description: str = "",
             root: Path | None = None) -> dict[str, Any]:
    if template not in TEMPLATES:
        raise BuildError(f"Unknown template: {template}")
    target = _build_root(name, root)
    if target.exists() and any(target.iterdir()):
        raise BuildError(f"Project '{name}' already exists.")
    desc = description.strip() or f"A {template} app built with AK Dev Arena."
    written = []
    for rel, content in TEMPLATES[template]["files"].items():
        text = content.replace("{{NAME}}", name).replace("{{DESC}}", desc)
        files.write_file(f"{BUILDS_DIR}/{name}/{rel}", text, root=root)
        written.append(f"{BUILDS_DIR}/{name}/{rel}")
    return {"name": name, "template": template, "path": f"{BUILDS_DIR}/{name}", "files": written}


def list_builds(root: Path | None = None) -> list[dict[str, Any]]:
    base = (root or files.WORKSPACE).resolve()
    builds = base / BUILDS_DIR
    if not builds.is_dir():
        return []
    out = []
    for child in sorted(builds.iterdir()):
        if child.is_dir():
            count = sum(1 for _ in child.rglob("*") if _.is_file())
            out.append({"name": child.name, "path": f"{BUILDS_DIR}/{child.name}", "files": count})
    return out


FIX_PROMPT = """You fix one bug in a project. Reply with EXACTLY ONE JSON object:
{"path": "relative file path", "old_text": "exact snippet to replace", "new_text": "replacement"}
Rules: old_text must match the file exactly. Minimal change only. No other text."""


async def fix_build(name: str, error: str, model: str,
                    root: Path | None = None) -> dict[str, Any]:
    target = _build_root(name, root)
    if not target.is_dir():
        raise BuildError(f"Project '{name}' not found.")
    listing = sorted(p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file())
    resp = await llm.chat_completion(model, [
        {"role": "system", "content": FIX_PROMPT},
        {"role": "user", "content": f"PROJECT FILES:\n{json.dumps(listing)}\n\nERROR:\n{error[:2000]}"},
    ], max_tokens=1500, temperature=0.2)
    raw = resp.get("content", "")
    try:
        patch = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        rel = str(patch["path"]).lstrip("/")
        full = f"{BUILDS_DIR}/{name}/{rel}"
        # validate inside project
        resolved = ((root or files.WORKSPACE).resolve() / full).resolve()
        if target.resolve() not in ([resolved] + list(resolved.parents)):
            raise BuildError("Patch path escapes the project.")
        result = files.apply_edit(full, str(patch["old_text"]), str(patch["new_text"]), root=root)
    except (json.JSONDecodeError, KeyError):
        raise BuildError("The AI returned an invalid patch — try again.") from None
    return {"name": name, "path": full, "diff": result["diff"], "applied": True}

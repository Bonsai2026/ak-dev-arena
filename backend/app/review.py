"""Arena Review Mode — a second pair of AI eyes on every diff.

Send a unified diff (or any code), get structured findings back:
[{severity, file, line, message}] + summary. Like CodeRabbit, but local,
free and multi-provider.
"""

from __future__ import annotations

import json
from typing import Any

from . import llm

REVIEW_PROMPT = """You are a strict senior code reviewer. Review the diff below.
Reply with EXACTLY ONE JSON object, no other text:
{"summary": "one paragraph verdict", "findings": [
  {"severity": "critical|warning|info", "file": "path", "line": 0, "message": "what + how to fix"}
]}
Rules: max 15 findings, ordered by severity. Empty findings [] if the code is clean."""


class ReviewError(Exception):
    """User-friendly review failure (safe to show in UI)."""


async def review_diff(diff: str, model: str) -> dict[str, Any]:
    if not diff.strip():
        raise ReviewError("Empty diff — nothing to review.")
    resp = await llm.chat_completion(model, [
        {"role": "system", "content": REVIEW_PROMPT},
        {"role": "user", "content": f"DIFF:\n{diff[:12000]}"},
    ], max_tokens=2000, temperature=0.2)
    raw = resp.get("content", "")
    try:
        obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        findings = obj.get("findings", [])
        if not isinstance(findings, list):
            raise ValueError
        clean = []
        for f in findings[:15]:
            clean.append({
                "severity": str(f.get("severity", "info")).lower(),
                "file": str(f.get("file", "?")),
                "line": int(f.get("line", 0) or 0),
                "message": str(f.get("message", ""))[:600],
            })
        return {"summary": str(obj.get("summary", ""))[:1000], "findings": clean,
                "model": resp.get("model", model)}
    except (json.JSONDecodeError, ValueError, AttributeError, KeyError):
        raise ReviewError("The AI returned an invalid review — try again.") from None

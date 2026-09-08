"""Arena usage tracker — every LLM call is logged (tokens, never content).

Powers the Free & Local story: users SEE what each model costs and can
switch to free/local models. No prompts or responses are stored — only counts.
"""

from __future__ import annotations

import time
from typing import Any

_log: list[dict[str, Any]] = []


def record(model: str, provider: str, prompt_tokens: int = 0,
           completion_tokens: int = 0, stream: bool = False) -> None:
    _log.append({"ts": time.time(), "model": model, "provider": provider,
                 "prompt": int(prompt_tokens or 0),
                 "completion": int(completion_tokens or 0),
                 "total": int(prompt_tokens or 0) + int(completion_tokens or 0),
                 "stream": stream})
    if len(_log) > 5000:  # ring buffer
        del _log[:1000]


def summary() -> dict[str, Any]:
    by_model: dict[str, dict[str, int]] = {}
    totals = {"calls": 0, "prompt": 0, "completion": 0, "total": 0}
    for entry in _log:
        totals["calls"] += 1
        for key in ("prompt", "completion", "total"):
            totals[key] += entry[key]
        slot = by_model.setdefault(entry["model"], {"calls": 0, "prompt": 0,
                                                    "completion": 0, "total": 0})
        slot["calls"] += 1
        for key in ("prompt", "completion", "total"):
            slot[key] += entry[key]
    return {"totals": totals,
            "by_model": [{"model": m, **v} for m, v in
                         sorted(by_model.items(), key=lambda kv: -kv[1]["total"])]}


def reset() -> None:
    _log.clear()

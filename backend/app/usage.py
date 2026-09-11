"""Arena usage tracker — every LLM call is logged (tokens, never content).

Powers the Free & Local story: users SEE what each model costs (estimated
from the models.dev registry; never shown as exact) and can switch to
free/local models. No prompts or responses are stored — only counts.
"""

from __future__ import annotations

import time
from typing import Any

from . import catalog

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


def _estimate_cost(model: str, prompt: int, completion: int) -> float:
    """Estimated USD (per-1M pricing from registry). 0 when unknown — never fake."""
    try:
        in_cost, out_cost = catalog.cost_for(model)
    except Exception:  # noqa: BLE001, S110 — estimate is best-effort
        return 0.0
    return (prompt / 1_000_000 * in_cost) + (completion / 1_000_000 * out_cost)


def summary() -> dict[str, Any]:
    by_model: dict[str, dict[str, Any]] = {}
    totals = {"calls": 0, "prompt": 0, "completion": 0, "total": 0, "cost": 0.0}
    for entry in _log:
        totals["calls"] += 1
        for key in ("prompt", "completion", "total"):
            totals[key] += entry[key]
        totals["cost"] += _estimate_cost(entry["model"], entry["prompt"], entry["completion"])
        slot = by_model.setdefault(entry["model"], {"calls": 0, "prompt": 0,
                                                    "completion": 0, "total": 0, "cost": 0.0})
        slot["calls"] += 1
        for key in ("prompt", "completion", "total"):
            slot[key] += entry[key]
        slot["cost"] += _estimate_cost(entry["model"], entry["prompt"], entry["completion"])
    return {"totals": totals,
            "by_model": [{"model": m, **v} for m, v in
                         sorted(by_model.items(), key=lambda kv: -kv[1]["total"])]}


def reset() -> None:
    _log.clear()

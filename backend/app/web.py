"""Arena web tools (FreeBuff/Manus-style research): search + fetch.

Search needs: pip install ddgs  (free, no API key). Fetch needs only httpx.
"""

from __future__ import annotations

import html
import re


class WebError(Exception):
    """User-friendly web failure (safe to show in UI)."""


SEARCH_HINT = "Web search needs: pip install ddgs  (free, no API key)"


def web_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    query = (query or "").strip()
    if not query:
        raise WebError("Empty query.")
    try:
        from ddgs import DDGS
    except ImportError:
        raise WebError(SEARCH_HINT) from None
    try:
        out = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max(1, min(max_results, 10))):
                out.append({"title": str(r.get("title", ""))[:200],
                            "url": str(r.get("href", "")),
                            "snippet": str(r.get("body", ""))[:500]})
        return out
    except Exception as exc:  # noqa: BLE001 — network failure → friendly error
        raise WebError(f"Search failed: {str(exc)[:200]}") from exc


def web_fetch(url: str, max_chars: int = 8000) -> dict[str, str]:
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise WebError("URL must start with http(s).")
    import httpx

    try:
        resp = httpx.get(url, timeout=15, follow_redirects=True,
                         headers={"User-Agent": "AKDevArena/1.2"})
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — network failure → friendly error
        raise WebError(f"Fetch failed: {str(exc)[:200]}") from exc
    raw = resp.text
    title = ""
    m = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
    if m:
        title = re.sub(r"\s+", " ", html.unescape(re.sub("<[^>]+>", "", m.group(1)))).strip()[:200]
    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\s+", " ", html.unescape(txt)).strip()
    return {"url": str(resp.url), "title": title, "text": txt[:max_chars]}

"""Arena web tools (FreeBuff/Manus-style research): search + fetch.

Search needs: pip install ddgs  (free, no API key). Fetch needs only httpx.

Security: fetch is SSRF-guarded — private/loopback/link-local/metadata
addresses are rejected so the AI can't reach your local network or cloud
metadata endpoints from a user-supplied URL.
"""

from __future__ import annotations

import html
import ipaddress
import re
import socket
import urllib.parse


class WebError(Exception):
    """User-friendly web failure (safe to show in UI)."""


SEARCH_HINT = "Web search needs: pip install ddgs  (free, no API key)"


def _assert_public_url(url: str) -> None:
    """Reject URLs that resolve to private, loopback, link-local or reserved IPs."""
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").strip().lower()
    if not host:
        raise WebError("URL has no host.")
    if host in ("localhost", "0.0.0.0") or host.endswith((".local", ".internal", ".lan")):
        raise WebError("Fetching local/private addresses is not allowed.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise WebError(f"Could not resolve host: {str(exc)[:160]}") from None
    seen: set[str] = set()
    for info in infos:
        addr = info[4][0]
        if addr in seen:
            continue
        seen.add(addr)
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise WebError("Fetching local/private addresses is not allowed.")


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
    _assert_public_url(url)
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

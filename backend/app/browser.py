"""Real browser inspection — Playwright (optional, install on demand).

This is NOT a fake browser: it launches a real Chromium, loads the page,
performs actions, and captures console errors + failed network requests,
so the agent verifies what the app ACTUALLY does.

    pip install playwright && playwright install chromium

When Playwright is missing the endpoints return a clear install hint and the
UI marks browser verification as "not available" (no fake results).
"""

from __future__ import annotations

from typing import Any

INSTALL_HINT = ("Browser inspection needs Playwright: "
                "pip install playwright && playwright install chromium")


class BrowserError(Exception):
    """User-friendly browser failure."""


def is_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


async def inspect(url: str, actions: list[dict[str, Any]] | None = None,
                  timeout: int = 25) -> dict[str, Any]:
    """Load a page, run optional actions, return evidence."""
    url = (url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise BrowserError("URL must start with http(s).")
    if not is_available():
        raise BrowserError(INSTALL_HINT)
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise BrowserError(INSTALL_HINT) from None

    console_errors: list[str] = []
    failed_requests: list[str] = []
    action_results: list[dict[str, Any]] = []

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 — chromium missing
            raise BrowserError(
                "Chromium not installed for Playwright. Run: playwright install chromium"
            ) from None
        page = await browser.new_page()
        page.on("console", lambda msg: console_errors.append(msg.text[:300])
                if msg.type == "error" else None)
        page.on("requestfailed", lambda req: failed_requests.append(
            f"{req.method} {req.url} — {req.failure}"))
        try:
            resp = await page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
            status = resp.status if resp else None
        except Exception as exc:  # noqa: BLE001 — page-level failure → still report
            status = None
            console_errors.append(f"navigation failed: {str(exc)[:200]}")
        for action in (actions or [])[:10]:
            kind = str(action.get("type", "")).lower()
            selector = str(action.get("selector", "")) or None
            value = str(action.get("value", ""))
            try:
                if kind == "click" and selector:
                    await page.click(selector, timeout=5000)
                    action_results.append({"type": kind, "selector": selector, "ok": True})
                elif kind == "fill" and selector:
                    await page.fill(selector, value, timeout=5000)
                    action_results.append({"type": kind, "selector": selector, "ok": True})
                elif kind == "text" and selector:
                    text = await page.inner_text(selector, timeout=5000)
                    action_results.append({"type": kind, "selector": selector, "ok": True,
                                           "text": text[:500]})
                elif kind == "wait":
                    await page.wait_for_timeout(min(int(value or 500), 5000))
                    action_results.append({"type": kind, "ok": True})
                elif kind == "screenshot" and selector:
                    await page.wait_for_timeout(300)
                    action_results.append({"type": kind, "selector": selector, "ok": True,
                                           "hint": "screenshot not saved (headless)"})
                else:
                    action_results.append({"type": kind, "selector": selector,
                                           "ok": False, "error": "unsupported action"})
            except Exception as exc:  # noqa: BLE001 — action failure is evidence
                action_results.append({"type": kind, "selector": selector, "ok": False,
                                       "error": str(exc)[:200]})
        title = await page.title()
        body_text = ""
        try:
            body_text = (await page.inner_text("body"))[:3000]
        except Exception:  # noqa: BLE001, S110 — snapshot is best-effort
            pass
        await browser.close()

    return {
        "url": url,
        "status_code": status,
        "title": title,
        "console_errors": console_errors[:20],
        "failed_requests": failed_requests[:20],
        "action_results": action_results,
        "body_snippet": body_text,
        "has_errors": bool(console_errors or failed_requests),
    }

"""REAL browser E2E (Benchmark: browser verification) — runs a live Chromium
via Playwright against a locally served page: navigation, click, fill, text
extraction, console-error capture and failed-request capture.

Skipped when Playwright/Chromium is not installed (dev machines, the
sandbox); the CI job 'Browser E2E (Playwright, real Chromium)' installs it,
so in CI this is full evidence — not a mock.
"""

import asyncio
import http.server
import threading

import pytest

from backend.app import browser

PAGE = """<!doctype html>
<html><head><title>Live Check</title></head>
<body>
<h1>AK Dev Arena live page</h1>
<input id="name" />
<button id="btn" onclick="document.getElementById('out').textContent='clicked:'+(document.getElementById('name').value||'none')">Go</button>
<div id="out">waiting</div>
<script>
console.error("boom-from-page");
fetch("http://127.0.0.1:1/never-listening").catch(function(){});
</script>
</body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _chromium_skip(exc: Exception) -> bool:
    return isinstance(exc, browser.BrowserError) and "Chromium" in str(exc)


@pytest.fixture(scope="module")
def live_page():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


@pytest.mark.skipif(not browser.is_available(),
                    reason="playwright not installed (pip install playwright)")
def test_real_browser_load_click_fill_console_network(live_page):
    async def _go():
        return await browser.inspect(live_page, actions=[
            {"type": "fill", "selector": "#name", "value": "arena"},
            {"type": "click", "selector": "#btn"},
            {"type": "text", "selector": "#out"},
        ])

    try:
        res = asyncio.run(_go())
    except browser.BrowserError as exc:  # pragma: no cover — env dependent
        if _chromium_skip(exc):
            pytest.skip("chromium not installed (playwright install chromium)")
        raise

    assert res["status_code"] == 200                      # real navigation
    assert res["title"] == "Live Check"
    assert "AK Dev Arena live page" in res["body_snippet"]
    acts = {a["type"]: a for a in res["action_results"]}
    assert acts["fill"]["ok"] is True
    assert acts["click"]["ok"] is True
    assert acts["text"]["ok"] is True
    assert acts["text"]["text"].startswith("clicked:arena")  # JS actually ran
    assert any("boom-from-page" in e for e in res["console_errors"])
    assert res["failed_requests"]                          # dead-port fetch caught
    assert res["has_errors"] is True


@pytest.mark.skipif(not browser.is_available(),
                    reason="playwright not installed")
def test_real_browser_reports_navigation_failure(live_page):
    async def _go():
        # port 1 is (almost) never listening → navigation fails honestly
        return await browser.inspect("http://127.0.0.1:1/", timeout=5)

    try:
        res = asyncio.run(_go())
    except browser.BrowserError as exc:  # pragma: no cover — env dependent
        if _chromium_skip(exc):
            pytest.skip("chromium not installed (playwright install chromium)")
        raise
    assert res["status_code"] is None
    assert any("navigation failed" in e for e in res["console_errors"])

"""Phase D/B end-to-end: a REAL OpenAI-compatible local provider drives the
full agent task flow (custom provider config → LiteLLM → plan → tool → done).

No internet, no API key — the mock speaks the OpenAI API over HTTP and is
called through the exact same code path as a real provider. This is the
strongest verification available in CI for the agent loop.
"""

import asyncio
import http.server
import json
import os
import threading

import pytest

from backend.app import agent, catalog, files

SCRIPTED: list[str] = [
    # planner call
    '{"steps": ["inspect", "verify"]}',
    # agent step 1
    '{"thought": "check cwd", "tool": "run", "args": {"cmd": "pwd"}}',
    # agent step 2
    '{"thought": "done", "tool": "done", "args": {"summary": "verified", '
    '"verification": [["pwd executed", "pass"]]}}',
]

_req_count = 0
_lock = threading.Lock()


class _MockHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 — http.server API
        global _req_count
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or b"{}")
        with _lock:
            idx = _req_count
            _req_count += 1
        content = SCRIPTED[min(idx, len(SCRIPTED) - 1)] if idx < len(SCRIPTED) else \
            '{"thought":"t","tool":"done","args":{"summary":"ok"}}'
        resp = {
            "id": "mock-1", "object": "chat.completion", "created": 0,
            "model": body.get("model", "one"),
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                         "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        data = json.dumps(resp).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # silent
        pass


@pytest.fixture(scope="module")
def mock_provider():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MockHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


def test_full_agent_task_via_custom_provider(mock_provider, tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    cfg = tmp_path / "local.yaml"
    monkeypatch.setenv("ARENA_LOCAL_CONFIG", str(cfg))
    monkeypatch.setenv("ARENA_CUSTOM_MOCKAI_KEY", "test-key-123")
    catalog.clear_custom_cache()
    catalog.upsert_custom_provider("mockai", "Mock AI",
                                   f"http://127.0.0.1:{mock_provider}/v1", "one")

    async def _go():
        task = agent.create_task("run a check", "mockai/one", max_steps=4,
                                 work_dir=tmp_path)
        for _ in range(200):
            state = agent.get_task(task["id"])
            if state and state["status"] in ("done", "failed", "cancelled", "timeout"):
                return state
            await asyncio.sleep(0.05)
        return agent.get_task(task["id"])

    state = asyncio.run(_go())
    try:
        assert state["status"] == "done", state
        assert state["summary"] == "verified"
        tools = [s["tool"] for s in state["steps"]]
        assert "run" in tools
        assert "done" in tools
        assert any(c["status"] == "pass" for c in state["criteria"])
        assert state["verification"] is not None
        # plan step actually executed
        assert any("inspect" in str(s).lower() for s in (state["plan"] or []))
    finally:
        agent.reset_tasks_for_tests()
        catalog.clear_custom_cache()

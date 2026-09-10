"""7 mandatory E2E benchmarks (from the master plan), automated in CI.

B1 React task manager      → real build/test of a node project via execjobs
B2 Error recovery          → fail → agent fixes file → retest → verify (mock LLM,
                             REAL test executions + REAL file edits)
B3 Git safety              → covered in test_security (safe undo)
B4 Cancellation            → covered in test_agent_tasks (cancel settles)
B5 Provider failure        → provider 401/500 → friendly error, no crash
B6 Desktop recovery        → Windows CI job (cargo check + smoke) + start.bat
B7 Resource awareness      → procman orphans tracked/cleaned; workspace cleanup
"""

import asyncio
import http.server
import json
import sys
import threading
import time

import pytest

from backend.app import agent, catalog, execjobs, files, procman


# -------------------------------------------- B1: real node build/test ----


def _node_e(js: str) -> str:
    """`node -e "<js>"` that survives BOTH shells npm uses: sh (POSIX) and
    cmd.exe (Windows). cmd has no single quotes, so we escape \\" as \\\\"
    — cmd turns that into a literal quote, sh passes the backslash through."""
    return 'node -e "%s"' % js.replace('"', '\\"')


def test_b1_node_project_build_and_test(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "task-app",
        "scripts": {"build": _node_e("require('fs').writeFileSync('built.txt','ok')"),
                    "test": _node_e("process.exit(require('fs').existsSync('built.txt')?0:1)")},
        "devDependencies": {},
    }))

    async def _go(action):
        job = execjobs.start(action, str(tmp_path))
        for _ in range(600):  # ~30s budget: npm startup is slow on Windows
            state = execjobs.get(job["id"])
            if state["status"] in ("passed", "failed", "cancelled", "stopped"):
                return state
            await asyncio.sleep(0.05)
        return execjobs.get(job["id"])

    build = asyncio.run(_go("build"))
    assert build["status"] == "passed", build
    assert build["exit_code"] == 0
    assert (tmp_path / "built.txt").exists()  # real artifact produced
    test = asyncio.run(_go("test"))
    assert test["status"] == "passed", test  # test sees real build artifact


# ------------------------------------------ B2: error → fix → retest ------


SCRIPT_FIX = [
    '{"steps":["run tests","inspect","fix","retest","verify"]}',
    '{"thought":"run","tool":"run_tests","args":{}}',
    '{"thought":"inspect","tool":"read_file","args":{"path":"package.json"}}',
    '{"thought":"fix","tool":"write_file","args":{"path":"package.json",'
    '"content":"{\\"scripts\\":{\\"test\\":\\"echo fixed\\"}}"}}',
    '{"thought":"retest","tool":"run_tests","args":{}}',
    '{"thought":"verify","tool":"done","args":{"summary":"fixed and verified",'
    '"verification":[["tests pass after fix","pass"]]}}',
]


class _FixHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", "0"))
        json.loads(self.rfile.read(n) or b"{}")
        idx = int(getattr(self.server, "_idx", 0))
        self.server._idx = idx + 1  # type: ignore[attr-defined]
        content = SCRIPT_FIX[min(idx, len(SCRIPT_FIX) - 1)]
        data = json.dumps({"id": "x", "object": "chat.completion", "model": "m",
                           "choices": [{"index": 0,
                                        "message": {"role": "assistant", "content": content},
                                        "finish_reason": "stop"}],
                           "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                                     "total_tokens": 2}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_b2_error_recovery_loop(tmp_path, monkeypatch):
    """Failing test → agent inspects & edits file → retest passes → verified."""
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"test": "exit 1"}}))  # starts BROKEN (sh + cmd both)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FixHandler)
    server._idx = 0  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    cfg = tmp_path / "local.yaml"
    monkeypatch.setenv("ARENA_LOCAL_CONFIG", str(cfg))
    monkeypatch.setenv("ARENA_CUSTOM_MOCKAI_KEY", "k")
    catalog.clear_custom_cache()
    catalog.upsert_custom_provider("mockai", "Mock",
                                   f"http://127.0.0.1:{server.server_address[1]}/v1", "m")
    try:
        async def _go():
            task = agent.create_task("make tests pass", "mockai/m", max_steps=8,
                                     work_dir=tmp_path)
            for _ in range(1200):  # ~60s budget: several npm runs on Windows
                state = agent.get_task(task["id"])
                if state and state["status"] in ("done", "failed", "cancelled", "timeout"):
                    return state
                await asyncio.sleep(0.05)
            return agent.get_task(task["id"])

        state = asyncio.run(_go())
        assert state["status"] == "done", state
        tools = [s["tool"] for s in state["steps"]]
        # real loop happened: fail → inspect → fix → retest → done
        assert tools.count("run_tests") >= 2
        assert "read_file" in tools and "write_file" in tools
        # verification computed from REAL exit codes
        assert state["verification"]["tests"] == "pass"
        assert state["verification"]["has_evidence"] is True
        assert any(c["status"] == "pass" for c in state["criteria"])
    finally:
        server.shutdown()
        agent.reset_tasks_for_tests()
        catalog.clear_custom_cache()


# --------------------------------------------- B5: provider failures -------


class _FailHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(n)
        code = int(getattr(self.server, "_code", 500))
        data = json.dumps({"error": {"message": "boom", "type": "server_error"}}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_b5_provider_failure_friendly(tmp_path, monkeypatch):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _FailHandler)
    server._code = 500  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    cfg = tmp_path / "local.yaml"
    monkeypatch.setenv("ARENA_LOCAL_CONFIG", str(cfg))
    monkeypatch.setenv("ARENA_CUSTOM_MOCKAI_KEY", "k")
    catalog.clear_custom_cache()
    catalog.upsert_custom_provider("mockai", "Mock",
                                   f"http://127.0.0.1:{server.server_address[1]}/v1", "m")
    try:
        from backend.app import llm

        async def _go():
            try:
                await llm.chat_completion("mockai/m",
                                          [{"role": "user", "content": "hi"}])
                return None
            except llm.ArenaLLMError as exc:
                return str(exc)

        msg = asyncio.run(_go())
        assert msg is not None
        assert "mockai" in msg  # provider called out by name
        server._code = 401  # type: ignore[attr-defined]
        msg2 = asyncio.run(_go())
        assert "key" in msg2.lower() or "authentication" in msg2.lower()
    finally:
        server.shutdown()
        catalog.clear_custom_cache()


# --------------------------------------------- B7: resource awareness -----


def test_b7_orphans_are_tracked_and_cleaned(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    procman.reset_for_tests()
    port = procman.find_free_port()
    procman.start([sys.executable, "-m", "http.server", str(port)],
                  tmp_path, port=port, task_id="task-b7")
    procs = procman.list_processes()
    assert any(p["task_id"] == "task-b7" and p["status"] == "running"
               for p in procs)  # process visible with owner
    assert any(p["port"] == port for p in procs)  # port tracked (cleanup source)
    for _ in range(60):  # http.server needs a moment to bind
        if procman.is_port_open(port):
            break
        time.sleep(0.05)
    assert procman.is_port_open(port) is True
    assert procman.stop_all_for_task("task-b7") >= 1
    # history entry stays (status=stopped) but nothing is RUNNING — no orphan
    b7 = [p for p in procman.list_processes() if p["task_id"] == "task-b7"]
    assert b7 and all(p["status"] != "running" for p in b7)
    assert procman.is_port_open(port) is False  # port freed


def test_b7_process_tree_killed_no_orphan(tmp_path, monkeypatch):
    """npm-like wrapper (parent → server child): stopping the tracked process
    must kill the WHOLE tree — the port has to close (found via live smoke).
    The wrapper is python (not `sh -c`) so it also works on Windows."""
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    procman.reset_for_tests()
    port = procman.find_free_port()
    wrapper = (
        "import subprocess, sys; "
        f"p = subprocess.Popen([sys.executable, '-m', 'http.server', '{port}']); "
        "p.wait()"
    )
    procman.start([sys.executable, "-c", wrapper],
                  tmp_path, port=port, task_id="tree")
    for _ in range(60):
        if procman.is_port_open(port):
            break
        time.sleep(0.05)
    assert procman.is_port_open(port) is True
    procs = procman.list_processes()
    target = next(p for p in procs if p["task_id"] == "tree")
    assert procman.stop(target["id"]) is True
    time.sleep(0.5)
    assert procman.is_port_open(port) is False  # child server died with parent

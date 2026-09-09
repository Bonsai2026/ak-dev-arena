"""Phase A security tests: SSRF guard, command allowlist, safe git undo, diagnostics."""

import pytest
from fastapi.testclient import TestClient

from backend.app import agent, files, gitops, web
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    monkeypatch.setenv("ARENA_LOCAL_CONFIG", str(tmp_path / "local.yaml"))
    return tmp_path


# ------------------------------------------------------------- SSRF guard ---


def test_web_fetch_blocks_localhost():
    with pytest.raises(web.WebError):
        web.web_fetch("http://localhost:8000/health")


def test_web_fetch_blocks_loopback_ip():
    with pytest.raises(web.WebError):
        web.web_fetch("http://127.0.0.1:8000/health")


def test_web_fetch_blocks_link_local_metadata():
    with pytest.raises(web.WebError):
        web.web_fetch("http://169.254.169.254/latest/meta-data/")


def test_web_fetch_blocks_private_dns_hint():
    with pytest.raises(web.WebError):
        web.web_fetch("http://myrouter.local/status")


def test_web_fetch_blocks_non_http():
    with pytest.raises(web.WebError):
        web.web_fetch("file:///etc/passwd")


# ------------------------------------------------------- command allowlist ---


def test_command_blocks_delete():
    with pytest.raises(agent.AgentError):
        agent.run_command("rm -rf /", cwd=files.WORKSPACE)


def test_command_blocks_absolute_read():
    with pytest.raises(agent.AgentError):
        agent.run_command("cat /etc/passwd", cwd=files.WORKSPACE)


def test_command_blocks_traversal_read():
    with pytest.raises(agent.AgentError):
        agent.run_command("cat ../secret.txt", cwd=files.WORKSPACE)


def test_command_blocks_git_push_and_install():
    with pytest.raises(agent.AgentError):
        agent.run_command("git push origin main", cwd=files.WORKSPACE)
    with pytest.raises(agent.AgentError):
        agent.run_command("npm install axios", cwd=files.WORKSPACE)
    with pytest.raises(agent.AgentError):
        agent.run_command("pip install requests", cwd=files.WORKSPACE)


def test_command_blocks_shell_metacharacters():
    with pytest.raises(agent.AgentError):
        agent.run_command("echo hi; rm -rf /", cwd=files.WORKSPACE)
    with pytest.raises(agent.AgentError):
        agent.run_command("echo hi > /tmp/x", cwd=files.WORKSPACE)


def test_command_allows_safe_echo(ws):
    out = agent.run_command("echo arena-safe", cwd=ws)
    assert "arena-safe" in out


def test_command_blocks_python_file_exec():
    with pytest.raises(agent.AgentError):
        agent.run_command("python app.py", cwd=files.WORKSPACE)


# ----------------------------------------------------------- safe git undo ---


def test_git_undo_refuses_dirty_tree(ws, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", ws)
    (ws / "base.txt").write_text("v1\n")
    client.post("/api/git/checkpoint", json={"message": "base"})
    # user modifies a file but does NOT checkpoint — undo must refuse
    (ws / "user.txt").write_text("my work, don't lose me\n")
    res = client.post("/api/git/undo", json={})
    assert res.status_code == 400
    assert "uncommitted" in res.json()["detail"].lower()
    assert (ws / "user.txt").read_text() == "my work, don't lose me\n"


def test_git_undo_creates_backup_branch(ws, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", ws)
    (ws / "a.txt").write_text("v1\n")
    client.post("/api/git/checkpoint", json={"message": "first"})
    (ws / "a.txt").write_text("v2\n")
    client.post("/api/git/checkpoint", json={"message": "second"})
    res = client.post("/api/git/undo", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["undone"] is True
    assert body.get("backup", "").startswith("arena-undo-backup-")
    # backup branch exists with the reverted state
    import subprocess
    branches = subprocess.run(["git", "branch", "--list", body["backup"]],
                              cwd=ws, capture_output=True, text=True).stdout
    assert body["backup"] in branches


# ------------------------------------------------------------ diagnostics ---


def test_diagnostics_endpoint(ws, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", ws)
    res = client.get("/api/diagnostics")
    assert res.status_code == 200
    body = res.json()
    for key in ("workspace", "python", "node", "git", "ollama",
                "providers_total", "providers_configured", "version"):
        assert key in body
    assert body["workspace"]["path"] == str(ws)


# -------------------------------------------------------------- CORS check ---


def test_cors_not_wildcard():
    # the middleware must not allow arbitrary origins anymore
    for mw in app.user_middleware:
        if mw.cls.__name__ == "CORSMiddleware":
            kwargs = mw.kwargs
            assert kwargs["allow_origins"] != ["*"]
            assert "http://localhost:1420" in kwargs["allow_origins"]
            return
    raise AssertionError("CORSMiddleware not found")

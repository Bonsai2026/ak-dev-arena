"""LAN auth — when ARENA_TOKEN is set, /api calls need it; loopback default
stays zero-config; /api/health stays open for readiness probes."""

import pytest
from fastapi.testclient import TestClient

from backend.app import files
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    return tmp_path


def test_no_token_by_default_open(ws, monkeypatch):
    import backend.app.main as m
    monkeypatch.setattr(m, "ARENA_TOKEN", "")
    assert client.get("/api/workspace").status_code == 200


def test_token_required_when_set(ws, monkeypatch):
    import backend.app.main as m
    monkeypatch.setattr(m, "ARENA_TOKEN", "sekrit")
    # no header → rejected
    assert client.get("/api/workspace").status_code == 401
    # wrong token → rejected
    r = client.get("/api/workspace", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401
    # right token → allowed
    r = client.get("/api/workspace", headers={"Authorization": "Bearer sekrit"})
    assert r.status_code == 200
    # header-style token also works (for tools that can't set Authorization)
    r = client.get("/api/workspace", headers={"X-Arena-Token": "sekrit"})
    assert r.status_code == 200


def test_health_open_even_with_token(ws, monkeypatch):
    import backend.app.main as m
    monkeypatch.setattr(m, "ARENA_TOKEN", "sekrit")
    assert client.get("/health").status_code == 200

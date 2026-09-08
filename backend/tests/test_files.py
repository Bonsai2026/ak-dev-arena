"""Code Mode tests: file tools, diff preview/apply, git checkpoints."""

import pytest
from fastapi.testclient import TestClient

from backend.app import files, gitops
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(files, "WORKSPACE", tmp_path)
    (tmp_path / "hello.py").write_text("print('hi')\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "notes.txt").write_text("alpha\nbeta\n")
    return tmp_path


def test_list_and_read(ws):
    res = client.get("/api/files", params={"path": ""})
    assert res.status_code == 200
    names = {e["name"] for e in res.json()["entries"]}
    assert {"hello.py", "sub"} <= names

    res = client.get("/api/files/read", params={"path": "hello.py"})
    assert res.status_code == 200
    assert "print" in res.json()["content"]


def test_path_traversal_blocked(ws):
    res = client.get("/api/files/read", params={"path": "../secret.txt"})
    assert res.status_code == 400


def test_write_and_search(ws):
    res = client.post("/api/files/write", json={"path": "a/b.txt", "content": "needle here"})
    assert res.status_code == 200
    res = client.get("/api/files/search", params={"q": "needle"})
    assert res.status_code == 200
    assert res.json()["hits"][0]["path"] == "a/b.txt"


def test_edit_preview_then_apply(ws):
    preview = client.post("/api/files/edit/preview", json={
        "path": "hello.py", "old_text": "print('hi')", "new_text": "print('hello arena')"})
    assert preview.status_code == 200
    assert "hello arena" in preview.json()["diff"]
    assert "hello arena" not in (ws / "hello.py").read_text()  # preview writes nothing

    applied = client.post("/api/files/edit/apply", json={
        "path": "hello.py", "old_text": "print('hi')", "new_text": "print('hello arena')"})
    assert applied.status_code == 200
    assert applied.json()["applied"] is True
    assert "hello arena" in (ws / "hello.py").read_text()


def test_edit_missing_old_text(ws):
    res = client.post("/api/files/edit/apply", json={
        "path": "hello.py", "old_text": "nope", "new_text": "x"})
    assert res.status_code == 400


def test_git_checkpoint_and_undo(ws):
    res = client.post("/api/git/checkpoint", json={"message": "first"})
    assert res.status_code == 200
    assert res.json()["hash"]

    (ws / "hello.py").write_text("changed\n")
    client.post("/api/git/checkpoint", json={"message": "second"})

    res = client.post("/api/git/undo", json={})
    assert res.status_code == 200
    assert res.json()["undone"] is True
    assert (ws / "hello.py").read_text() == "print('hi')\n"


def test_git_status(ws):
    res = client.get("/api/git/status")
    assert res.status_code == 200
    assert res.json()["is_repo"] is False
    assert gitops.is_repo(root=ws) is False

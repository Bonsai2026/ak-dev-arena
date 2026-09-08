"""Review Mode tests with mocked LLM."""

import json

import pytest
from fastapi.testclient import TestClient

from backend.app import llm
from backend.app.main import app

client = TestClient(app)


@pytest.fixture()
def mock_review(monkeypatch):
    async def _fake(model, messages, max_tokens=2000, temperature=0.2):
        return {"content": json.dumps({
            "summary": "One SQL injection risk found.",
            "findings": [{"severity": "critical", "file": "db.py", "line": 12,
                           "message": "Use parameterized queries."}]}),
            "model": model, "provider": "mock", "usage": {}}

    monkeypatch.setattr(llm, "chat_completion", _fake)


def test_review_returns_findings(mock_review):
    res = client.post("/api/review", json={
        "model": "gpt-4o-mini", "diff": "--- a/db.py\n+++ b/db.py\n+q = f'SELECT * FROM u WHERE n={name}'"})
    assert res.status_code == 200
    body = res.json()
    assert body["findings"][0]["severity"] == "critical"
    assert "SQL injection" in body["summary"]


def test_review_rejects_empty_diff(mock_review):
    res = client.post("/api/review", json={"model": "gpt-4o-mini", "diff": "  "})
    assert res.status_code == 400

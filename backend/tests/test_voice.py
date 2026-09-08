"""Voice Mode tests: graceful degradation + mocked engines."""

import pytest
from fastapi.testclient import TestClient

from backend.app import voice
from backend.app.main import app

client = TestClient(app)


def test_transcribe_without_engine_gives_install_hint():
    """faster-whisper is NOT in requirements → expect friendly 400."""
    try:
        import faster_whisper  # noqa: F401
        pytest.skip("engine installed in this env")
    except ImportError:
        pass
    res = client.post("/api/voice/transcribe",
                      files={"audio": ("x.webm", b"fake-bytes", "audio/webm")})
    assert res.status_code == 400
    assert "faster-whisper" in res.json()["detail"]


def test_transcribe_mocked_engine(monkeypatch):
    async def _fake(audio, filename="audio.webm"):
        return {"text": "hello arena", "language": "en", "duration": 1.0}

    monkeypatch.setattr(voice, "transcribe_bytes", _fake)
    res = client.post("/api/voice/transcribe",
                      files={"audio": ("x.webm", b"fake-bytes", "audio/webm")})
    assert res.status_code == 200
    assert res.json()["text"] == "hello arena"


def test_speak_without_engine_gives_install_hint():
    try:
        import edge_tts  # noqa: F401
        pytest.skip("engine installed in this env")
    except ImportError:
        pass
    res = client.post("/api/voice/speak", json={"text": "hi"})
    assert res.status_code == 400
    assert "edge-tts" in res.json()["detail"]


def test_speak_mocked_engine(monkeypatch):
    async def _fake(text, voice="en-US-AriaNeural"):
        return b"ID3fake-mp3"

    monkeypatch.setattr(voice, "speak_bytes", _fake)
    res = client.post("/api/voice/speak", json={"text": "hi"})
    assert res.status_code == 200
    assert res.headers["content-type"] == "audio/mpeg"
    assert res.content.startswith(b"ID3")

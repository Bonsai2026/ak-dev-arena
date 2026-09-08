"""Arena Voice Mode — speech-to-text and text-to-speech engines.

Engines are OPTIONAL dependencies (kept out of requirements.txt so the core
app stays light). If missing, endpoints return a clear install hint instead
of crashing:
  - STT: pip install faster-whisper   (local, free, offline)
  - TTS: pip install edge-tts         (free, needs internet)
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path


class VoiceError(Exception):
    """User-friendly voice failure (safe to show in UI)."""


STT_HINT = ("Voice engine not installed. Run: pip install faster-whisper "
            "(first run downloads a small model, then works offline).")
TTS_HINT = "Voice speaker not installed. Run: pip install edge-tts"


async def transcribe_bytes(audio: bytes, filename: str = "audio.webm") -> dict:
    """Speech → text with local Faster-Whisper (tiny model)."""
    if not audio:
        raise VoiceError("Empty audio.")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise VoiceError(STT_HINT) from None
    suffix = Path(filename).suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio)
        tmp_path = tmp.name
    try:
        model = WhisperModel("tiny", device="cpu", compute_type="int8")

        def _run():
            segments, info = model.transcribe(tmp_path)
            text = " ".join(s.text for s in segments).strip()
            return {"text": text, "language": info.language,
                    "duration": round(info.duration, 1)}

        return await asyncio.to_thread(_run)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def speak_bytes(text: str, voice: str = "en-US-AriaNeural") -> bytes:
    """Text → speech (MP3) with Edge-TTS."""
    text = (text or "").strip()
    if not text:
        raise VoiceError("Empty text.")
    try:
        import edge_tts
    except ImportError:
        raise VoiceError(TTS_HINT) from None
    communicate = edge_tts.Communicate(text[:1000], voice)
    chunks = []
    async for piece in communicate.stream():
        if piece["type"] == "audio":
            chunks.append(piece["data"])
    if not chunks:
        raise VoiceError("TTS returned no audio.")
    return b"".join(chunks)

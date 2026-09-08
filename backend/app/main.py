"""AK Dev Arena — FastAPI server (the brain's front door).

Run:
    python -m uvicorn backend.app.main:app --port 8000
API docs:
    http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import __version__, config, llm, vault

app = FastAPI(title="AK Dev Arena", version=__version__)

# Local dev: the Vite/Tauri UI talks to this server on localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------- models ---


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=100_000)


class ChatRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    messages: list[Message] = Field(min_length=1, max_length=200)
    max_tokens: int = Field(default=2048, ge=1, le=128_000)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class KeyRequest(BaseModel):
    provider: str = Field(min_length=1, max_length=50)
    key: str = Field(min_length=4, max_length=500)


# ---------------------------------------------------------------- routes ---


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/config")
def get_public_config() -> dict[str, Any]:
    return config.get_config().safe_dict()


@app.get("/api/models")
def list_models() -> dict[str, Any]:
    cfg = config.get_config()
    models = []
    for entry in llm.MODEL_CATALOG:
        models.append({**entry, "configured": vault.is_configured(entry["provider"])})
    return {"models": models, "defaults": cfg.default_models}


@app.get("/api/providers")
def list_providers() -> dict[str, Any]:
    return {"providers": vault.provider_status()}


@app.post("/api/keys")
def save_key(body: KeyRequest) -> dict[str, Any]:
    try:
        vault.set_key(body.provider, body.key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"saved": True, "provider": body.provider.lower()}


@app.delete("/api/keys/{provider}")
def remove_key(provider: str) -> dict[str, Any]:
    return {"deleted": vault.delete_key(provider), "provider": provider.lower()}


@app.post("/api/chat")
async def chat(body: ChatRequest) -> dict[str, Any]:
    try:
        return await llm.chat_completion(
            model=body.model,
            messages=[m.model_dump() for m in body.messages],
            max_tokens=body.max_tokens,
            temperature=body.temperature,
        )
    except llm.ArenaLLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/chat/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    async def event_generator():
        try:
            async for token in llm.chat_stream(
                model=body.model,
                messages=[m.model_dump() for m in body.messages],
                max_tokens=body.max_tokens,
                temperature=body.temperature,
            ):
                yield f"data: {json.dumps({'token': token})}\n\n"
        except llm.ArenaLLMError as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

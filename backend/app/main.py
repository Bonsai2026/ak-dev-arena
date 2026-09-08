"""AK Dev Arena — FastAPI server (the brain's front door).

Run:
    python -m uvicorn backend.app.main:app --port 8000
API docs:
    http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from . import (
    __version__,
    agent,
    builder,
    catalog,
    config,
    files,
    gitops,
    llm,
    manager,
    review,
    usage,
    vault,
    voice,
)

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


class WriteRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=1_000_000)


class EditRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    old_text: str = Field(max_length=500_000)
    new_text: str = Field(max_length=500_000)


class CheckpointRequest(BaseModel):
    path: str = Field(default="", max_length=500)
    message: str = Field(default="arena: checkpoint", max_length=200)


class UndoRequest(BaseModel):
    path: str = Field(default="", max_length=500)


class AgentRequest(BaseModel):
    task: str = Field(min_length=1, max_length=20_000)
    model: str = Field(default="", max_length=200)
    max_steps: int = Field(default=8, ge=1, le=25)


class JobRequest(BaseModel):
    task: str = Field(min_length=1, max_length=20_000)
    model: str = Field(default="", max_length=200)
    max_steps: int = Field(default=8, ge=1, le=25)


class GenerateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    template: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=2000)


class FixRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    error: str = Field(min_length=1, max_length=10_000)
    model: str = Field(default="", max_length=200)


class ReviewRequest(BaseModel):
    diff: str = Field(max_length=50_000)
    model: str = Field(default="", max_length=200)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    voice: str = Field(default="en-US-AriaNeural", max_length=100)


# --------------------------------------------------------------- helpers ---


def _default_model(mode: str) -> str:
    return config.get_config().default_models.get(mode, "gpt-4o-mini")


def _record_usage(result: dict[str, Any], stream: bool = False) -> None:
    counts = result.get("usage", {}) if isinstance(result, dict) else {}
    usage.record(
        model=str(result.get("model", "?")),
        provider=str(result.get("provider", "?")),
        prompt_tokens=int(counts.get("prompt_tokens", 0) or 0),
        completion_tokens=int(counts.get("completion_tokens", 0) or 0),
        stream=stream,
    )


# ---------------------------------------------------------- core routes ---


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.get("/api/config")
def get_public_config() -> dict[str, Any]:
    return config.get_config().safe_dict()


@app.get("/api/models")
def list_models(provider: str = "", search: str = "", free_only: bool = False,
                limit: int = 500) -> dict[str, Any]:
    cfg = config.get_config()
    entries = catalog.models(provider=provider, search=search, free_only=free_only,
                             limit=max(1, min(limit, 2000)))
    if not entries and not provider and not search and not free_only:
        entries = [{**m, "free": False, "tool_call": True, "reasoning": False,
                    "context": 0} for m in llm.FALLBACK_CATALOG]
    for entry in entries:
        entry["configured"] = vault.is_configured(entry["provider"])
    total_all = sum(p.get("model_count", 0) for p in catalog.providers())
    return {"models": entries, "defaults": cfg.default_models, "total": len(entries),
            "catalog_total": total_all}


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


@app.post("/api/catalog/refresh")
def api_catalog_refresh() -> dict[str, Any]:
    try:
        return catalog.refresh()
    except catalog.CatalogError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ---------------------------------------------------------- chat routes ---


@app.post("/api/chat")
async def chat(body: ChatRequest) -> dict[str, Any]:
    try:
        result = await llm.chat_completion(
            model=body.model,
            messages=[m.model_dump() for m in body.messages],
            max_tokens=body.max_tokens,
            temperature=body.temperature,
        )
    except llm.ArenaLLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _record_usage(result)
    return result


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
            _record_usage({"model": body.model,
                           "provider": llm.provider_for_model(body.model)}, stream=True)
        except llm.ArenaLLMError as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ----------------------------------------------------- code mode routes ---


@app.get("/api/files")
def api_list_files(path: str = "") -> dict[str, Any]:
    try:
        return {"entries": files.list_files(path)}
    except files.FileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/files/read")
def api_read_file(path: str = "") -> dict[str, Any]:
    try:
        return files.read_file(path)
    except files.FileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/files/write")
def api_write_file(body: WriteRequest) -> dict[str, Any]:
    try:
        return files.write_file(body.path, body.content)
    except files.FileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/files/search")
def api_search(q: str = "", path: str = "") -> dict[str, Any]:
    try:
        return {"hits": files.search(q, path)}
    except files.FileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/files/edit/preview")
def api_edit_preview(body: EditRequest) -> dict[str, Any]:
    try:
        current = files.read_file(body.path)["content"]
        if not body.old_text or body.old_text not in current:
            raise files.FileError("old_text not found in file.")
        return {"path": body.path,
                "diff": files.make_diff(body.path, current,
                                        current.replace(body.old_text, body.new_text, 1)),
                "applied": False}
    except files.FileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/files/edit/apply")
def api_edit_apply(body: EditRequest) -> dict[str, Any]:
    try:
        return files.apply_edit(body.path, body.old_text, body.new_text)
    except files.FileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/git/status")
def api_git_status(path: str = "") -> dict[str, Any]:
    try:
        return gitops.status(path)
    except gitops.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/git/checkpoint")
def api_git_checkpoint(body: CheckpointRequest) -> dict[str, Any]:
    try:
        return gitops.checkpoint(body.path, body.message)
    except gitops.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/git/undo")
def api_git_undo(body: UndoRequest) -> dict[str, Any]:
    try:
        return gitops.undo(body.path)
    except gitops.GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------- agent mode routes ---


@app.post("/api/agent/run")
async def api_agent_run(body: AgentRequest) -> dict[str, Any]:
    model = body.model or _default_model("agent")
    return await agent.run_agent(body.task, model, body.max_steps)


# ------------------------------------------------------ manager routes ---


@app.post("/api/jobs")
async def api_job_create(body: JobRequest) -> dict[str, Any]:
    # async so background job tasks attach to the running event loop
    model = body.model or _default_model("agent")
    return manager.create_job(body.task, model, body.max_steps)


@app.get("/api/jobs")
def api_job_list() -> dict[str, Any]:
    return {"jobs": manager.list_jobs()}


@app.get("/api/jobs/{job_id}")
def api_job_get(job_id: str) -> dict[str, Any]:
    job = manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.delete("/api/jobs/{job_id}")
def api_job_cancel(job_id: str) -> dict[str, Any]:
    return {"cancelled": manager.cancel_job(job_id), "id": job_id}


# -------------------------------------------------------- build routes ---


@app.get("/api/build/templates")
def api_build_templates() -> dict[str, Any]:
    return {"templates": builder.list_templates()}


@app.post("/api/build/generate")
def api_build_generate(body: GenerateRequest) -> dict[str, Any]:
    try:
        return builder.generate(body.name, body.template, body.description)
    except builder.BuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/build/list")
def api_build_list() -> dict[str, Any]:
    return {"builds": builder.list_builds()}


@app.post("/api/build/fix")
async def api_build_fix(body: FixRequest) -> dict[str, Any]:
    model = body.model or _default_model("build")
    try:
        return await builder.fix_build(body.name, body.error, model)
    except builder.BuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except llm.ArenaLLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ------------------------------------------------------- review routes ---


@app.post("/api/review")
async def api_review(body: ReviewRequest) -> dict[str, Any]:
    model = body.model or _default_model("code")
    try:
        return await review.review_diff(body.diff, model)
    except review.ReviewError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except llm.ArenaLLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# -------------------------------------------------------- voice routes ---


@app.post("/api/voice/transcribe")
async def api_transcribe(audio: UploadFile = File(...)) -> dict[str, Any]:
    try:
        raw = await audio.read()
        return await voice.transcribe_bytes(raw, audio.filename or "audio.webm")
    except voice.VoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/voice/speak")
async def api_speak(body: SpeakRequest) -> Response:
    try:
        mp3 = await voice.speak_bytes(body.text, body.voice)
    except voice.VoiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=mp3, media_type="audio/mpeg")


# -------------------------------------------------------- usage routes ---


@app.get("/api/usage")
def api_usage() -> dict[str, Any]:
    return usage.summary()


@app.delete("/api/usage")
def api_usage_reset() -> dict[str, Any]:
    usage.reset()
    return {"reset": True}

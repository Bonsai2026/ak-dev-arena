"""AK Dev Arena — FastAPI server (the brain's front door).

Run:
    python -m uvicorn backend.app.main:app --port 8000
API docs:
    http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from typing import Any, Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

# -------------------------------------------------------------------------
# Logging — structured-ish, secret-free. API keys are NEVER logged (the vault
# injects them directly into LLM calls and nothing here prints request bodies).
# -------------------------------------------------------------------------
logging.basicConfig(
    level=os.environ.get("ARENA_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("akdevstudio")

from . import (
    __version__,
    agent,
    aider_engine,
    browser,
    builder,
    catalog,
    config,
    contextx,
    execjobs,
    files,
    gitops,
    llm,
    manager,
    mcp_client,
    profiles,
    review,
    slash,
    store,
    todos,
    usage,
    vault,
    voice,
    web,
    workflows,
    workspacex,
)

app = FastAPI(title="AK Dev Studio", version=__version__)


@app.on_event("startup")
def _restore_persisted_state() -> None:
    """Bring back agent tasks + run-job history from the last session.
    Anything that was mid-flight is honestly marked 'interrupted'."""
    try:
        store.restore_state()
    except Exception:  # noqa: BLE001, S110 — persistence must never break boot
        pass


# Security: only the app's own UI origins may call the API. Override for extra
# origins (e.g. a LAN/Tauri build) via ARENA_CORS_ORIGINS="a,b,c".
DEFAULT_CORS = (
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
)
CORS_ORIGINS = [o.strip() for o in
                os.environ.get("ARENA_CORS_ORIGINS", ",".join(DEFAULT_CORS)).split(",")
                if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# LAN/shared-host protection: when ARENA_TOKEN is set, every /api call needs
# `Authorization: Bearer <token>` (or X-Arena-Token). Loopback-only setups can
# leave it unset and keep the zero-config flow. /api/health stays open so the
# desktop shell / start.bat can still probe readiness.
ARENA_TOKEN = os.environ.get("ARENA_TOKEN", "").strip()
# Paths that never need the token (readiness probes, nothing sensitive).
# (/health is outside /api/* so it's open anyway; /api/health kept as alias.)
TOKEN_OPEN_PATHS = {"/api/health", "/health"}


@app.middleware("http")
async def _token_guard(request: Request, call_next):  # noqa: ANN001
    if ARENA_TOKEN and request.url.path.startswith("/api/"):
        if request.method != "OPTIONS" and request.url.path not in TOKEN_OPEN_PATHS:
            header = request.headers.get("authorization", "")
            provided = ""
            if header.lower().startswith("bearer "):
                provided = header.split(" ", 1)[1].strip()
            provided = provided or request.headers.get("x-arena-token", "").strip()
            # EventSource can't set headers → accept ?token= for SSE endpoints.
            provided = provided or (request.query_params.get("token") or "").strip()
            if not hmac.compare_digest(provided, ARENA_TOKEN):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Missing or wrong ARENA_TOKEN "
                                       "(send 'Authorization: Bearer <token>')."})
    return await call_next(request)

COMPOSER_PROMPT = """You output multi-file patches as EXACTLY ONE JSON object, no other text:
{"patches": [{"path": "relative/path", "old_text": "exact snippet to replace", "new_text": "replacement"}]}
Rules: old_text must match the file EXACTLY. For a NEW file use old_text "" (empty). Only needed files."""


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


class InstructionsBody(BaseModel):
    content: str = Field(max_length=50_000)


class RulesBody(BaseModel):
    content: str = Field(max_length=20_000)


class AgentRequest(BaseModel):
    task: str = Field(min_length=1, max_length=20_000)
    model: str = Field(default="", max_length=200)
    max_steps: int = Field(default=8, ge=1, le=25)
    profile: str = Field(default="coder", max_length=20)
    auto_commit: bool = False  # commit ONLY if task finishes verified


class ContinueRequest(BaseModel):
    follow_up: str = Field(min_length=1, max_length=20_000)
    model: str = Field(default="", max_length=200)
    max_steps: int = Field(default=8, ge=1, le=25)


class PlanRequest(BaseModel):
    task: str = Field(min_length=1, max_length=20_000)
    model: str = Field(default="", max_length=200)


class ApproveRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=50)
    minutes: int = Field(default=10, ge=1, le=120)


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


class ComposerRequest(BaseModel):
    instructions: str = Field(min_length=1, max_length=20_000)
    model: str = Field(default="", max_length=200)


class ComposerPatch(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    old_text: str = Field(max_length=500_000)
    new_text: str = Field(max_length=500_000)


class ComposerApply(BaseModel):
    patches: list[ComposerPatch] = Field(min_length=1, max_length=50)


class CompleteRequest(BaseModel):
    file: str = Field(default="", max_length=500)
    prefix: str = Field(min_length=1, max_length=20_000)
    suffix: str = Field(default="", max_length=20_000)
    model: str = Field(default="", max_length=200)


class SlashRun(BaseModel):
    command: str = Field(min_length=1, max_length=50)
    args: str = Field(default="", max_length=5000)
    model: str = Field(default="", max_length=200)


class McpCall(BaseModel):
    server: str = Field(min_length=1, max_length=100)
    tool: str = Field(min_length=1, max_length=200)
    args: dict[str, Any] = Field(default_factory=dict)


class TodoCreate(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    job: str = Field(default="", max_length=50)


class TodoPatch(BaseModel):
    done: bool = True


class WorkflowStep(BaseModel):
    task: str = Field(min_length=1, max_length=2000)
    profile: str = Field(default="coder", max_length=20)
    max_steps: int = Field(default=6, ge=1, le=25)


class WorkflowSave(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    steps: list[WorkflowStep] = Field(min_length=1, max_length=20)


class WorkflowRun(BaseModel):
    model: str = Field(default="", max_length=200)


class WebSearchReq(BaseModel):
    q: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=10)


class WebFetchReq(BaseModel):
    url: str = Field(min_length=10, max_length=2000)


class RunReq(BaseModel):
    action: Literal["install", "build", "test", "serve"] = "build"
    path: str = Field(default="", max_length=500)
    port: int | None = Field(default=None, ge=1024, le=65535)
    timeout: int = Field(default=600, ge=10, le=3600)


class CleanupReq(BaseModel):
    max_age_hours: int = Field(default=24, ge=1, le=720)
    max_bytes: int = Field(default=200 * 1024 * 1024, ge=0, le=10**11)


class BrowserInspectReq(BaseModel):
    url: str = Field(min_length=10, max_length=2000)
    actions: list[dict[str, Any]] = Field(default_factory=list, max_length=10)


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


@app.get("/api/diagnostics")
def diagnostics() -> dict[str, Any]:
    """Environment health: what AK Dev Studio can actually use right now."""
    import shutil
    import subprocess

    def _which(name: str) -> bool:
        return shutil.which(name) is not None

    def _ver(cmd: list[str]) -> str:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            return (out.stdout or out.stderr).strip().splitlines()[0][:80]
        except Exception:  # noqa: BLE001, S110 — diagnostics must never crash
            return ""

    ws = files._root(None)  # noqa: SLF001 — same package
    writable = os.access(ws, os.W_OK)
    ollama = False
    try:
        import httpx

        r = httpx.get(catalog.OLLAMA_BASE + "/api/tags", timeout=1.5)
        ollama = r.status_code == 200
    except Exception:  # noqa: BLE001, S110 — ollama is optional
        pass
    providers_status = vault.provider_status()
    configured = [p for p in providers_status if p.get("configured")]
    return {
        "version": __version__,
        "workspace": {"path": str(ws), "writable": writable},
        "python": _which("python") or _which("python3"),
        "node": _which("node"),
        "npm": _which("npm"),
        "git": _which("git"),
        "ollama": ollama,
        "ollama_base": catalog.OLLAMA_BASE,
        "providers_total": len(providers_status),
        "providers_configured": len(configured),
        "provider_names": [p.get("provider") for p in configured],
        "hints": [] if writable else ["Workspace is not writable."],
    }


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


# ------------------------------------------------ custom providers ---
# OpenAI-compatible endpoints saved in config.local.yaml (API keys go to the
# vault under ARENA_CUSTOM_<ID>_KEY). Base URLs are normalized (no double /v1).


class CustomProviderRequest(BaseModel):
    id: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(default="", max_length=100)
    base_url: str = Field(min_length=1, max_length=500)
    model: str = Field(default="", max_length=200)


@app.get("/api/providers/custom")
def list_custom_providers() -> dict[str, Any]:
    return {"providers": list(catalog.custom_providers().values())}


@app.post("/api/providers/custom")
def create_custom_provider(body: CustomProviderRequest) -> dict[str, Any]:
    try:
        return {"provider": catalog.upsert_custom_provider(
            body.id, body.name, body.base_url, body.model)}
    except catalog.CatalogError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/providers/custom/{provider_id}")
def delete_custom_provider(provider_id: str) -> dict[str, Any]:
    return {"deleted": catalog.remove_custom_provider(provider_id),
            "id": provider_id.lower()}


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
        messages = contextx.inject_context([m.model_dump() for m in body.messages])
        result = await llm.chat_completion(
            model=body.model, messages=messages,
            max_tokens=body.max_tokens, temperature=body.temperature)
    except llm.ArenaLLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _record_usage(result)
    return result


@app.post("/api/chat/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    try:
        messages = contextx.inject_context([m.model_dump() for m in body.messages])
    except Exception as exc:  # noqa: BLE001 — context failure → friendly error
        async def _err():
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    async def event_generator():
        try:
            async for token in llm.chat_stream(
                model=body.model, messages=messages,
                max_tokens=body.max_tokens, temperature=body.temperature,
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


@app.get("/api/code/repomap")
def api_repomap(path: str = "") -> dict[str, Any]:
    try:
        return aider_engine.repo_map(path)
    except files.FileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/code/composer")
async def api_composer(body: ComposerRequest) -> dict[str, Any]:
    model = body.model or _default_model("code")
    tree = contextx._tree_text(None)  # noqa: SLF001 — same package
    try:
        messages = contextx.inject_context([
            {"role": "system", "content": COMPOSER_PROMPT},
            {"role": "user", "content": f"WORKSPACE TREE:\n{tree}\n\nTASK:\n{body.instructions}"},
        ])
        resp = await llm.chat_completion(model, messages, max_tokens=3000, temperature=0.2)
    except llm.ArenaLLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raw = resp.get("content", "")
    try:
        obj = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
        patches = obj.get("patches", [])
        if not isinstance(patches, list):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400,
                            detail="The AI returned an invalid patch set — try again.") from None
    out = []
    for p in patches[:20]:
        path = str(p.get("path", "")).lstrip("/")
        old, new = str(p.get("old_text", "")), str(p.get("new_text", ""))
        try:
            current = files.read_file(path)["content"]
            exists = True
        except files.FileError:
            current, exists = "", False
        if not exists and not old:
            out.append({"path": path, "diff": f"(new file {path}, {len(new)} chars)",
                        "ok": True, "error": "", "old_text": old, "new_text": new})
        elif not old or old not in current:
            out.append({"path": path, "diff": "", "ok": False,
                        "error": "old_text not found — file may have changed.",
                        "old_text": old, "new_text": new})
        else:
            out.append({"path": path,
                        "diff": files.make_diff(path, current, current.replace(old, new, 1)),
                        "ok": True, "error": "", "old_text": old, "new_text": new})
    return {"patches": out, "applied": False}


@app.post("/api/code/composer/apply")
def api_composer_apply(body: ComposerApply) -> dict[str, Any]:
    applied, failed = [], []
    for p in body.patches:
        try:
            try:
                files.read_file(p.path)
                exists = True
            except files.FileError:
                exists = False
            if not exists and not p.old_text:
                files.write_file(p.path, p.new_text)
            else:
                files.apply_edit(p.path, p.old_text, p.new_text)
            applied.append(p.path)
        except files.FileError as exc:
            failed.append({"path": p.path, "error": str(exc)})
    checkpoint = None
    if applied:
        try:
            checkpoint = gitops.checkpoint("", "arena: composer apply").get("hash")
        except gitops.GitError:
            pass
    return {"applied": applied, "failed": failed, "checkpoint": checkpoint}


@app.post("/api/code/complete")
async def api_complete(body: CompleteRequest) -> dict[str, Any]:
    model = body.model or _default_model("chat")
    try:
        resp = await llm.chat_completion(model, [
            {"role": "system", "content": "You are a code autocomplete engine. Reply with ONLY the completion text — no quotes, no backticks, no explanation."},
            {"role": "user", "content": f"File: {body.file or 'untitled'}\n<BEFORE>\n{body.prefix[-3000:]}\n<AFTER>\n{(body.suffix or '')[:1000]}"},
        ], max_tokens=256, temperature=0.2)
    except llm.ArenaLLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"suggestion": (resp.get("content") or "").strip()}


@app.get("/api/context/rules")
def api_rules() -> dict[str, Any]:
    rules = contextx.load_rules()
    return {"rules": rules, "found": bool(rules)}


@app.get("/api/context/instructions")
def api_instructions() -> dict[str, Any]:
    """Chat instructions: global (user-level) + project (.akrules) — Cursor/Claude/Codex-style."""
    return contextx.rules_summary()


@app.put("/api/context/instructions")
def api_save_instructions(body: InstructionsBody) -> dict[str, Any]:
    """Save user-level chat instructions (persisted in git-ignored config.local.yaml)."""
    contextx.save_global_instructions(body.content)
    return contextx.rules_summary()


@app.post("/api/context/rules")
def api_save_rules(body: RulesBody) -> dict[str, Any]:
    """Save project rules to .akrules in the workspace root."""
    contextx.save_rules(body.content)
    return contextx.rules_summary()


@app.delete("/api/context/rules")
def api_delete_rules() -> dict[str, Any]:
    contextx.delete_rules()
    return contextx.rules_summary()


# ---------------------------------------------------- agent mode routes ---


@app.post("/api/agent/run")
async def api_agent_run(body: AgentRequest) -> dict[str, Any]:
    model = body.model or _default_model("agent")
    return await agent.run_agent(body.task, model, body.max_steps, profile=body.profile or "coder")


# Long-running agent tasks: progress + cancellation (Phase B heart).
@app.post("/api/agent/tasks")
async def api_agent_task_create(body: AgentRequest) -> dict[str, Any]:
    model = body.model or _default_model("agent")
    task_state = agent.create_task(body.task, model, body.max_steps,
                                   profile=body.profile or "coder",
                                   auto_commit=body.auto_commit)
    log.info("agent task started id=%s profile=%s", task_state["id"], body.profile or "coder")
    return task_state


@app.post("/api/agent/tasks/{task_id}/continue")
async def api_agent_task_continue(task_id: str, body: ContinueRequest) -> dict[str, Any]:
    model = body.model or _default_model("agent")
    try:
        return agent.continue_task(task_id, body.follow_up, model=model,
                                   max_steps=body.max_steps)
    except agent.AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/agent/tasks")
def api_agent_task_list() -> dict[str, Any]:
    return {"tasks": agent.list_tasks()}


@app.get("/api/agent/tasks/{task_id}")
def api_agent_task_get(task_id: str) -> dict[str, Any]:
    state = agent.get_task(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="Task not found.")
    return state


# Server-sent events: pushes the task state whenever it changes instead of the
# UI polling every 1.2s. Closes itself once the task reaches a terminal state.
_TERMINAL_AGENT = ("done", "failed", "cancelled", "timeout", "interrupted",
                   "complete")


@app.get("/api/agent/tasks/{task_id}/events")
async def api_agent_task_events(task_id: str):
    if not agent.get_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found.")

    async def event_generator():
        last = ""
        idle = 0
        while True:
            state = agent.get_task(task_id)
            if state is None:  # pruned/gone mid-stream
                yield "data: {\"detail\":\"task gone\"}\n\n"
                return
            try:
                blob = json.dumps(state, default=str)
            except (TypeError, ValueError):
                blob = json.dumps({"id": task_id, "status": state.get("status")})
            if blob != last:
                last = blob
                yield f"data: {blob}\n\n"
            if state.get("status") in _TERMINAL_AGENT:
                return
            await asyncio.sleep(0.35)
            idle += 1
            if idle % 40 == 0:  # ~14s keep-alive comment (no UI effect)
                yield ": keep-alive\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/api/agent/tasks/{task_id}")
def api_agent_task_cancel(task_id: str) -> dict[str, Any]:
    state = agent.get_task(task_id)
    if not state:
        raise HTTPException(status_code=404, detail="Task not found.")
    cancelled = agent.cancel_task(task_id)
    return {"id": task_id, "cancelled": cancelled, "status": state["status"]}


# Diff review + 1-click undo for every file the agent touched.
class RevertRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)


@app.get("/api/agent/tasks/{task_id}/changes")
def api_agent_task_changes(task_id: str) -> dict[str, Any]:
    if not agent.get_task(task_id):
        raise HTTPException(status_code=404, detail="Task not found.")
    return {"changes": agent.task_changes(task_id)}


@app.post("/api/agent/tasks/{task_id}/changes/revert")
def api_agent_task_revert(task_id: str, body: RevertRequest) -> dict[str, Any]:
    try:
        return agent.revert_change(task_id, body.path)
    except agent.AgentError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/agent/plan")
async def api_agent_plan(body: PlanRequest) -> dict[str, Any]:
    model = body.model or _default_model("agent")
    return await agent.plan_task(body.task, model)


@app.get("/api/agent/profiles")
def api_agent_profiles() -> dict[str, Any]:
    return {"profiles": profiles.list_profiles()}


@app.get("/api/agent/pending")
def api_agent_pending() -> dict[str, Any]:
    return {"pending": agent.pending_approvals()}


@app.post("/api/agent/approve")
def api_agent_approve(body: ApproveRequest) -> dict[str, Any]:
    return agent.approve_tool(body.tool, body.minutes)


# ------------------------------------------------------ manager routes ---


@app.post("/api/jobs")
async def api_job_create(body: JobRequest) -> dict[str, Any]:
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


@app.get("/api/jobs/{job_id}/artifacts")
def api_job_artifacts(job_id: str) -> dict[str, Any]:
    if not manager.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job not found.")
    try:
        base = manager.job_dir(job_id)
        out = []
        for p in sorted(base.rglob("*")):
            if len(out) >= 200:
                break
            if p.is_file():
                try:
                    out.append({"path": p.relative_to(base).as_posix(),
                                "size": p.stat().st_size})
                except OSError:
                    continue
        return {"id": job_id, "artifacts": out}
    except Exception as exc:  # noqa: BLE001 — FS failure → friendly error
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


# -------------------------------------------------------- slash routes ---


@app.get("/api/slash/list")
def api_slash_list() -> dict[str, Any]:
    return {"commands": slash.list_commands()}


@app.post("/api/slash/run")
async def api_slash_run(body: SlashRun) -> dict[str, Any]:
    model = body.model or _default_model("chat")
    try:
        return await slash.run_slash(body.command, body.args, model)
    except llm.ArenaLLMError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------- mcp routes ---


@app.get("/api/mcp/status")
async def api_mcp_status() -> dict[str, Any]:
    return await mcp_client.status()


@app.post("/api/mcp/call")
async def api_mcp_call(body: McpCall) -> dict[str, Any]:
    try:
        return {"result": await mcp_client.call_tool(body.server, body.tool, body.args)}
    except mcp_client.McpError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# -------------------------------------------------------- todos routes ---


@app.get("/api/todos")
def api_todos_list() -> dict[str, Any]:
    return {"todos": todos.list_todos()}


@app.post("/api/todos")
def api_todos_create(body: TodoCreate) -> dict[str, Any]:
    try:
        return todos.create(body.text, body.job or None)
    except todos.TodoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.patch("/api/todos/{todo_id}")
def api_todos_patch(todo_id: str, body: TodoPatch) -> dict[str, Any]:
    try:
        return todos.set_done(todo_id, body.done)
    except todos.TodoError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/todos/{todo_id}")
def api_todos_delete(todo_id: str) -> dict[str, Any]:
    return {"deleted": todos.remove(todo_id), "id": todo_id}


@app.post("/api/todos/clear")
def api_todos_clear() -> dict[str, Any]:
    return {"cleared": todos.clear_done()}


# ---------------------------------------------------- workflows routes ---


@app.get("/api/workflows")
def api_workflows_list() -> dict[str, Any]:
    return {"workflows": workflows.list_workflows()}


@app.post("/api/workflows")
def api_workflows_save(body: WorkflowSave) -> dict[str, Any]:
    try:
        return workflows.save_workflow(
            body.name, [s.model_dump() for s in body.steps])
    except workflows.WorkflowError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/workflows/{name}")
def api_workflows_delete(name: str) -> dict[str, Any]:
    return {"deleted": workflows.delete_workflow(name), "name": name}


@app.post("/api/workflows/{name}/run")
async def api_workflows_run(name: str, body: WorkflowRun) -> dict[str, Any]:
    model = body.model or _default_model("agent")
    try:
        return workflows.start_run(name, model)
    except workflows.WorkflowError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/workflows/runs/{run_id}")
def api_workflows_get_run(run_id: str) -> dict[str, Any]:
    run = workflows.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    return run


# ----------------------------------------------------- workspace routes ---


@app.get("/api/workspace")
def api_workspace() -> dict[str, Any]:
    return {"layout": workspacex.ensure(), "usage": workspacex.usage()}


@app.post("/api/workspace/cleanup")
def api_workspace_cleanup(body: CleanupReq) -> dict[str, Any]:
    result = workspacex.cleanup(body.max_age_hours, body.max_bytes)
    log.info("workspace cleanup removed=%s files=%s bytes", result["removed_files"], result["removed_bytes"])
    return result


# ------------------------------------------------------ run/build routes ---


@app.post("/api/run")
async def api_run(body: RunReq) -> dict[str, Any]:
    try:
        job = execjobs.start(body.action, body.path, port=body.port, timeout=body.timeout)
        log.info("exec job started id=%s action=%s", job["id"], body.action)
        return job
    except execjobs.ExecError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/run")
def api_run_list() -> dict[str, Any]:
    return {"jobs": execjobs.list_jobs()}


@app.get("/api/run/{job_id}")
def api_run_get(job_id: str) -> dict[str, Any]:
    job = execjobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@app.delete("/api/run/{job_id}")
def api_run_cancel(job_id: str) -> dict[str, Any]:
    job = execjobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return {"id": job_id, "cancelled": execjobs.cancel(job_id), "status": job["status"]}


# ------------------------------------------------------ browser routes ---


@app.post("/api/browser/inspect")
async def api_browser_inspect(body: BrowserInspectReq) -> dict[str, Any]:
    try:
        return await browser.inspect(body.url, body.actions)
    except browser.BrowserError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------- web routes ---


@app.post("/api/web/search")
def api_web_search(body: WebSearchReq) -> dict[str, Any]:
    try:
        return {"results": web.web_search(body.q, body.max_results)}
    except web.WebError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/web/fetch")
def api_web_fetch(body: WebFetchReq) -> dict[str, Any]:
    try:
        return web.web_fetch(body.url)
    except web.WebError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

# AK Dev Arena — Architecture

## Big picture

```
┌─────────────────────────────────────────────────────────┐
│  Desktop shell (Tauri + React + Tailwind)   ← the "face" │
│  Chat · Code · Agent · Manager · Build · Voice           │
└──────────────────────┬──────────────────────────────────┘
                       │  HTTP/SSE (localhost)
┌──────────────────────▼──────────────────────────────────┐
│  Python sidecar (FastAPI)                   ← the "brain"│
│  ┌─────────┐  ┌──────────┐  ┌─────────────────────────┐  │
│  │ Vault   │  │ LLM      │  │ Tools (Phase 1+)        │  │
│  │ (keys)  │  │ Router   │  │ files · terminal · git  │  │
│  │         │  │ LiteLLM  │  │ browser · sandbox       │  │
│  └─────────┘  └────┬─────┘  └─────────────────────────┘  │
└───────────────────┼─────────────────────────────────────┘
                    │  any provider
        ┌───────────┼───────────────────────────────┐
        ▼           ▼               ▼               ▼
     OpenAI    Anthropic    Gemini/DeepSeek    Ollama (local)
```

## Components

| Component | File(s) | Job |
|---|---|---|
| API server | `backend/app/main.py` | REST + SSE endpoints, validation, errors |
| LLM router | `backend/app/llm.py` | One interface for every provider via LiteLLM |
| Vault | `backend/app/vault.py` | Reads keys from env / `config.local.yaml`; API only exposes booleans, never key values |
| Config | `backend/app/config.py` + `config.yaml` | All settings, no secrets |
| Frontend | `frontend/src/` | Chat UI now; editor/diff/terminal/preview in later phases |
| Desktop shell | `src-tauri/` | Native window + packaging (Phase 8) |

## Key decisions
1. **One backend language (Python)** — LiteLLM, Aider-style editing, Whisper, Docker SDK are all Python. No Bun/TS backend to maintain.
2. **LiteLLM as the universal translator** — user brings any key, same code path handles it. New models work without code changes.
3. **Keys never touch git or logs** — env vars or `config.local.yaml` (git-ignored, chmod 600). `/api/*` never returns key values.
4. **Explicit modes, not magic routing** — user picks Chat/Code/Agent/... (Cline-style). The router only *suggests*.
5. **Every destructive action needs approve + undo** — diffs in Code Mode, checkpoints in Agent/Build Mode, voice confirmations in Voice Mode.
6. **Sandbox by default** — Agent/Build Mode run risky commands in Docker; host FS is never directly touched.

## Data flow (Chat Mode, Phase 0)
1. User types → frontend `POST /api/chat` (or `/api/chat/stream` for SSE tokens)
2. `main.py` validates → `llm.py` picks provider, injects key from `vault.py`
3. LiteLLM calls provider → response streams back token-by-token
4. No prompt content is stored anywhere (memory arrives in Phase 2, opt-in).

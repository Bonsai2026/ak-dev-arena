# 🏟️ AK Dev Arena

> **One open-source AI workstation that mixes the best of Cursor, Manus, OpenCode, FreeBuff, Claude Code & Codex — plus hands-free voice control nobody else has.**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![CI](https://github.com/Bonsai2026/ak-dev-arena/actions/workflows/ci.yml/badge.svg)](https://github.com/Bonsai2026/ak-dev-arena/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-1.2.0-brightgreen.svg)](config.yaml)
[![Stack](https://img.shields.io/badge/stack-Tauri%20%2B%20React%20%2B%20FastAPI%20%2B%20LiteLLM-green.svg)](docs/ARCHITECTURE.md)
[![Tests](https://img.shields.io/badge/tests-79%20passing-brightgreen.svg)](backend/tests)

Bring **any API key** — **215+ providers, 7,500+ models** via the open [models.dev](https://models.dev) registry (same formula OpenCode uses). Add one key → all its models auto-detect. **1,000+ models are FREE** 🆓 — or run **100% local** with Ollama. No lock-in. No ads. No subscriptions. Ever.

**Real open-source engines mixed in:** models.dev catalog (OpenCode formula) · MCP protocol (Anthropic) · Aider repo-maps (auto when installed) · free web research · Cursor-style `@mentions` + **chat instructions** + Composer + Tab-complete · Claude-style `/slash` + Plan + hooks + permissions · FreeBuff-style profiles + workflows · Manus-style todos + artifacts.

**📋 Chat instructions (new in v1.2):** set global instructions + project rules (`.akrules`) once, and they're auto-injected into every model call — Chat, Agent, Code Composer, Build and Review. Like Cursor rules · Claude `CLAUDE.md` · Codex `AGENTS.md`.

---

## ✨ Modes (all 7 working in v1.0)

| Mode | What it does | Inspired by |
|------|--------------|-------------|
| 💬 **Chat** | Talk to any model, streaming replies | ChatGPT / Claude |
| ⌨️ **Code** | Browse, edit (diff preview), search, git checkpoint + undo | Cursor, Aider |
| 🤖 **Agent** | Autonomous plan→act→verify tasks with tools | Manus, Claude Code |
| 👁️ **Manager** | Mission control — parallel agents, isolated workspaces | Antigravity |
| 🏗️ **Build** | Prompt-to-project scaffolding + AI fix loop | v0, Bolt, Lovable |
| 🔍 **Review** | Senior-dev AI review of any diff | CodeRabbit, Codex |
| 🎙️ **Voice** | Speak to command, Arena speaks back | ⭐ our killer feature |

Extras: **⌘K command palette** · **📊 usage tracker** (see every token) · **🔑 key vault** (keys never leak) · **🐳 sandbox-ready** agent design.

Full plan: [`docs/ROADMAP.md`](docs/ROADMAP.md) · How it works: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · Shipping: [`docs/RELEASE.md`](docs/RELEASE.md) · Honest status: [`docs/STATUS.md`](docs/STATUS.md)

---

## 🚀 Quickstart (2 minutes)

**Prerequisites:** Python 3.11+, Node.js 20+

```bash
# 1. Clone
git clone https://github.com/Bonsai2026/ak-dev-arena.git
cd ak-dev-arena

# 2. One-command setup (backend + optional engines + frontend)
make setup
# …or manually:
#   pip install -r backend/requirements.txt
#   pip install -r backend/requirements-optional.txt   # voice, web search, MCP, repo maps
#   cd frontend && npm install && cd ..

# 3. Start the backend (brain 🧠) — binds 127.0.0.1 by default (safe)
make backend          # or: python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
# → API docs at http://127.0.0.1:8000/docs
# Only expose to LAN/preview when you need it:
#   ARENA_HOST=0.0.0.0 make backend      (add ARENA_CORS_ORIGINS for extra origins)

# 4. Start the frontend (face 😎) — in a new terminal
make frontend         # or: cd frontend && npm run dev
# → App at http://localhost:1420
```

**Set your chat instructions** (optional, like Cursor rules / Claude CLAUDE.md / Codex AGENTS.md):
- Open **📋 Instructions** in the sidebar (or `⌘K` → “Chat instructions”).
- **Global instructions** apply everywhere; **project rules** save as `.akrules` in `./workspace`.
- Both are auto-injected into Chat, Agent, Code Composer, Build and Review.

**Add your API key** (pick one):
- In the app: click **🔑 Keys** in the sidebar, paste key, done.
- Or via terminal: `export OPENAI_API_KEY=sk-...` (also `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `GROQ_API_KEY`)
- Or 100% local & free: install [Ollama](https://ollama.ai), run `ollama pull llama3.1`, pick the Ollama model in the app.

**Windows first:** see [`docs/WINDOWS.md`](docs/WINDOWS.md) — one-click `start.bat`,
Tauri shell (auto-starts the backend), and the smoke-test checklist. CI runs a
Windows job (pytest + frontend build + Tauri check) on every push.

**Voice mode extras (optional):** `pip install faster-whisper edge-tts`

> **Security:** the backend binds `127.0.0.1` and CORS is allow-listed to the app's
> own origins (no `*`). Web fetch rejects private/local addresses (SSRF guard),
> the agent's shell is token allow-listed (no delete/install/push/metacharacters),
> and git undo never destroys uncommitted user work (backup branch + dirty-tree
> refusal). See `backend/tests/test_security.py`.

---

## 🧪 Tests

```bash
make test                      # 79 tests — chat, files, git, agent, jobs, build, review, voice, usage, instructions
make build                     # TypeScript + production build
```

## 🗂️ Project structure

```
ak-dev-arena/
├── backend/            # Python sidecar (FastAPI + LiteLLM) — the brain
│   ├── app/            #   main.py (API) · llm.py · vault.py · config.py
│   │                   #   files.py · gitops.py · agent.py · manager.py
│   │                   #   builder.py · review.py · voice.py · usage.py
│   └── tests/          #   79 pytest tests (run in CI)
├── frontend/           # React + Vite + Tailwind — the face (7 modes + ⌘K palette)
├── src-tauri/          # Tauri desktop shell (native packaging — needs Rust stable)
├── workspace/          # AI playground (git-ignored, created on first run)
├── docs/               # ARCHITECTURE.md · ROADMAP.md · RELEASE.md
├── config.yaml         # All settings (no secrets — keys stay in config.local.yaml)
└── .github/workflows/  # CI + Release automation
```

## 🤝 Contributing

Open source, open hearts. See [CONTRIBUTING.md](CONTRIBUTING.md) — PRs welcome!

## 📜 License

[AGPL-3.0](LICENSE) — free forever, for everyone. If you improve it, share it back. ❤️

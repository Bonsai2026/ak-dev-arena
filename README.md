# 🏟️ AK Dev Arena

> **One open-source AI workstation that mixes the best of Cursor, Manus, OpenCode, FreeBuff, Claude Code & Codex — plus hands-free voice control nobody else has.**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![CI](https://github.com/Bonsai2026/ak-dev-arena/actions/workflows/ci.yml/badge.svg)](https://github.com/Bonsai2026/ak-dev-arena/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.1.0-orange.svg)](config.yaml)
[![Stack](https://img.shields.io/badge/stack-Tauri%20%2B%20React%20%2B%20FastAPI%20%2B%20LiteLLM-green.svg)](docs/ARCHITECTURE.md)

Bring **any API key** (OpenAI, Anthropic, Gemini, DeepSeek, Groq) or run **100% local & free** with Ollama. No lock-in. No ads. No subscriptions. Ever.

---

## ✨ Modes (one app, six superpowers)

| Mode | Status | Inspired by |
|------|--------|-------------|
| 💬 **Chat** — talk to any model | ✅ Phase 0 (working) | ChatGPT / Claude |
| ⌨️ **Code** — Cursor-style smart edits in your projects | 🔜 Phase 1 | Cursor, Aider |
| 🤖 **Agent** — autonomous tasks in a safe sandbox | 🔜 Phase 2 | Manus, Claude Code |
| 👁️ **Manager** — mission control for parallel agents | 🔜 Phase 3 | Antigravity |
| 🏗️ **Build** — prompt-to-app with live preview | 🔜 Phase 4 | v0, Bolt, Lovable |
| 🎙️ **Voice** — hands-free continuous voice control | 🔜 Phase 6 | ⭐ our killer feature |

Full plan: [`docs/ROADMAP.md`](docs/ROADMAP.md) · How it works: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## 🚀 Quickstart (2 minutes)

**Prerequisites:** Python 3.11+, Node.js 20+

```bash
# 1. Clone
git clone https://github.com/Bonsai2026/ak-dev-arena.git
cd ak-dev-arena

# 2. Start the backend (brain 🧠)
pip install -r backend/requirements.txt
python -m uvicorn backend.app.main:app --port 8000
# → API docs at http://127.0.0.1:8000/docs

# 3. Start the frontend (face 😎) — in a new terminal
cd frontend && npm install && npm run dev
# → App at http://localhost:1420
```

**Add your API key** (pick one):
- In the app: click **🔑 Keys** in the sidebar, paste key, done.
- Or via terminal: `export OPENAI_API_KEY=sk-...` (also supports `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `GROQ_API_KEY`)
- Or 100% local & free: install [Ollama](https://ollama.ai), run `ollama pull llama3.1`, pick the Ollama model in the app.

---

## 🗂️ Project structure

```
ak-dev-arena/
├── backend/            # Python sidecar (FastAPI + LiteLLM) — the brain
│   ├── app/            #   main.py (API) · llm.py (router) · vault.py (keys) · config.py
│   └── tests/          #   pytest suite (runs in CI)
├── frontend/           # React + Vite + Tailwind — the face
├── src-tauri/          # Tauri desktop shell (packaging in Phase 8)
├── docs/               # ARCHITECTURE.md · ROADMAP.md
├── config.yaml         # All settings (no secrets — keys stay in config.local.yaml)
└── .github/workflows/  # CI: backend tests + frontend build
```

## 🤝 Contributing

Open source, open hearts. See [CONTRIBUTING.md](CONTRIBUTING.md) — PRs welcome!

## 📜 License

[AGPL-3.0](LICENSE) — free forever, for everyone. If you improve it, share it back. ❤️

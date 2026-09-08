# 🏟️ AK Dev Arena

> **One open-source AI workstation that mixes the best of Cursor, Manus, OpenCode, FreeBuff, Claude Code & Codex — plus hands-free voice control nobody else has.**

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)
[![CI](https://github.com/Bonsai2026/ak-dev-arena/actions/workflows/ci.yml/badge.svg)](https://github.com/Bonsai2026/ak-dev-arena/actions/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-1.1.0-brightgreen.svg)](config.yaml)
[![Stack](https://img.shields.io/badge/stack-Tauri%20%2B%20React%20%2B%20FastAPI%20%2B%20LiteLLM-green.svg)](docs/ARCHITECTURE.md)
[![Tests](https://img.shields.io/badge/tests-38%20passing-brightgreen.svg)](backend/tests)

Bring **any API key** — **215+ providers, 7,500+ models** via the open [models.dev](https://models.dev) registry (same formula OpenCode uses). Add one key → all its models auto-detect. **1,000+ models are FREE** 🆓 — or run **100% local** with Ollama. No lock-in. No ads. No subscriptions. Ever.

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

Full plan: [`docs/ROADMAP.md`](docs/ROADMAP.md) · How it works: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · Shipping: [`docs/RELEASE.md`](docs/RELEASE.md)

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
- Or via terminal: `export OPENAI_API_KEY=sk-...` (also `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `GROQ_API_KEY`)
- Or 100% local & free: install [Ollama](https://ollama.ai), run `ollama pull llama3.1`, pick the Ollama model in the app.

**Voice mode extras (optional):** `pip install faster-whisper edge-tts`

---

## 🧪 Tests

```bash
pytest backend/tests -q        # 38 tests — chat, files, git, agent, jobs, build, review, voice, usage
cd frontend && npm run build   # TypeScript + production build
```

## 🗂️ Project structure

```
ak-dev-arena/
├── backend/            # Python sidecar (FastAPI + LiteLLM) — the brain
│   ├── app/            #   main.py (API) · llm.py · vault.py · config.py
│   │                   #   files.py · gitops.py · agent.py · manager.py
│   │                   #   builder.py · review.py · voice.py · usage.py
│   └── tests/          #   38 pytest tests (run in CI)
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

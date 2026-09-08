# Contributing to AK Dev Arena 🤝

Thanks for helping build the open AI workstation! Short rules:

## Setup
```bash
git clone https://github.com/Bonsai2026/ak-dev-arena.git
cd ak-dev-arena
pip install -r backend/requirements.txt
cd frontend && npm install
```

## Workflow
1. Fork → create branch (`feat/voice-mode`, `fix/chat-scroll`)
2. Make changes + add/adjust tests
3. Run checks:
   ```bash
   pytest backend/tests -q        # backend must pass
   cd frontend && npm run build   # frontend must build
   ```
4. Open a PR against `main` with a clear description + screenshot/GIF if UI changed

## Code style
- **Backend:** Python 3.11+, type hints, docstrings, `ruff`/`black`-friendly formatting
- **Frontend:** TypeScript strict, functional components, Tailwind for styling
- **Security:** NEVER log or commit API keys. Keys live in env vars or `config.local.yaml` (git-ignored) only.

## Roadmap
Pick an issue from the [Phase plan](docs/ROADMAP.md). Phase 0 ✅ · Next: Phase 1 (Code Mode).

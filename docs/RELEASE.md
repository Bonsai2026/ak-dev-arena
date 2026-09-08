# AK Dev Arena — Release Guide

## What "v1.0 Full & Final" contains
- **Backend:** FastAPI + LiteLLM sidecar, 25+ endpoints, 38 passing tests
- **Frontend:** React + Vite + Tailwind, 7 modes, ⌘K palette, production build verified
- **Docs:** README, ARCHITECTURE, ROADMAP, CONTRIBUTING, AGPL-3.0 LICENSE
- **Automation:** CI (pytest + frontend build) on every push; GitHub Release on every `v*` tag

## Run from source (recommended for v1.0)
```bash
git clone https://github.com/Bonsai2026/ak-dev-arena.git
cd ak-dev-arena
pip install -r backend/requirements.txt
python -m uvicorn backend.app.main:app --port 8000 &
cd frontend && npm install && npm run dev
# open http://localhost:1420
```

## Make a new release
```bash
# 1. bump versions (config.yaml, backend/app/__init__.py,
#    frontend/package.json, src-tauri/*)
# 2. commit + tag + push
git commit -am "Release vX.Y.Z"
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin main vX.Y.Z
# 3. GitHub Actions builds a Release automatically (see release.yml)
```

## Native desktop installers (post-1.0 track)
`src-tauri/` holds the Tauri 2 shell. To package locally you need **Rust stable**:
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
cargo install tauri-cli
cd frontend && npm run build && cd ..
tauri build   # → bundles for your OS (deb/appimage/nsis/dmg)
```
Code-signing (Windows/macOS) + auto-update + sidecar binaries are tracked as post-1.0 work.

## Launch checklist (for the maintainer)
- [ ] Demo video/GIF in README
- [ ] Post to r/LocalLLaMA, r/opensource, Hacker News "Show HN", Product Hunt
- [ ] Topics on GitHub repo: ai-agent, coding-assistant, voice-control, sandbox, tauri, litellm
- [ ] Open a Discord for contributors

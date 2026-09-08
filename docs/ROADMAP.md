# AK Dev Arena — Roadmap to v1.0 (Full & Final)

10 phases, Phase 0 → Phase 9. Every phase ended with a **working, tested, tagged** version.

| Phase | Name | Delivered | Version |
|---|---|---|---|
| **0** | Foundation | Tauri+React shell, FastAPI+LiteLLM sidecar, Chat Mode, key vault, CI | v0.1 ✅ |
| **1** | Code Mode | File tree, editor, diff preview, search, `.akrules`-ready, git checkpoint + undo | v0.2 ✅ |
| **2** | Agent Mode | Plan→act→verify loop, allow-listed shell, observations | v0.3 ✅ |
| **3** | Manager View | Mission control, parallel jobs in isolated workspaces, cancel | v0.4 ✅ |
| **4** | Build Mode | 3 templates, prompt-to-project, AI fix loop with safe patches | v0.5 ✅ |
| **5** | Review Mode | Structured AI findings (critical/warning/info) on any diff | v0.6 ✅ |
| **6** | Voice Mode | Faster-Whisper STT + Edge-TTS, mic record, speak-back ⭐ killer feature | v0.7 ✅ |
| **7** | Free & Local | Ollama catalog entry, usage tracker, free-model filter | v0.8 ✅ |
| **8** | Polish | ⌘K palette, shortcuts, usage footer, onboarding, 7-mode shell | v0.9 ✅ |
| **9** | Release | Docs, release automation, demo workspace, version 1.0.0 | **v1.0 🎉** |

## v1.0 definition of done
- [x] All 7 modes working (Chat, Code, Agent, Manager, Build, Review, Voice)
- [x] Any API key + Ollama local both work
- [x] 38 backend tests passing + frontend production build green in CI
- [x] Undo available for every destructive action (diff preview + git checkpoints)
- [x] Docs published (ARCHITECTURE, ROADMAP, RELEASE, CONTRIBUTING)

## Post-1.0 ideas
Tauri native installers (Win/Mac/Linux code-signed), Docker sandbox executor, light theme,
persistent agent memory, cloud sync, mobile companion, agent/workflow marketplace.

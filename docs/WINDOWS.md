# 🪟 AK Dev Studio — Windows Smoke Test Guide

Windows is the **first-class desktop target**. CI runs the Windows job on every
push (backend tests + frontend build + Tauri `cargo check`), but a real PC test
needs a human — this page is that checklist.

## 1. Prerequisites (one time)

```powershell
# From an Administrator PowerShell / CMD:
winget install Python.Python.3.12
winget install OpenJS.NodeJS.LTS
winget install Git.Git
winget install Microsoft.VisualStudio.2022.BuildTools   # Tauri (C++ workload optional for dev)
# options (voice / web search / MCP / repo maps):
winget install Ollama.Ollama
```

## 2. Setup + launch

```powershell
git clone https://github.com/Bonsai2026/ak-dev-arena.git
cd ak-dev-arena
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt
.venv\Scripts\pip install -r backend\requirements-optional.txt
cd frontend
npm install
cd ..
start.bat
```

`start.bat` opens two windows: **Backend** (`:8000`) and **Frontend**
(`:1420`). Open http://localhost:1420 in your browser.

## 3. Early Smoke Test (Phase A.5) — run on YOUR PC

Task each row with a ✅ / ❌ and the error message if any.

| # | Check | How | ✅/❌ |
|---|---|---|---|
| 1 | Backend starts | Backend window shows "Application startup complete" | |
| 2 | Health check | `curl http://127.0.0.1:8000/health` → `{"status":"ok"}` | |
| 3 | Diagnostics | `curl http://127.0.0.1:8000/api/diagnostics` | |
| 4 | Frontend loads | http://localhost:1420 shows the app, not an error screen | |
| 5 | Workspace opens | Code Mode shows `./workspace` files | |
| 6 | API request works | Sidebar Keys panel saves a key (or Ollama local model appears) | |
| 7 | Basic chat | Send "hi" — streaming reply appears; ⏹ Stop works | |
| 8 | Restart | Close both windows, run `start.bat` again — everything comes back | |

## 4. Desktop shell (Tauri)

Tauri needs Rust stable + [WebView2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/) (usually preinstalled on Win 10/11):

```powershell
winget install Rustlang.Rustup
winget install tauri-apps.tauri-cli
cargo install tauri-cli --locked
# from repo root:
cd frontend && npm run build && cd ..
cargo run --manifest-path src-tauri/Cargo.toml
```

The Rust shell spawns the Python backend automatically (`ARENA_PYTHON`
overrides the interpreter; default `python`).

## 5. Tauri smoke checklist

| # | Check | ✅/❌ |
|---|---|---|
| 1 | Window opens with the app UI | |
| 2 | Backend starts automatically (no manual command) | |
| 3 | Chat works inside the desktop window (CORS `tauri://localhost` / `tauri.localhost` are allow-listed) | |
| 4 | Closing the window kills the backend process (check Task Manager) | |
| 5 | `cargo build` (Debug) completes without errors | |

## 6. Known Windows notes

* Backend binds `127.0.0.1` by default — safe. For LAN/preview use
  `set ARENA_HOST=0.0.0.0` and `set ARENA_CORS_ORIGINS=http://<lan-ip>:1420`.
* `python` vs `py`: if `python` is missing, run `.\.venv\Scripts\python.exe`
  directly or set `ARENA_PYTHON=py`.
* Path separators are handled by Python (`pathlib`); Rust sidecar uses
  `python -m uvicorn` (no shell), so `C:\Users\...` paths work.
* If the Windows firewall prompts, allow **only** `127.0.0.1` (private) traffic.

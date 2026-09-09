// AK Dev Studio — Tauri desktop shell.
//
// The shell is responsible for:
//   1. Opening the desktop window (React UI from ../frontend/dist or dev server)
//   2. Spawning the Python backend sidecar (FastAPI on :8000) at startup
//   3. Killing the sidecar when the app exits (no orphan processes)
//
// Configuration (env vars, all optional):
//   ARENA_PYTHON      python executable            (default: python / python3)
//   ARENA_BACKEND_DIR backend working dir          (default: current dir)
//   ARENA_HOST        backend bind host            (default: 127.0.0.1)
//   ARENA_PORT        backend port                 (default: 8000)

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::{Manager, RunEvent};

struct BackendProcess(Mutex<Option<Child>>);

fn spawn_backend() -> Option<Child> {
    let py = std::env::var("ARENA_PYTHON").unwrap_or_else(|_| {
        if cfg!(windows) {
            "python".to_string()
        } else {
            "python3".to_string()
        }
    });
    let host = std::env::var("ARENA_HOST").unwrap_or_else(|_| "127.0.0.1".to_string());
    let port = std::env::var("ARENA_PORT").unwrap_or_else(|_| "8000".to_string());
    let dir = std::env::var("ARENA_BACKEND_DIR").unwrap_or_else(|_| ".".to_string());

    Command::new(&py)
        .args([
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            &host,
            "--port",
            &port,
        ])
        .current_dir(&dir)
        .spawn()
        .ok()
}

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            // Start the brain (Python sidecar) before showing the UI.
            let child = spawn_backend();
            if child.is_none() {
                eprintln!(
                    "[AK Dev Studio] Could not start backend. Set ARENA_PYTHON / ARENA_BACKEND_DIR."
                );
            }
            app.manage(BackendProcess(Mutex::new(child)));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build AK Dev Studio")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app_handle.try_state::<BackendProcess>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                            let _ = child.wait();
                        }
                    }
                }
            }
        });
}

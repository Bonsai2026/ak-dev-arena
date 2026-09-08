// AK Dev Arena — Tauri desktop shell (Phase 0 stub).
// Full packaging (sidecar binaries, auto-update, installers) lands in Phase 8.
// Until then: `cd frontend && npm run dev` + python sidecar (see README).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .run(tauri::generate_context!())
        .expect("failed to run AK Dev Arena");
}

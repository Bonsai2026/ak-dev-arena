import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Port 1420 = Tauri dev default (desktop shell attaches here in Phase 8).
// /api is proxied to the Python sidecar (FastAPI on :8000).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: "0.0.0.0",
    port: 1420,
    strictPort: true,
    // Allow the Arena live-preview host (and any LAN host for Tauri/phone testing).
    allowedHosts: true,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: "dist",
  },
});

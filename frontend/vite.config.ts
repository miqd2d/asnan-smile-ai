/// <reference types="vitest" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// The browser talks to "/api/..." and the dev server forwards it to the FastAPI backend.
// This avoids CORS entirely, so the backend needs NO changes to work with this frontend.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const backend = env.VITE_BACKEND_URL || "http://localhost:8000";
  const proxy = {
    "/api": { target: backend, changeOrigin: true, rewrite: (p: string) => p.replace(/^\/api/, "") },
  };
  return {
    plugins: [react()],
    server: { port: 5173, proxy },
    preview: { port: 5173, proxy },
    test: {
      environment: "jsdom", globals: true, setupFiles: ["./tests/setup.ts"], testTimeout: 30000,
      // The integration test talks to a real backend (see tests/support/fake_backend.py)
      env: { VITE_API_BASE: env.TEST_BACKEND_URL || "http://127.0.0.1:8765" },
    },
  };
});

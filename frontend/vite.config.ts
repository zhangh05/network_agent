/// <reference types="vitest" />
/// <reference types="node" />
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Vite config.
 *
 * Dev proxy (npm run dev):
 *  - `/api` → `VITE_DEV_API_TARGET` (default `http://127.0.0.1:8010`)
 *
 * Production build (npm run build):
 *  - Static files in `dist/` can be served by the FastAPI backend
 *    or by a separate static server. The frontend's API base URL
 *    is read from `VITE_API_BASE` at build time, defaulting to
 *    `/api` (same-origin). Override per-environment via
 *    `VITE_API_BASE=https://example.com` etc.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const devApiTarget = env.VITE_DEV_API_TARGET || "http://127.0.0.1:8010";

  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        "/api": {
          target: devApiTarget,
          changeOrigin: true,
        },
      },
    },
    test: {
      globals: true,
      environment: "happy-dom",
      setupFiles: "./src/test/setup.ts",
      css: false,
    },
  };
});

import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

const here = path.dirname(fileURLToPath(import.meta.url));
const backend = process.env.VITE_BACKEND_URL || "http://127.0.0.1:8030";

// Local `vite` / `npm run dev` (and local compose): stay at `/` so
// http://localhost:8040/ is unchanged. The production image sets
// VITE_BASE=/qualsched/ (see frontend/Dockerfile) so the browser requests
// /qualsched/assets/… and /qualsched/api/…; host nginx strips that prefix.
const base = process.env.VITE_BASE || "/";

export default defineConfig({
  plugins: [svelte()],
  base,
  resolve: {
    alias: {
      "@qualsched/ui": path.resolve(here, "../../ui"),
      "@qualsched/api": path.resolve(here, "src/lib/api.ts"),
      "@qualsched/changelog": path.resolve(here, "CHANGELOG.md"),
      "@qualsched/guide": path.resolve(here, "docs/USER_GUIDE.md"),
    },
  },
  server: {
    port: 8040,
    strictPort: true,
    host: true,
    fs: {
      allow: [here, path.resolve(here, "../../ui")],
    },
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/auth": { target: backend, changeOrigin: true },
      "/health": { target: backend, changeOrigin: true },
    },
  },
  preview: {
    port: 8040,
    strictPort: true,
  },
});

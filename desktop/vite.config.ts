import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

const here = path.dirname(fileURLToPath(import.meta.url));
const host = process.env.TAURI_DEV_HOST;

export default defineConfig(async () => ({
  plugins: [svelte()],
  resolve: {
    alias: {
      "@qualsched/ui": path.resolve(here, "../ui"),
      "@qualsched/api": path.resolve(here, "src/lib/api.ts"),
      "@qualsched/changelog": path.resolve(here, "CHANGELOG.md"),
      "@qualsched/guide": path.resolve(here, "docs/USER_GUIDE.md"),
    },
  },
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host ? { protocol: "ws", host, port: 1421 } : undefined,
    fs: {
      allow: [here, path.resolve(here, "../ui")],
    },
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
}));

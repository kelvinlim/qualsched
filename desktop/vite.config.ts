import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";

const here = path.dirname(fileURLToPath(import.meta.url));
const host = process.env.TAURI_DEV_HOST;

export default defineConfig(async () => ({
  plugins: [svelte()],
  resolve: {
    // Regex finds keep `?raw` (and other queries). Vite's production alias
    // matcher only accepts an exact string or `alias/…`, so
    // `import x from "@qualsched/changelog?raw"` from `ui/` failed `vite build`.
    alias: [
      { find: "@qualsched/ui", replacement: path.resolve(here, "../ui") },
      { find: "@qualsched/api", replacement: path.resolve(here, "src/lib/api.ts") },
      {
        find: /^@qualsched\/changelog/,
        replacement: path.resolve(here, "CHANGELOG.md"),
      },
      {
        find: /^@qualsched\/guide/,
        replacement: path.resolve(here, "docs/USER_GUIDE.md"),
      },
    ],
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

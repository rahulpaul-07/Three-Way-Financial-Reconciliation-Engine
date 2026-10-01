import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// VITE_BASE is set by the Pages workflow, because the site is served from
// /Three-Way-Financial-Reconciliation-Engine/ there and from / on Render.
export default defineConfig({
  base: process.env.VITE_BASE ?? "/",
  plugins: [react()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    // `npm run dev` proxies the API to a local uvicorn on :8000.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: {
    sourcemap: false,
    // Never inline fonts. Vite inlines any asset under 4 kB, which put the
    // small Cyrillic, Greek and symbol subsets into the render-blocking CSS
    // as base64 (13 kB the page never uses). As separate files the browser
    // fetches a subset only when the page contains those characters.
    assetsInlineLimit: (file: string) => (/\.woff2?$/.test(file) ? false : undefined),
    chunkSizeWarningLimit: 700,
    // No manualChunks. The chart sections are loaded with dynamic import()
    // (App.tsx, workbench.tsx), so recharts and d3 land in their own chunks
    // without help. A hand-made "charts" chunk had absorbed small helpers the
    // entry also used, which made the entry import it, and Vite then
    // preloaded all 110 kB gzipped of chart code before the first paint.
  },
});

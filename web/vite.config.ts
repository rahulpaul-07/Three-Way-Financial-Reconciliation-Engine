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
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        // Rollup 4 (Vite 8) takes manualChunks as a function. Charts and the
        // animation library are split out because neither is needed until the
        // reader scrolls past the opening.
        manualChunks(id: string) {
          if (id.includes("node_modules/recharts") || id.includes("node_modules/d3-")) return "charts";
          if (id.includes("node_modules/framer-motion") || id.includes("node_modules/motion-")) return "motion";
          return undefined;
        },
      },
    },
  },
});

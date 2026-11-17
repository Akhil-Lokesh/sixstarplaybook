import { defineConfig } from "vite";

// Static build for Cloudflare Pages: output in dist/, SPA fallback in public/_redirects.
export default defineConfig({
  server: { port: 5173, strictPort: true },
  build: { outDir: "dist", sourcemap: false },
});

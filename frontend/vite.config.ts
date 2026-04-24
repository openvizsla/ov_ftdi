import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

// Build output goes into api/src/ovweb/ui/ so the FastAPI app can serve it
// as static files directly (CLAUDE.md repo layout).
export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: '../api/src/ovweb/ui',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true, ws: true },
    },
  },
});

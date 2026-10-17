import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build the app into the Python package so `mcl web` can serve it directly.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: '../mcp_cybernet_lab/webdist',
    emptyOutDir: true,
  },
  server: {
    // During `npm run dev`, proxy the API to a running `mcl web` on :8000.
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})

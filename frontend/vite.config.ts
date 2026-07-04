import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the API runs separately (`ghostline serve`); in production
// FastAPI serves the built app itself.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', ws: true },
    },
  },
  build: {
    chunkSizeWarningLimit: 1500,
  },
})

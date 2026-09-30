import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Dev server: forward /api to the backend (in compose, nginx does this).
  // The backend rejects requests whose Origin differs from Host, so pass the
  // browser's Host (localhost:5173) through unchanged; never rewrite Origin.
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: false },
    },
  },
})

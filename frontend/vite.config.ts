import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Dev server: forward /api to the backend (in compose, nginx does this).
  server: { proxy: { '/api': 'http://localhost:8000' } },
})

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Dev server: forward /api to the backend (in compose, nginx does this).
  // The backend rejects requests whose Origin differs from Host, so present the
  // proxied request as coming from the backend's own origin.
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (req) => {
            if (req.getHeader('origin')) req.setHeader('origin', 'http://localhost:8000')
          })
        },
      },
    },
  },
})

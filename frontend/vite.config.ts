import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// The backend's enforce_origin middleware rejects any request whose Origin
// header doesn't match its own http://127.0.0.1:<port> exactly. changeOrigin
// only rewrites the outgoing Host header, not Origin — the browser's real
// Origin (http://localhost:<vite-port>) still reaches the backend unchanged
// and gets 403'd on every state-changing request. Force it here instead.
const BACKEND_ORIGIN = 'http://127.0.0.1:8420'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: BACKEND_ORIGIN,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('origin', BACKEND_ORIGIN)
          })
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.ts', './src/test-a11y.ts'],
    exclude: ['**/node_modules/**', '**/e2e/**'],
  },
})

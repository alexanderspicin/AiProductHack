import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react(), {
    name: 'text-workspace-entry',
    configureServer(server) {
      server.middlewares.use((request, _response, next) => {
        if (request.url === '/' || request.url?.startsWith('/?')) request.url = '/text.html'
        next()
      })
    },
  }],
  server: {
    host: '127.0.0.1', port: 5177, strictPort: true,
    watch: { usePolling: true, interval: 700 },
    proxy: { '/api/text': { target: process.env.REHEARSAL_API_TARGET || 'http://127.0.0.1:8004', ws: true } },
  },
  build: { outDir: 'dist-text', rollupOptions: { input: 'text.html' } },
})

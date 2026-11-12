import { defineConfig } from 'vite'
import preact from '@preact/preset-vite'

const api = { target: 'http://localhost:8000', changeOrigin: false }
export default defineConfig({
  plugins: [preact()],
  server: { port: 5173, proxy: { '/api': api, '/auth': api } },
})

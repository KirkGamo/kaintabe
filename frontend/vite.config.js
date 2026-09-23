import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Testing the Telegram Mini App locally goes through an https cloudflared quick tunnel
    allowedHosts: ['.trycloudflare.com'],
    // With VITE_API_URL empty, API calls are same-origin (/api/...) and forwarded to the local backend,
    // so one tunnel serves both the page and the API
    proxy: { '/api': 'http://localhost:8000' },
  },
})

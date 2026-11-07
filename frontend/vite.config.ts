import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

// Dev: Vite on 5173 proxies /api to FastAPI on 8000.
// Demo: FastAPI serves frontend/dist on 8000 (one origin), so no proxy is involved.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      // Registered from main.tsx on /phone only, so the dashboard is never served from a stale cache.
      injectRegister: false,
      includeAssets: ['favicon.svg', 'icons/apple-touch-icon.png'],
      manifest: {
        name: 'PowerSync',
        short_name: 'PowerSync',
        start_url: '/phone',
        scope: '/',
        display: 'standalone',
        theme_color: '#f3f4ef',
        background_color: '#f3f4ef',
        // Icon files are added at B6 (icons agreed with A at 1:20).
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        // Cache the app shell only. Never cache /api.
        navigateFallback: '/index.html',
        navigateFallbackDenylist: [/^\/api\//, /^\/dashboard/],
        runtimeCaching: [],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: false },
    },
  },
})

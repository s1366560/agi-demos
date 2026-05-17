import path from 'node:path';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { visualizer } from 'rollup-plugin-visualizer';
import { defineConfig } from 'vite';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // Note: Ant Design 6+ has built-in tree-shaking support and uses CSS-in-JS
    // No additional plugin needed for on-demand imports
    // Bundle analyzer - generates stats.html after build
    visualizer({
      open: false,
      gzipSize: true,
      brotliSize: true,
      filename: 'dist/stats.html',
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 3000,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
    headers: {
      'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY',
      'Referrer-Policy': 'strict-origin-when-cross-origin',
      'Permissions-Policy': 'camera=(self), microphone=(self), geolocation=()',
    },
  },
  build: {
    outDir: 'dist',
    // Report chunk sizes
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined;

          if (
            /[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom)[\\/]/.test(
              id
            )
          ) {
            return 'vendor-react';
          }
          if (/[\\/]node_modules[\\/](antd|@ant-design|rc-[^\\/]+)[\\/]/.test(id)) {
            return 'vendor-antd';
          }
          if (
            /[\\/]node_modules[\\/](@tanstack|zustand|use-sync-external-store|swr)[\\/]/.test(id)
          ) {
            return 'vendor-state';
          }
          if (
            /[\\/]node_modules[\\/](i18next|react-i18next|i18next-browser-languagedetector)[\\/]/.test(
              id
            )
          ) {
            return 'vendor-i18n';
          }
          if (/[\\/]node_modules[\\/](axios|uuid)[\\/]/.test(id)) {
            return 'vendor-utils';
          }

          return undefined;
        },
      },
    },
  },
});

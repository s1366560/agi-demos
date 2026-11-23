import path from 'node:path';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { visualizer } from 'rollup-plugin-visualizer';
import { defineConfig, type Plugin } from 'vite';

const projectPackageTranslations: Plugin = {
  name: 'project-package-translations',
  enforce: 'pre',
  transform(source: string, id: string) {
    const locales = path.resolve(__dirname, 'src/locales');
    if (id !== path.join(locales, 'en-US.json') && id !== path.join(locales, 'zh-CN.json')) return;
    const { common, login, forceChangePassword, projectPackages, tenant } = JSON.parse(
      source
    ) as typeof import('./src/locales/en-US.json');
    return JSON.stringify({
      common,
      login,
      forceChangePassword,
      projectPackages,
      tenant: { pluginHub: { optionalBusiness: tenant.pluginHub.optionalBusiness } },
    });
  },
};

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const packageHost = mode === 'project-packages';
  return {
    publicDir: packageHost ? false : 'public',
    plugins: [
      ...(packageHost ? [projectPackageTranslations] : []),
      react(),
      tailwindcss(),
      // Note: Ant Design 6+ has built-in tree-shaking support and uses CSS-in-JS
      // No additional plugin needed for on-demand imports
      // Bundle analyzer - generates stats.html after build
      ...(packageHost
        ? []
        : [
            visualizer({
              open: false,
              gzipSize: true,
              brotliSize: true,
              filename: 'dist/stats.html',
            }),
          ]),
    ],
    resolve: {
      dedupe: ['react-router-dom', 'chart.js', 'react-chartjs-2', 'i18next', 'react-markdown', 'use-debounce', 'zustand', '@tanstack/react-query', '@tanstack/react-virtual', 'react', 'react-dom', 'react-i18next', 'antd', 'lucide-react'],
      alias: {
        '@': path.resolve(__dirname, './src'),
        '@business': path.resolve(__dirname, '../plugins/business'),
        '@agistack/plugin-slots': path.resolve(
          __dirname,
          '../agi-stack/packages/plugin-slots/src/index.ts'
        ),
        '@agistack/plugin-runtime': path.resolve(
          __dirname,
          '../agi-stack/packages/plugin-runtime/src/index.ts'
        ),
      },
    },
    server: {
      host: '0.0.0.0',
      port: 3000,
      strictPort: true,
      fs: {
        // Shared workspace packages live outside web/, so Vite must be allowed
        // to serve them after resolving the aliases above.
        allow: [path.resolve(__dirname, '..')],
      },
      proxy: {
        '/api': {
          target: process.env.MEMSTACK_API_PROXY || 'http://localhost:8000',
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
      outDir: packageHost ? 'dist-project-packages' : 'dist',
      ...(packageHost
        ? { rollupOptions: { input: path.resolve(__dirname, 'project-packages.html') } }
        : {}),
      // Report chunk sizes
      chunkSizeWarningLimit: 1000,
    },
  };
});

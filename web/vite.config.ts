import path from 'node:path';

import { richPageFramePlugin } from '../agi-stack/packages/plugin-slots/viteRichPageFrame.mjs';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { visualizer } from 'rollup-plugin-visualizer';
import { defineConfig } from 'vite';

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const packageHost = !['full', 'compat', 'test'].includes(mode);
  return {
    publicDir: packageHost ? false : 'public',
    plugins: [
      richPageFramePlugin(),
      ...(['full', 'compat'].includes(mode)
        ? [
            {
              name: 'full-client-entry',
              transformIndexHtml: {
                order: 'pre' as const,
                handler(html: string) {
                  return html.replace('/src/projectPackages/main.tsx', mode === 'full' ? '/src/fullHost/main.tsx' : '/src/main.tsx');
                },
              },
            },
          ]
        : []),
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
              filename: mode === 'compat' ? 'dist-compat/stats.html' : 'dist/stats.html',
            }),
          ]),
    ],
    resolve: {
      dedupe: ['cytoscape', 'three', 'three-mesh-bvh', '@react-three/drei', '@react-three/fiber', 'docx-preview', 'xlsx', 'react-syntax-highlighter', '@xterm/addon-fit', '@xterm/addon-web-links', '@xterm/xterm',
        'react-router-dom',
        'chart.js',
        'react-chartjs-2',
        'i18next',
        'react-markdown', 'remark-gfm', 'remark-math', 'rehype-katex', 'katex',
        'use-debounce',
        'uuid',
        'zustand',
        '@tanstack/react-query',
        '@tanstack/react-virtual',
        'react',
        'react-dom',
        'react-i18next',
        'antd',
        'lucide-react',
      ],
      alias: {
      '@copilotkit/a2ui-renderer/dist': path.resolve(__dirname, './node_modules/@copilotkit/a2ui-renderer/dist'),
        '@': path.resolve(__dirname, './src'),
        ...(['compat', 'test'].includes(mode) ? { '@business': path.resolve(__dirname, '../plugins/business') } : {}),
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
      outDir: mode === 'compat' ? 'dist-compat' : mode === 'project-packages' ? 'dist-project-packages' : 'dist',
      ...(mode === 'project-packages'
        ? { rollupOptions: { input: path.resolve(__dirname, 'project-packages.html') } }
        : {}),
      // Report chunk sizes
      chunkSizeWarningLimit: 1000,
    },
  };
});

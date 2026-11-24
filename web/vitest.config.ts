import path from 'path'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

function katexCssPlugin() {
  return {
    name: 'mock-katex-css',
    enforce: 'pre' as const,
    resolveId(id: string) {
      if (id.includes('katex') && id.endsWith('.css')) {
        return path.resolve(__dirname, './src/test/__mocks__/empty.ts');
      }
      return undefined;
    },
  };
}

export default defineConfig({
  plugins: [katexCssPlugin(), react()],
  resolve: {
    dedupe: ['cytoscape', 'three', 'three-mesh-bvh', '@react-three/drei', '@react-three/fiber', 'docx-preview', 'xlsx', 'react-syntax-highlighter', '@xterm/addon-fit', '@xterm/addon-web-links', '@xterm/xterm', 'react-router-dom', 'chart.js', 'react-chartjs-2', 'i18next', 'react-markdown', 'remark-gfm', 'remark-math', 'rehype-katex', 'katex', 'use-debounce', 'uuid', 'zustand', '@tanstack/react-query', '@tanstack/react-virtual', 'react-i18next', 'antd', 'lucide-react', 'vitest'],
    alias: {
      '@copilotkit/a2ui-renderer/dist': path.resolve(__dirname, './node_modules/@copilotkit/a2ui-renderer/dist'),
      '@': path.resolve(__dirname, './src'),
      '@desktop': path.resolve(__dirname, '../agi-stack/apps/desktop/src'),
      '@business': path.resolve(__dirname, '../plugins/business'),
      react: path.resolve(__dirname, './node_modules/react'),
      'react/jsx-runtime': path.resolve(__dirname, './node_modules/react/jsx-runtime'),
      'react/jsx-dev-runtime': path.resolve(__dirname, './node_modules/react/jsx-dev-runtime'),
      'react-dom': path.resolve(__dirname, './node_modules/react-dom'),
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
  server: { fs: { allow: [path.resolve(__dirname, '..')] } },
  test: {
    globals: true,
    testTimeout: 20000,
    environment: 'happy-dom',
    css: true,
    server: {
      deps: {
        inline: [/katex/],
      },
    },
    setupFiles: ['./src/test/setup-macrotask.ts', './src/test/setup.ts'],
    include: ['src/test/**/*.{test,spec}.{js,mjs,cjs,ts,mts,cts,jsx,tsx}', '../plugins/business/*/tests/**/*.test.tsx'],
    exclude: ['**/node_modules/**', '**/dist/**', '**/e2e/**', '**/.{idea,git,cache,output,temp}/**'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'src/test/',
        '**/*.d.ts',
        '**/*.config.*',
        '**/mockData',
        'dist/',
      ],
      thresholds: {
        lines: 50,
        functions: 50,
        branches: 50,
        statements: 50,
      },
    },
  },
})

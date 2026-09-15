import path from 'node:path';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { rendererRootHotReload } from './scripts/rendererRootHotReload.mjs';

export default defineConfig({
  base: './',
  plugins: [rendererRootHotReload(__dirname), react()],
  resolve: {
    alias: {
      '@agistack/plugin-runtime': path.resolve(
        __dirname,
        '../../packages/plugin-runtime/src/index.ts'
      ),
      '@agistack/plugin-slots': path.resolve(
        __dirname,
        '../../packages/plugin-slots/src/index.ts'
      ),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});

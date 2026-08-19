import path from 'node:path';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  plugins: [react()],
  resolve: {
    alias: {
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

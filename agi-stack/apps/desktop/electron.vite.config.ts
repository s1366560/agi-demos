import react from '@vitejs/plugin-react';
import { defineConfig } from 'electron-vite';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const desktopRoot = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  main: {
    build: {
      outDir: resolve(desktopRoot, 'out/main'),
      rollupOptions: {
        input: resolve(desktopRoot, 'electron/main/index.ts'),
        output: {
          format: 'es',
          entryFileNames: 'index.js',
        },
      },
    },
  },
  preload: {
    build: {
      outDir: resolve(desktopRoot, 'out/preload'),
      rollupOptions: {
        input: resolve(desktopRoot, 'electron/preload/index.ts'),
        output: {
          format: 'cjs',
          entryFileNames: 'index.cjs',
        },
      },
    },
  },
  renderer: {
    root: desktopRoot,
    base: './',
    plugins: [react()],
    build: {
      outDir: resolve(desktopRoot, 'out/renderer'),
      emptyOutDir: true,
      rollupOptions: {
        input: resolve(desktopRoot, 'index.html'),
      },
    },
  },
});

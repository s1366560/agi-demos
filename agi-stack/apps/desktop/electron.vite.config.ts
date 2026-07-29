import react from '@vitejs/plugin-react';
import { defineConfig } from 'electron-vite';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const desktopRoot = dirname(fileURLToPath(import.meta.url));

// Generated output directories must not trigger renderer page reloads or
// main/preload rebuilds while the dev app is running (QA traces, release
// packaging, and legacy bundles are written next to the sources).
const generatedOutputWatchIgnores = [
  '**/browser-qa/results/**',
  '**/browser-qa/report/**',
  '**/release/**',
  '**/dist/**',
  '**/out/**',
];

export default defineConfig(({ command }) => ({
  main: {
    build: {
      outDir: resolve(desktopRoot, 'out/main'),
      // `build.watch` is dev-only input for electron-vite; enabling it in a
      // production build would leave Rollup in watch mode forever.
      ...(command === 'serve' ? { watch: { exclude: generatedOutputWatchIgnores } } : {}),
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
      ...(command === 'serve' ? { watch: { exclude: generatedOutputWatchIgnores } } : {}),
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
    server: {
      watch: {
        ignored: generatedOutputWatchIgnores,
      },
    },
    build: {
      outDir: resolve(desktopRoot, 'out/renderer'),
      emptyOutDir: true,
      rollupOptions: {
        input: resolve(desktopRoot, 'index.html'),
      },
    },
  },
}));

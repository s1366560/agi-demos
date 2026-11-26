import { richPageFramePlugin } from '../../packages/plugin-slots/viteRichPageFrame.mjs';
import { compatibilityProfile, fullDesktopProfile, legacyRendererEntry } from './scripts/legacyRendererProfile';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'electron-vite';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { rendererRootHotReload } from './scripts/rendererRootHotReload.mjs';

const desktopRoot = dirname(fileURLToPath(import.meta.url));

const desktopOutput = compatibilityProfile ? 'out-compat' : 'out';

// Generated output directories must not trigger renderer page reloads or
// main/preload rebuilds while the dev app is running (QA traces, release
// packaging, and legacy bundles are written next to the sources).
const generatedOutputWatchIgnores = [
  '**/browser-qa/results/**',
  '**/browser-qa/report/**',
  '**/release/**',
  '**/dist/**',
  '**/out/**',
  '**/out-compat/**',
];

export default defineConfig(({ command }) => ({
  main: {
    define: {
      __AGISTACK_FULL_DESKTOP__: JSON.stringify(fullDesktopProfile),
      __AGISTACK_COMPAT_DESKTOP__: JSON.stringify(compatibilityProfile),
    },
    build: {
      outDir: resolve(desktopRoot, desktopOutput, 'main'),
      // `build.watch` is dev-only input for electron-vite; enabling it in a
      // production build would leave Rollup in watch mode forever.
      ...(command === 'serve' ? { watch: { exclude: generatedOutputWatchIgnores } } : {}),
      rollupOptions: {
        ...(fullDesktopProfile ? {} : {
          treeshake: { moduleSideEffects: (id: string) => !id.includes('/electron/main/iab/') },
        }),
        input: {
          index: resolve(desktopRoot, 'electron/main/index.ts'),
        },
        output: {
          format: 'es',
          entryFileNames: '[name].js',
        },
      },
    },
  },
  preload: {
    define: { __AGISTACK_FULL_DESKTOP__: JSON.stringify(fullDesktopProfile) },
    build: {
      outDir: resolve(desktopRoot, desktopOutput, 'preload'),
      ...(command === 'serve' ? { watch: { exclude: generatedOutputWatchIgnores } } : {}),
      rollupOptions: {
        input: {
          index: resolve(desktopRoot, 'electron/preload/index.ts'),
          ...(fullDesktopProfile ? {
            iab: resolve(desktopRoot, 'electron/preload/iabPreload.ts'),
            mcpAppGuest: resolve(desktopRoot, 'electron/preload/mcpAppGuestPreload.ts'),
          } : {}),
        },
        output: {
          format: 'cjs',
          entryFileNames: '[name].cjs',
        },
      },
    },
  },
  renderer: {
    root: desktopRoot,
    base: './',
    plugins: [
      rendererRootHotReload(desktopRoot),
      react(),
      richPageFramePlugin(),
      ...(fullDesktopProfile ? [legacyRendererEntry] : []),
    ],
    resolve: {
      dedupe: ['@xterm/addon-fit', '@xterm/addon-web-links', '@xterm/xterm', 'react', 'react-dom', '@radix-ui/themes', '@radix-ui/react-icons'],
      alias: {
        '@desktop': resolve(desktopRoot, 'src'),
        ...(fullDesktopProfile ? {'@business': resolve(desktopRoot, '../../../plugins/business')} : {}),
        '@agistack/plugin-runtime': resolve(
          desktopRoot,
          '../../packages/plugin-runtime/src/index.ts',
        ),
        '@agistack/plugin-slots': resolve(
          desktopRoot,
          '../../packages/plugin-slots/src/index.ts',
        ),
      },
    },
    server: {
      host: '127.0.0.1',
      fs: { allow: [resolve(desktopRoot, '../../..')] },
      watch: {
        ignored: generatedOutputWatchIgnores,
      },
    },
    build: {
      outDir: resolve(desktopRoot, desktopOutput, 'renderer'),
      emptyOutDir: true,
      rollupOptions: {
        input: { index: resolve(desktopRoot, 'index.html'), ...(fullDesktopProfile
          ? { mcpApp: resolve(desktopRoot, 'mcp-app.html') } : {}) },
      },
    },
  },
}));

import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import tailwind from '@tailwindcss/postcss';
import postcss from 'postcss';
import { buildPackagePages } from '../../../../../sdk/memstack-plugin-sdk/buildPages.mjs';

const directory = fileURLToPath(new URL('.', import.meta.url));
await buildPackagePages({
  root: fileURLToPath(new URL('../../', import.meta.url)),
  sourceDirectory: 'ui/signed',
  entries: {
    directory: { web: 'WebDirectoryPage.tsx', 'desktop-renderer': 'DesktopDirectoryPage.tsx' },
    create: { web: 'WebCreatePage.tsx', 'desktop-renderer': 'DesktopCreatePage.tsx' },
  },
  plugins: [
    {
      name: 'package-tailwind',
      setup(build) {
        const require = createRequire(import.meta.url);
        build.onResolve(
          { filter: /^(react|react-dom|react-i18next|react-router-dom|i18next)(\/.*)?$/ },
          ({ path }) => ({ path: require.resolve(path) })
        );
        const sources = {
          '@/utils/objectiveProgress': '../../../../../web/src/utils/objectiveProgress.ts',
          '@/utils/workspaceTaskProjection':
            '../../../../../web/src/utils/workspaceTaskProjection.ts',
          '@/hooks/useThemeColor': './themeColor.ts',
          '@desktop/i18n': '../../../../../agi-stack/apps/desktop/src/i18nContext.ts',
          '@desktop/api/client': '../../../../../agi-stack/apps/desktop/src/api/desktopApiError.ts',
        };
        build.onResolve({ filter: /^(@desktop\/|@\/)/ }, ({ path }) =>
          sources[path] ? { path: resolve(directory, sources[path]) } : undefined
        );
        build.onLoad({ filter: /workspace(Create|Directory)\.css$/ }, async ({ path }) => {
          const result = await postcss([tailwind({ base: directory, optimize: true })]).process(
            await readFile(path, 'utf8'),
            { from: path }
          );
          return { contents: result.css, loader: 'css' };
        });
      },
    },
  ],
});

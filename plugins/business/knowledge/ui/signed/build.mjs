import { resolve } from 'node:path';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import tailwind from '@tailwindcss/postcss';
import postcss from 'postcss';
import { buildPackagePages } from '../../../../../sdk/memstack-plugin-sdk/buildPages.mjs';

const directory = fileURLToPath(new URL('.', import.meta.url));
await buildPackagePages({
  root: fileURLToPath(new URL('../../', import.meta.url)),
  sourceDirectory: 'ui/signed',
  contribution: 'workers/graph_projection/contributions.json',
  entries: {
    memories: { web: 'MemoriesPage.tsx', 'desktop-renderer': 'DesktopMemoriesPage.tsx' },
    'memory-editor': { web: 'MemoriesPage.tsx', 'desktop-renderer': 'DesktopMemoriesPage.tsx' },
    'desktop-memory-editor': 'DesktopMemoriesPage.tsx',
    'memory-detail': 'MemoriesPage.tsx',
    entities: { web: 'EntitiesPage.tsx', 'desktop-renderer': 'DesktopEntitiesPage.tsx' },
  },
  plugins: [
    {
      name: 'package-tailwind',
      setup(build) {
        const require = createRequire(import.meta.url);
        build.onResolve(
          { filter: /^(react|react-dom|react-i18next|react-router-dom|i18next)(\/.*)?$/ },
          ({ path }) => ({ path: require.resolve(path) }),
        );
        const aliases = {
          '@business/knowledge/ui/web/services/knowledgeApi': './memoryApi.ts',
          '@/components/agent/chat/MarkdownContent': './MarkdownPreview.tsx',
          '@/hooks/useUnsavedChangesWarning':
            '../../../../../web/src/hooks/useUnsavedChangesWarning.ts',
          '@/services/taskStream': './indexTask.ts',
          '@/utils/date': '../../../../../sdk/memstack-plugin-sdk/ui/localDate.ts',
          '@/utils/logger': './logger.ts',
          '@/components/common': '../../../../../web/src/components/common/AppModal.tsx',
          '@/components/common/index': '../../../../../web/src/components/common/AppModal.tsx',
          '@/components/project/EditMemoryModal': '../web/project/EditMemoryModal.tsx',
          '@/components/shared/Pagination':
            '../../../../../sdk/memstack-plugin-sdk/ui/Pagination.tsx',
          '@/components/shared/modals/DeleteConfirmationModal':
            '../../../../../web/src/components/shared/modals/DeleteConfirmationModal.tsx',
          '@/components/common/SkeletonLoader':
            '../../../../../web/src/components/common/SkeletonLoader.tsx',
          '@/hooks/useProjectBasePath': '../../../../../web/src/hooks/useProjectBasePath.ts',
          '@/utils/confirmAction': '../../../../../sdk/memstack-plugin-sdk/ui/confirmAction.ts',
          '@/hooks/useThemeColor': './appearance.ts',
          '@desktop/api/desktopApiError':
            '../../../../../agi-stack/apps/desktop/src/api/desktopApiError.ts',
          '@desktop/i18n': '../../../../../agi-stack/apps/desktop/src/i18nContext.ts',
        };
        build.onResolve({ filter: /^(@business|@desktop|@)\// }, ({ path }) =>
          aliases[path] ? { path: resolve(directory, aliases[path]) } : undefined,
        );
        build.onResolve(
          { filter: /^(\.\.\/services\/(taskStream|graphService))$/ },
          ({ path }) => ({
            path: resolve(
              directory,
              path.endsWith('taskStream') ? './indexTask.ts' : './optimize.ts',
            ),
          }),
        );
        build.onLoad({ filter: /(entities|memories)\.css$/ }, async ({ path }) => {
          const result = await postcss([tailwind({ base: directory, optimize: true })]).process(
            await readFile(path, 'utf8'),
            { from: path },
          );
          return { contents: result.css, loader: 'css' };
        });
      },
    },
  ],
});

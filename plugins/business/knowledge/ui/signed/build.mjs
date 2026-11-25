import { resolve } from 'node:path';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import tailwind from '@tailwindcss/postcss';
import postcss from 'postcss';
import { buildPackagePages } from '../../../../../sdk/memstack-plugin-sdk/buildPages.mjs';

const directory = fileURLToPath(new URL('.', import.meta.url));
// Bundle the original Web design tokens with the signed page. Host styles do not
// cross the iframe boundary, and importing the whole shell would include its layout.
const webStyles = postcss.parse(await readFile(resolve(directory, '../../../../../web/src/index.css'), 'utf8'));
const webTheme = webStyles.nodes.find((node) => node.type === 'atrule' && node.name === 'theme');
if (!webTheme) throw new Error('The original Web theme is missing');

await buildPackagePages({
  root: fileURLToPath(new URL('../../', import.meta.url)),
  sourceDirectory: 'ui/signed',
  contribution: 'workers/graph_projection/contributions.json',
  entries: {
    'project-search': 'SearchPage.tsx',
    graph: 'GraphPage.tsx',
    memories: 'MemoriesPage.tsx',
    'memory-editor': 'MemoriesPage.tsx',
    'desktop-memory-editor': 'MemoriesPage.tsx',
    'memory-detail': 'MemoriesPage.tsx',
    entities: 'EntitiesPage.tsx',
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
          '@/stores/project': './searchProject.ts',
          '@/utils/downloadJson': '../../../../../web/src/utils/downloadJson.ts',
          '@/stores/theme': './graphAppearance.ts',
          '@/components/shared/ui/StateDisplay': '../../../../../web/src/components/shared/ui/StateDisplay.tsx',
          '@business/knowledge/ui/web/services/graphService': './graphApi.ts',
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
          '@desktop/features/project-knowledge/CloudMemoryRouteContext': '../../../../../agi-stack/apps/desktop/src/features/project-knowledge/CloudMemoryRouteContext.tsx',
          '@desktop/features/project-knowledge/projectGraphMemoryReader': '../../../../../agi-stack/apps/desktop/src/features/project-knowledge/projectGraphMemoryReader.ts',
          '@business/knowledge/ui/desktop/project-knowledge/cloudMemoryUiAuthority': '../desktop/project-knowledge/cloudMemoryUiAuthority.ts',
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
              path.endsWith('taskStream') ? './indexTask.ts' : './graphApi.ts',
            ),
          }),
        );
        build.onLoad({ filter: /(entities|memories|graph-web|search-page)\.css$/ }, async ({ path }) => {
          const stylesheet = await readFile(path, 'utf8');
          const result = await postcss([tailwind({ base: directory, optimize: true })]).process(
            path.endsWith('search-page.css') ? stylesheet + '\n' + webTheme.toString() : stylesheet,
            { from: path },
          );
          return { contents: result.css, loader: 'css' };
        });
      },
    },
  ],
});

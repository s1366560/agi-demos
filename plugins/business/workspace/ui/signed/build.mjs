import { existsSync } from 'node:fs';
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
    "agent-collab": "GroupChatPage.tsx",
    ...Object.fromEntries(['detail','settings','workspace-members','workspace-posts','workspace-tasks'].map(id=>[id,'BlackboardPage.tsx'])),
    'workspace-task-detail': 'BlackboardPage.tsx',
    overview: 'OverviewWeb.tsx',
    directory: 'WebDirectoryPage.tsx',
    create: 'WebCreatePage.tsx',
  },
  plugins: [
    {
      name: 'package-tailwind',
      setup(build) {
        build.initialOptions.define = {
          ...build.initialOptions.define,
          'import.meta.env.DEV': 'false',
        };
        const require = createRequire(import.meta.url);
        build.onResolve(
          {
            filter:
              /^(react|react-dom|react-i18next|react-router-dom|i18next|@tanstack\/react-virtual|zustand)(\/.*)?$/,
          },
          ({ path }) => ({ path: require.resolve(path) }),
        );
        if (build.initialOptions.entryPoints.includes(resolve(directory, 'GroupChatPage.tsx'))) {
          build.onResolve(
            { filter: /^(@business\/workspace\/ui\/web\/stores\/workspace|@\/stores\/auth)$/ },
            () => ({ path: resolve(directory, 'groupChatStore.ts') }),
          );
        }
        const sources = {
          '@/services/client/httpClient': './blackboardTransport.ts',
          '@/utils/logger': './logger.ts',
          '@/services/agentService': './externalCapabilities.ts',
          '@business/environments/ui/web/services/geneMarketService': './externalCapabilities.ts',
          '@/i18n/config': './boardLocale.ts',
          '@/utils/confirmAction': '../../../../../sdk/memstack-plugin-sdk/ui/confirmAction.ts',
          '@/services/unifiedEventService': './boardRefresh.ts',
          '@/services/client/urlUtils': './blackboardTransport.ts',
          '@/utils/objectiveProgress': '../../../../../web/src/utils/objectiveProgress.ts',
          '@/utils/workspaceTaskProjection':
            '../../../../../web/src/utils/workspaceTaskProjection.ts',
          '@/hooks/useThemeColor': './themeColor.ts',
          '@desktop/i18n': '../../../../../agi-stack/apps/desktop/src/i18nContext.ts',
          '@desktop/api/client': '../../../../../agi-stack/apps/desktop/src/api/desktopApiError.ts',
        };
        build.onResolve({ filter: /^(@business\/|@desktop\/|@\/)/ }, ({ path }) =>
          sources[path] ? { path: resolve(directory, sources[path]) } : undefined,
        );
        build.onResolve({ filter: /^\.\/RosterControls$/ }, () => ({
          path: resolve(directory, './ConversationRoster.tsx'),
        }));
        build.onResolve({ filter: /^\.\.\/hooks\/useBlackboardSSE$/ }, () => ({
          path: resolve(directory, './boardRefresh.ts'),
        }));
        build.onResolve({ filter: /^(@\/|@business\/|@desktop\/)/ }, ({ path }) => {
          const file = path.startsWith('@business/')
            ? resolve(directory, '../../..', path.slice(10))
            : path.startsWith('@desktop/')
              ? resolve(directory, '../../../../../agi-stack/apps/desktop/src', path.slice(9))
              : resolve(directory, '../../../../../web/src', path.slice(2));
          for (const suffix of ['', '.ts', '.tsx', '.css', '/index.ts', '/index.tsx']) {
            if (existsSync(file + suffix) && !(!suffix && !file.match(/\.(css|json)$/)))
              return { path: file + suffix };
          }
        });
        build.onResolve({ filter: /^\.\/openPlanPreview$/ }, () => ({ path: resolve(directory, './externalCapabilities.ts') }));
        build.onLoad(
          { filter: /(blackboard|workspace(Create|Directory|Overview))\.css$/ },
          async ({ path }) => {
            const result = await postcss([tailwind({ base: directory, optimize: true })]).process(
              await readFile(path, 'utf8'),
              { from: path },
            );
            return { contents: result.css, loader: 'css' };
          },
        );
      },
    },
  ],
});

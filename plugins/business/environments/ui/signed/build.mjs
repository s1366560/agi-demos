import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import tailwind from '@tailwindcss/postcss';
import postcss from 'postcss';
import { fileURLToPath } from 'node:url';
import { buildPackagePages } from '../../../../../sdk/memstack-plugin-sdk/buildPages.mjs';

const local = (name) => fileURLToPath(new URL(name, import.meta.url));
await buildPackagePages({
  root: local('../../'),
  sourceDirectory: 'ui/signed',
  entries: {
    'runtime-pool': 'PoolWeb.tsx',
    deployments: 'TenantDeployWeb.tsx',
    sandbox: 'ProjectSandboxPage.tsx',
    'sandbox-interaction': 'InteractionPage.tsx',
    'tenant-clusters': 'ClustersWeb.tsx',
  },
  plugins: [
    {
      name: 'cluster-runtime',
      setup(build) {
        const require = createRequire(import.meta.url);
        build.onResolve(
          { filter: /^(react|react-dom|react-i18next|i18next)(\/.*)?$/ },
          ({ path }) => ({ path: require.resolve(path) }),
        );
        build.onResolve({ filter: /^@\/vendor\/kasmvnc\// }, ({ path }) => ({
          path: local('../../../../../web/src/' + path.slice(2)),
        }));
        const aliases = {
          '../services/poolService': './signedPoolService.ts',
          '@/utils/logger': '../../../../../web/src/utils/logger.ts',
          '@/components/common/StatusTag': '../../../../../web/src/components/common/StatusTag.tsx',
          '@desktop/api/client': '../../../../../agi-stack/apps/desktop/src/api/desktopApiError.ts',
          '@/stores/project': './instanceWizardScope.ts',
          '@/stores/tenant': './instanceWizardScope.ts',
          '@business/workspace/ui/web/stores/workspace': './instanceWizardScope.ts',
          '@/utils/date': '../../../../../sdk/memstack-plugin-sdk/ui/localDate.ts',
          '@/utils/confirmAction': '../../../../../sdk/memstack-plugin-sdk/ui/confirmAction.ts',
          '@/components/ui/lazyAntd': '../../../../../web/src/components/ui/lazyAntd.tsx',
          '@/components/common/SkeletonLoader':
            '../../../../../web/src/components/common/SkeletonLoader.tsx',
          '@/hooks/useUnsavedChangesWarning':
            '../../../../../web/src/hooks/useUnsavedChangesWarning.ts',
          '../services/deployService': './deploymentService.ts',
          './deployProgressStream': './deploymentService.ts',
          '../services/instanceTemplateService': './templateService.ts',
          '../stores/geneMarket': './instanceWizardScope.ts',
          '../stores/instance': './instanceWizardScope.ts',

          '@/plugins/webOperationAdmissionV2': './operationScope.ts',
          '@/utils/tokenResolver': './isolatedTransport.ts',
          '@/services/client/urlUtils': './isolatedTransport.ts',
          '@business/environments/ui/web/services/sandboxWebSocketUtils': './isolatedTransport.ts',
          '@/hooks/useThemeColor': './themeColors.ts',
          '@/components/common/Spinner': '../../../../../web/src/components/common/Spinner.tsx',
        };
        build.onResolve({ filter: /^(?:@(?:business|desktop)?\/|\.\.?\/)/ }, ({ path }) =>
          aliases[path] ? { path: local(aliases[path]) } : undefined,
        );
        build.initialOptions.define = {
          ...build.initialOptions.define,
          'import.meta.env.DEV': 'false',
          'import.meta.env.VITE_DEBUG_LOGS': 'undefined',
          'import.meta.env.VITE_ENABLE_DEBUG_LOGS': 'undefined',
        };
        build.onLoad(
          { filter: /(?:clusters-web|project-sandbox|tenant-deploy|interaction)\.css$/ },
          async ({ path }) => {
            const result = await postcss([tailwind({ base: local('.'), optimize: true })]).process(
              await readFile(path, 'utf8'),
              { from: path },
            );
            return { contents: result.css, loader: 'css' };
          },
        );
        build.onResolve({ filter: /^@desktop\/i18n$/ }, () => ({
          path: local('./desktopI18n.tsx'),
        }));
        build.onResolve({ filter: /^\.\.\/services\/clusterService$/ }, () => ({
          path: local('./clusterService.ts'),
        }));
      },
    },
  ],
});

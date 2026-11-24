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
    sandbox: 'ProjectSandboxPage.tsx',
    'sandbox-interaction': 'InteractionPage.tsx',
    'tenant-clusters': { web: 'ClustersWeb.tsx', 'desktop-renderer': 'ClustersDesktop.tsx' },
  },
  plugins: [
    {
      name: 'cluster-runtime',
      setup(build) {
        const require = createRequire(import.meta.url);
        build.onResolve(
          { filter: /^(react|react-dom|react-i18next|i18next)(\/.*)?$/ },
          ({ path }) => ({ path: require.resolve(path) })
        );
        build.onResolve({ filter: /^@\/vendor\/kasmvnc\// }, ({ path }) => ({
          path: local('../../../../../web/src/' + path.slice(2)),
        }));
        const aliases = {
          '@/plugins/webOperationAdmissionV2': './operationScope.ts',
          '@/utils/tokenResolver': './isolatedTransport.ts',
          '@/services/client/urlUtils': './isolatedTransport.ts',
          '@business/environments/ui/web/services/sandboxWebSocketUtils': './isolatedTransport.ts',
          '@/hooks/useThemeColor': './themeColors.ts',
          '@/components/common/Spinner': '../../../../../web/src/components/common/Spinner.tsx',
        };
        build.onResolve({ filter: /^(@|@business)\// }, ({ path }) =>
          aliases[path] ? { path: local(aliases[path]) } : undefined
        );
        build.initialOptions.define = {
          ...build.initialOptions.define,
          'import.meta.env.DEV': 'false',
        };
        build.onLoad(
          { filter: /(?:clusters-web|project-sandbox|interaction)\.css$/ },
          async ({ path }) => {
            const result = await postcss([tailwind({ base: local('.'), optimize: true })]).process(
              await readFile(path, 'utf8'),
              { from: path }
            );
            return { contents: result.css, loader: 'css' };
          }
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

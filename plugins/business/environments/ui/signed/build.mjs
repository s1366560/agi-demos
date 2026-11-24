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
    'tenant-clusters': { web: 'ClustersWeb.tsx', 'desktop-renderer': 'ClustersDesktop.tsx' },
  },
  plugins: [
    {
      name: 'cluster-runtime',
      setup(build) {
        build.initialOptions.define = {
          ...build.initialOptions.define,
          'import.meta.env.DEV': 'false',
        };
        build.onLoad({ filter: /(?:clusters-web|project-sandbox)\.css$/ }, async ({ path }) => {
          const result = await postcss([tailwind({ base: local('.'), optimize: true })]).process(
            await readFile(path, 'utf8'),
            { from: path }
          );
          return { contents: result.css, loader: 'css' };
        });
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

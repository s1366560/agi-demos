import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import tailwind from '@tailwindcss/postcss';
import postcss from 'postcss';
import { buildPackagePages } from '../../../../../sdk/memstack-plugin-sdk/buildPages.mjs';

const directory = fileURLToPath(new URL('.', import.meta.url));
await buildPackagePages({
  root: fileURLToPath(new URL('../../', import.meta.url)),
  sourceDirectory: 'ui/signed',
  contribution: 'contributions.json',
  entries: {
    schedules: 'CronJobsPage.tsx',
    'workflow-patterns': 'WorkflowPatternsPage.tsx',
    playbooks: { web: 'PlaybooksWeb.tsx', 'desktop-renderer': 'PlaybooksDesktop.tsx' },
  },
  plugins: [
    {
      name: 'package-tailwind',
      setup(build) {
        build.initialOptions.define = {
          ...build.initialOptions.define,
          'import.meta.env.DEV': 'false',
        };
        const local = (name) => fileURLToPath(new URL(name, import.meta.url));
        build.onResolve({ filter: /^\.\.\/services\/cronService$/ }, () => ({
          path: local('./cronService.ts'),
        }));
        build.onResolve({ filter: /^@\/types\/common$/ }, () => ({
          path: local('./pageError.ts'),
        }));
        build.onResolve({ filter: /^@\/utils\/date$/ }, () => ({
          path: local('../../../../../sdk/memstack-plugin-sdk/ui/localDate.ts'),
        }));
        build.onResolve({ filter: /^@\/utils\/confirmAction$/ }, () => ({
          path: local('../../../../../sdk/memstack-plugin-sdk/ui/confirmAction.ts'),
        }));
        build.onLoad({ filter: /\.css$/ }, async ({ path }) => {
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

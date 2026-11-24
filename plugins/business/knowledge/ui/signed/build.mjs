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
  entries: { entities: 'EntitiesPage.tsx' },
  plugins: [{
    name: 'package-tailwind',
    setup(build) {
      build.onLoad({ filter: /entities\.css$/ }, async ({ path }) => {
        const result = await postcss([tailwind({ base: directory, optimize: true })])
          .process(await readFile(path, 'utf8'), { from: path });
        return { contents: result.css, loader: 'css' };
      });
    },
  }],
});

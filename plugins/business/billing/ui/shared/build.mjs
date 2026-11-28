import { readFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import tailwind from '@tailwindcss/postcss';
import postcss from 'postcss';
import { buildPackagePages } from '../../../../../sdk/memstack-plugin-sdk/buildPages.mjs';

await buildPackagePages({
  root: fileURLToPath(new URL('../../', import.meta.url)),
  sourceDirectory: 'ui/shared',
  entries: {
    'tenant-account': 'WebBillingPage.tsx',
  },
  plugins: [{
    name: 'billing-original-views',
    setup(build) {
      build.initialOptions.alias = { react: fileURLToPath(new URL('./node_modules/react', import.meta.url)), 'react-dom': fileURLToPath(new URL('./node_modules/react-dom', import.meta.url)), '@desktop': fileURLToPath(new URL('../../../../../agi-stack/apps/desktop/src', import.meta.url)) };
      build.onLoad({ filter: /webBilling\.css$/ }, async ({ path }) => {
        const css = await postcss([tailwind({ base: dirname(path), optimize: true })])
          .process(await readFile(path, 'utf8'), { from: path });
        return { contents: css.css, loader: 'css' };
      });
    },
  }],
  banner: { js: '/*! React and React DOM\n' +
    await readFile(new URL('node_modules/react/LICENSE', import.meta.url), 'utf8') + '\n*/' },
});

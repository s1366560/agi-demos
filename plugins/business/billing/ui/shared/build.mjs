import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { buildPackagePages } from '../../../../../sdk/memstack-plugin-sdk/buildPages.mjs';

await buildPackagePages({
  root: fileURLToPath(new URL('../../', import.meta.url)),
  sourceDirectory: 'ui/shared',
  entries: { account: 'AccountPage.tsx' },
  banner: {
    js: '/*! React and React DOM\n' +
      await readFile(new URL('node_modules/react/LICENSE', import.meta.url), 'utf8') + '\n*/',
  },
});

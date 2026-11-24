import { fileURLToPath } from 'node:url';
import { buildPackagePages } from '../../../../../sdk/memstack-plugin-sdk/buildPages.mjs';

await buildPackagePages({
  root: fileURLToPath(new URL('../../', import.meta.url)),
  sourceDirectory: 'ui/signed',
  entries: {},
  resourceEntries: { 'ui/transcript.js': 'transcript.tsx' },
});

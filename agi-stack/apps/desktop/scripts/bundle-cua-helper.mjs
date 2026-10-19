import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createCuaMacBundle, cuaMacBundleName } from './cua-layout.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
await createCuaMacBundle({
  executable: resolve(root, 'cua-helper/bin/cua-helper'),
  lockedUse: resolve(root, 'cua-helper/bin/locked-use'),
  desktopRoot: root,
  destination: resolve(root, 'cua-helper/bin', cuaMacBundleName),
  identity: process.env.MEMSTACK_CUA_CODESIGN_IDENTITY ?? '-',
  hardenedRuntime: Boolean(process.env.MEMSTACK_CUA_CODESIGN_IDENTITY),
});

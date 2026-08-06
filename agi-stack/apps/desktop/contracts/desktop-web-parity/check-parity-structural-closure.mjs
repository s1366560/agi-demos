import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

import { assertParityStructuralClosure } from './parity-structural-closure.mjs';

const manifestUrl = process.argv[2]
  ? pathToFileURL(resolve(process.argv[2]))
  : new URL('./parity-manifest.v3.json', import.meta.url);

if (process.argv.length > 3) {
  throw new Error('Usage: node check-parity-structural-closure.mjs [manifest-path]');
}

const manifest = JSON.parse(readFileSync(manifestUrl, 'utf8'));
try {
  assertParityStructuralClosure(manifest);
  console.log(`Verified structural closure for ${manifest.capabilities.length} capabilities.`);
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
}

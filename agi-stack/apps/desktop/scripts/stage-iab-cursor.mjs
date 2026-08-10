import { createHash } from 'node:crypto';
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Stage the compiled agent-cursor content script for the in-app browser.
 *
 * Source of truth: the browser extension's built MV3 output
 * (`apps/browser-extension/.output/chrome-mv3/content-scripts/cursor.js`).
 * The iab backend injects this exact artifact into its WebContentsViews (see
 * `electron/main/iab/iabCursor.ts`). Re-run this script whenever the
 * extension's cursor content script is rebuilt.
 */
const desktopRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const source = resolve(
  desktopRoot,
  '../browser-extension/.output/chrome-mv3/content-scripts/cursor.js',
);
const destinationDirectory = resolve(desktopRoot, 'electron/resources');
const destination = resolve(destinationDirectory, 'iab-cursor.js');

mkdirSync(destinationDirectory, { recursive: true });
copyFileSync(source, destination);
const digest = createHash('sha256').update(readFileSync(destination)).digest('hex');
writeFileSync(
  resolve(destinationDirectory, 'iab-cursor.js.SHA256'),
  `${digest}  iab-cursor.js\n`,
  'utf8',
);
console.log(`staged iab cursor script (${digest.slice(0, 12)}) -> ${destination}`);

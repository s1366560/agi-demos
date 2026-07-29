import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const playwrightConfig = readFileSync(
  new URL('../browser-qa/playwright.config.mjs', import.meta.url),
  'utf8',
);
const desktopMakefile = readFileSync(
  new URL('../../../Makefile', import.meta.url),
  'utf8',
);

test('Browser QA never reuses a server from another checkout', () => {
  assert.match(playwrightConfig, /reuseExistingServer:\s*false/u);
});

test('the canonical Browser QA entry uses the CI execution profile', () => {
  assert.match(
    desktopMakefile,
    /desktop-browser-qa:[\s\S]*?CI=true \$\(PNPM\) run qa:browser/u,
  );
});

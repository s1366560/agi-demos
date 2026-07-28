import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  browserQaManifest,
  buildBrowserQaMatrix,
  discoverBrowserQaScenarios,
} from '../browser-qa/matrix.mjs';

const packageJson = JSON.parse(
  readFileSync(new URL('../package.json', import.meta.url), 'utf8'),
);
const makefile = readFileSync(new URL('../../../Makefile', import.meta.url), 'utf8');

test('Browser QA v1 expands every fixture across locale, viewport, and theme', () => {
  const scenarios = discoverBrowserQaScenarios();
  const matrix = buildBrowserQaMatrix();
  assert.equal(browserQaManifest.contractVersion, 1);
  assert.equal(scenarios.length, 36);
  assert.deepEqual(
    browserQaManifest.locales.map((locale) => locale.id),
    ['en-US', 'zh-CN'],
  );
  assert.deepEqual(
    browserQaManifest.viewports.map(({ width, height }) => [width, height]),
    [
      [1440, 1024],
      [1100, 800],
    ],
  );
  assert.deepEqual(browserQaManifest.themes, ['light', 'dark']);
  assert.equal(matrix.length, 288);
  assert.equal(new Set(matrix.map((variant) => variant.id)).size, matrix.length);
});

test('Desktop exposes pinned Playwright and aggregate parity commands', () => {
  assert.equal(packageJson.devDependencies['@playwright/test'], '1.57.0');
  assert.equal(
    packageJson.scripts['qa:browser'],
    'playwright test --config browser-qa/playwright.config.mjs',
  );
  assert.match(makefile, /^desktop-browser-qa:\s*desktop-deps/mu);
  assert.match(makefile, /^desktop-parity-check:\s*desktop-check desktop-browser-qa/mu);
});

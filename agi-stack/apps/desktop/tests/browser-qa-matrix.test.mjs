import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

import {
  browserQaManifest,
  buildBrowserQaMatrix,
  discoverBrowserQaScenarios,
} from '../browser-qa/matrix.mjs';
import { isExpectedBrowserQaSecurityDiagnostic } from '../browser-qa/diagnostics.mjs';

const packageJson = JSON.parse(
  readFileSync(new URL('../package.json', import.meta.url), 'utf8'),
);
const makefile = readFileSync(new URL('../../../Makefile', import.meta.url), 'utf8');
const terminalQaSource = readFileSync(
  new URL('../src/qa/SessionTerminalQa.tsx', import.meta.url),
  'utf8',
);

test('Browser QA v1 expands fixtures and applicable states across all visual dimensions', () => {
  const scenarios = discoverBrowserQaScenarios();
  const matrix = buildBrowserQaMatrix();
  assert.equal(browserQaManifest.contractVersion, 1);
  assert.equal(scenarios.length, 39);
  assert.deepEqual(
    ['artifact-preview', 'sandbox-runtime', 'workspace-collaboration'].filter(
      (scenario) => !scenarios.some(({ id }) => id === scenario),
    ),
    [],
  );
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
  assert.equal(matrix.length, 416);
  assert.equal(new Set(matrix.map((variant) => variant.id)).size, matrix.length);
  assert.deepEqual(
    matrix
      .filter(({ scenario }) => scenario.id === 'session-steering')
      .map(({ scenario }) => scenario.variantId)
      .filter((value, index, values) => values.indexOf(value) === index)
      .sort(),
    [
      'a2ui-deleted',
      'a2ui-incremental',
      'a2ui-ready',
      'default',
      'elicitation',
      'hitl-answered',
    ],
  );
  assert.deepEqual(
    Object.keys(browserQaManifest.scenarioVariants).sort(),
    ['sandbox-runtime', 'session-steering', 'workspace-collaboration'],
  );
});

test('terminal Browser QA mounts the interactive xterm contract', () => {
  assert.match(terminalQaSource, /interactiveCapability=\{/u);
  assert.match(terminalQaSource, /onTerminalInput=/u);
  assert.match(terminalQaSource, /onTerminalResize=/u);
});

test('Browser QA ignores only the expected opaque sandbox enforcement diagnostics', () => {
  assert.equal(
    isExpectedBrowserQaSecurityDiagnostic(
      'artifact-preview',
      'page',
      "Failed to read the 'localStorage' property from 'Window': The document is sandboxed and lacks the 'allow-same-origin' flag.",
    ),
    true,
  );
  assert.equal(
    isExpectedBrowserQaSecurityDiagnostic(
      'artifact-preview',
      'console',
      "Blocked script execution in 'blob:http://127.0.0.1:5193/1985b031-4281-4ae8-a482-21799c988bac' because the document's frame is sandboxed and the 'allow-scripts' permission is not set.",
    ),
    true,
  );
  assert.equal(
    isExpectedBrowserQaSecurityDiagnostic(
      'workspace-collaboration',
      'console',
      "Blocked script execution in 'blob:http://127.0.0.1:5193/1985b031-4281-4ae8-a482-21799c988bac' because the document's frame is sandboxed and the 'allow-scripts' permission is not set.",
    ),
    false,
  );
  assert.equal(
    isExpectedBrowserQaSecurityDiagnostic(
      'artifact-preview',
      'console',
      'Application failed to render',
    ),
    false,
  );
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

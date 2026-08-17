import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const { SignedUiModuleBoundary, SIGNED_UI_MODULE_SANDBOX, signedModuleDocument } = require(
  '/tmp/agistack-desktop-test-dist/src/features/settings/SignedUiModuleBoundary.js',
);
const { UiSlotRegistry } = require('/tmp/agistack-desktop-test-dist/src/plugins/uiSlotRegistry.js');
const { frontendSlotDefinitions } = require(
  '/tmp/agistack-desktop-test-dist/src/plugins/uiSlotRuntime.js',
);

const config = {
  apiBaseUrl: 'http://127.0.0.1:8088',
  deviceAuthorizationBaseUrl: 'http://127.0.0.1:3000',
  apiKey: '',
  localApiToken: 'session',
  tenantId: 'local',
  projectId: 'local-project',
  workspaceId: '',
  mode: 'local',
  workspaceRoot: '',
};

test('signed frontend module renders in a scripts-only opaque sandbox', () => {
  const markup = renderToStaticMarkup(
    React.createElement(SignedUiModuleBoundary, {
      config,
      pluginId: 'third-party-ui',
      expectedDigest: 'a'.repeat(64),
    }),
  );

  assert.equal(SIGNED_UI_MODULE_SANDBOX, 'allow-scripts');
  assert.equal(SIGNED_UI_MODULE_SANDBOX.includes('allow-same-origin'), false);
  assert.match(markup, /<p[^>]*signed-ui-module-loading/);
});

test('signed module document cannot enable same-origin or referrer access', () => {
  const document = signedModuleDocument('<script>parent.document</script>');

  assert.match(document, /<meta name="referrer" content="no-referrer"/);
  assert.equal(document.includes('srcdoc'), false);
});

test('signed frontend capabilities derive sandboxed module slots from canonical snapshot', () => {
  const digest = 'b'.repeat(64);
  const definitions = frontendSlotDefinitions({
    plugins: [
      {
        schema_version: 1,
        id: 'third-party-ui',
        version: '1.0.0',
        runtime: 'frontend',
        trust: 'signed',
        provides: [
          {
            kind: 'ui_renderer',
            id: 'tool_result_renderer',
            contract: 'ui_renderer:tool-result',
            permissions: ['ui.render'],
          },
        ],
        config: { artifact: { layer_sha256: digest } },
      },
    ],
  });
  const registry = new UiSlotRegistry();
  const disposers = definitions.map((definition) =>
    registry.register(definition, { trust: 'signed', runtime: 'frontend' }),
  );

  assert.equal(definitions.length, 1);
  assert.equal(definitions[0].moduleRef, `signed:${digest}`);
  assert.equal(registry.list('tool_result_renderer').length, 1);
  disposers.forEach((dispose) => dispose());
  assert.equal(registry.list('tool_result_renderer').length, 0);
});

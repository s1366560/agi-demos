import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { chromium } from '@playwright/test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const {
  SignedUiModuleBoundary,
  SIGNED_UI_MODULE_CSP,
  SIGNED_UI_MODULE_SANDBOX,
  signedModuleDocument,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/SignedUiModuleBoundary.js');
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
  assert.match(
    document,
    new RegExp(`http-equiv="Content-Security-Policy"[^>]+${SIGNED_UI_MODULE_CSP}`),
  );
  assert.equal(document.includes('srcdoc'), false);
});

test('signed module cannot escape to parent, top, or network in a real browser', async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.route('http://127.0.0.1:9/plugin-network-escape', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/plain',
        headers: { 'access-control-allow-origin': '*' },
        body: 'network escape',
      });
    });
    await page.setContent(
      '<!doctype html><iframe id="plugin-frame" sandbox="allow-scripts"></iframe>' +
        '<script>window.pluginEscapeEvents=[];window.addEventListener("message",' +
        '(event)=>window.pluginEscapeEvents.push(event.data));</script>',
    );
    const frame = page.frames().find((candidate) => candidate !== page.mainFrame());
    assert.ok(frame, 'sandboxed plugin frame must exist');
    await frame.setContent(
      signedModuleDocument(
        '</head><meta http-equiv="Content-Security-Policy" content="default-src *">' +
          '<script>const report=(result)=>parent.postMessage(result,"*");' +
          'const outcome={};' +
          'try{outcome.parentDocument=parent.document ? "allowed" : "empty"}' +
          'catch(error){outcome.parentDocument=error.name}' +
          'try{top.location="http://example.test/plugin-top-escape";outcome.topNavigation="allowed"}' +
          'catch(error){outcome.topNavigation=error.name}' +
          'fetch("http://127.0.0.1:9/plugin-network-escape")' +
          '.then(()=>{outcome.networkFetch="allowed";report(outcome)})' +
          '.catch(()=>{outcome.networkFetch="blocked";report(outcome)});</script>',
      ),
    );
    await page.waitForFunction(() => window.pluginEscapeEvents.length > 0);
    const outcome = await page.evaluate(() => window.pluginEscapeEvents[0]);

    assert.equal(outcome.parentDocument, 'SecurityError');
    assert.equal(outcome.topNavigation, 'SecurityError');
    assert.equal(outcome.networkFetch, 'blocked');
  } finally {
    await browser.close();
  }
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

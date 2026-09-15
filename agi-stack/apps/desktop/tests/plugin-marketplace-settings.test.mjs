import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const React = require('react');
const ts = require('typescript');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider, useI18n } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const { loadPluginMarketplaceSettings, pluginMarketplaceSettingsAvailable } = require(
  '/tmp/agistack-desktop-test-dist/src/features/settings/pluginMarketplaceSettingsModel.js',
);

test('local settings expose builtin slots without requesting the cloud marketplace', async () => {
  let calls = 0;
  assert.equal(pluginMarketplaceSettingsAvailable('local'), false);
  assert.deepEqual(await loadPluginMarketplaceSettings({ mode: 'local' }, {
    listMarketplacePlugins: async () => { calls += 1; throw new Error('no cloud authority'); },
  }), []);
  assert.equal(calls, 0);
});

test('cloud settings retain exact credentials, cancellation and retryable upstream failures', async () => {
  const config = { mode: 'cloud', tenantId: 'tenant-a' };
  const controller = new AbortController();
  const failure = new Error('marketplace unavailable');
  let calls = 0;
  const operations = { listMarketplacePlugins: async (received, signal) => {
    assert.equal(received, config);
    assert.equal(signal, controller.signal);
    calls += 1;
    if (calls === 1) throw failure;
    return [{ id: 'restored@1.0.0' }];
  } };
  assert.equal(pluginMarketplaceSettingsAvailable('cloud'), true);
  await assert.rejects(loadPluginMarketplaceSettings(config, operations, controller.signal), failure);
  assert.deepEqual(await loadPluginMarketplaceSettings(config, operations, controller.signal), [
    { id: 'restored@1.0.0' },
  ]);
});

test('every supported UI slot has a localized label in both languages', () => {
  const source = ts.createSourceFile('uiSlotRegistry.ts', readFileSync(
    new URL('../src/plugins/uiSlotRegistry.ts', import.meta.url), 'utf8',
  ), ts.ScriptTarget.Latest, true);
  const alias = source.statements.find((node) => ts.isTypeAliasDeclaration(node) && node.name.text === 'UiSlotKind');
  const slots = alias.type.types.map((node) => node.literal.text);
  const englishLabels = new Map();
  const oldWindow = globalThis.window;
  try {
    for (const locale of ['en', 'zh-CN']) {
      globalThis.window = { localStorage: { getItem: () => locale } };
      function Labels() {
        const { t } = useI18n();
        for (const slot of slots) {
          const key = `settings.platformPluginUi.slot.${slot}`;
          assert.notEqual(t(key), key, `${locale}: ${slot}`);
          if (locale === 'en') englishLabels.set(slot, t(key));
          else assert.notEqual(t(key), englishLabels.get(slot), `Chinese fallback: ${slot}`);
        }
        return null;
      }
      renderToStaticMarkup(React.createElement(I18nProvider, null, React.createElement(Labels)));
    }
  } finally {
    if (oldWindow === undefined) delete globalThis.window;
    else globalThis.window = oldWindow;
  }
});

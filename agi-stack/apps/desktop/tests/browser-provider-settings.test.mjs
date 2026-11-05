import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const module = { exports: {} };
const source = readFileSync(
  new URL('../src/features/settings/browserProviderSettingsModel.ts', import.meta.url),
  'utf8',
);
new Function(
  'exports',
  ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText,
)(module.exports);
const { browserProviderOptions, removeBrowserEndpoint } = module.exports;
const id = 'd5c2e852-c751-43d7-840a-cdc1e2d0fe08';
const config = {
  cdp_endpoints: [
    {
      id,
      name: 'Local test',
      endpoint: 'http://127.0.0.1:9222',
      enabled: true,
    },
  ],
  default_browser_id: `cdp:${id}`,
};
test('default browser persists as a stable ref when its provider is offline or disabled', () => {
  const offline = browserProviderOptions(config, []);
  assert.deepEqual(
    offline.find((row) => row.id === config.default_browser_id),
    { id: config.default_browser_id, name: 'Local test', online: false },
  );
  const live = {
    id: 'cdp:changing:connection',
    metadata: { stableId: `cdp:${id}`, name: 'Local test' },
  };
  assert.equal(
    browserProviderOptions(config, [live]).find((row) => row.id === config.default_browser_id)
      .online,
    true,
  );
  assert.equal(
    browserProviderOptions(config, [live]).some((row) => row.id === live.id),
    false,
  );
  const unknown = browserProviderOptions({ default_browser_id: 'chrome:offline-profile' }, []);
  assert.equal(unknown.find((row) => row.id === 'chrome:offline-profile').online, false);
});
test('deleting the selected CDP endpoint resets the default to IAB and preserves other settings', () => {
  const updated = removeBrowserEndpoint({ ...config, enabled: true, port: 9722 }, id);
  assert.deepEqual(updated, {
    ...config,
    enabled: true,
    port: 9722,
    cdp_endpoints: [],
    default_browser_id: 'iab',
  });
  assert.equal(config.cdp_endpoints.length, 1);
});

test('settings renders the stored offline default and disables writes while configuration is pending', () => {
  const React = require('react');
  const { renderToStaticMarkup } = require('react-dom/server');
  const component = { exports: {} };
  const source = readFileSync(
    new URL('../src/features/settings/BrowserProviderSettings.tsx', import.meta.url),
    'utf8',
  );
  new Function(
    'require',
    'exports',
    ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText,
  )((name) => {
    if (name === '../../i18n') return { useI18n: () => ({ t: (key) => key }) };
    if (name === './browserProviderSettingsModel') return module.exports;
    if (name === '@radix-ui/themes') return { Button: 'button' };
    return require(name);
  }, component.exports);
  const html = renderToStaticMarkup(
    React.createElement(component.exports.BrowserProviderSettings, {
      config,
      status: null,
      busy: true,
      error: null,
      save: async () => false,
    }),
  );
  assert.match(html, new RegExp(`value="cdp:${id}" selected=""`));
  assert.match(html, /Local test \(settings.browserProviderOffline\)/);
  assert.match(html, /<select[^>]*disabled=""/);
  assert.match(html, /settings.browserProviderEndpoint/);
});

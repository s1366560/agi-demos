import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const webRequire = createRequire(new URL('../../../../web/package.json', import.meta.url));
const { Window } = await import(pathToFileURL(webRequire.resolve('happy-dom')).href);
const window = new Window({ url: 'http://localhost/' });
for (const key of [
  'window',
  'document',
  'navigator',
  'HTMLElement',
  'HTMLInputElement',
  'Event',
  'Node',
  'Element',
])
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value: key === 'window' ? window : window[key],
  });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react');
const { act } = React;
const { createRoot } = require('react-dom/client');
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const compiled = await esbuild.build({
  stdin: {
    contents:
      "export {ProviderCatalogPicker} from './src/features/settings/ProviderCatalogPicker'; export {AddProviderDialog} from './src/features/settings/AddProviderDialog'; export {I18nProvider} from './src/i18n';",
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'ts',
  },
  write: false,
  bundle: true,
  platform: 'node',
  format: 'cjs',
  packages: 'external',
});
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(
  require,
  module,
  module.exports
);
const { ProviderCatalogPicker, AddProviderDialog, I18nProvider } = module.exports;

test('a large discovered catalog can select its last model and retains selections across searches', async () => {
  const models = Array.from({ length: 138 }, (_, index) => ({
    id: `opaque-model-${index}`,
    capability: 'chat',
  }));
  models[137] = { id: 'EXACT-audio[1]', capability: 'chat' };
  let selection = new Set([models[0].id]);
  const element = document.createElement('div');
  document.body.append(element);
  const root = createRoot(element);
  function Picker() {
    const [selected, setSelected] = React.useState(selection);
    return React.createElement(ProviderCatalogPicker, {
      models,
      selectedModels: selected,
      primaryModel: models[0].id,
      onToggle(id) {
        selection = new Set(selected);
        if (selection.has(id)) selection.delete(id);
        else selection.add(id);
        setSelected(selection);
      },
    });
  }
  const search = async (text) => {
    const input = element.querySelector('input[type="search"]');
    assert.ok(input?.getAttribute('aria-label'));
    await act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(
        input,
        text
      );
      input.dispatchEvent(new window.Event('input', { bubbles: true }));
    });
  };
  try {
    await act(async () =>
      root.render(React.createElement(I18nProvider, null, React.createElement(Picker)))
    );
    assert.equal(element.querySelectorAll('input[type="checkbox"]').length, 138);
    assert.equal(element.querySelector('input[type="checkbox"]').disabled, true);
    await search('  exact-audio[1]  ');
    const match = element.querySelectorAll('input[type="checkbox"]');
    assert.equal(match.length, 1);
    assert.match(match[0].parentElement.textContent, /EXACT-audio\[1\]/);
    await act(async () => match[0].click());
    assert.deepEqual([...selection], [models[0].id, models[137].id]);
    await search('absent model');
    assert.equal(element.querySelectorAll('input[type="checkbox"]').length, 0);
    assert.ok(element.querySelector('[role="status"]')?.textContent);
    assert.equal(selection.size, 2);
    await search('');
    assert.equal(element.querySelectorAll('input[type="checkbox"]:checked').length, 2);
    assert.equal(element.querySelectorAll('input[type="checkbox"]').length, 138);
  } finally {
    await act(async () => root.unmount());
    element.remove();
  }
});

test('cloud creation sends selected non-primary models as exact secondary model IDs', async () => {
  let created;
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const catalog = {
    providerType: 'volcengine',
    providerId: null,
    availability: 'available',
    source: 'provider-api',
    discoveredAt: null,
    detail: null,
    models: [
      { id: 'opaque-primary', capability: 'chat' },
      { id: 'opaque-secondary', capability: 'chat' },
    ],
  };
  const click = async (text) => {
    const button = [...document.querySelectorAll('button')].find(
      (item) => item.textContent.trim() === text
    );
    assert.ok(button, text);
    assert.equal(button.disabled, false, text);
    await act(async () => button.click());
  };
  try {
    await act(async () =>
      root.render(
        React.createElement(
          I18nProvider,
          null,
          React.createElement(AddProviderDialog, {
            onClose() {},
            async onLoadTypes() {
              return [
                {
                  providerType: 'volcengine',
                  source: 'cloud_api',
                  operationType: 'llm',
                  authMethods: ['api_key'],
                  unavailableAuthMethods: [],
                  probeSupported: false,
                },
              ];
            },
            async onValidateDraft() {
              return {
                provider: null,
                status: 'configuration_valid',
                probed: false,
                detail: null,
                catalog,
              };
            },
            async onCreate(input) {
              created = input;
              return {};
            },
          })
        )
      )
    );
    await click('Continue');
    await act(async () => {
      const keyInput = document.querySelector('input[type="password"]');
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(
        keyInput,
        'fixture-only'
      );
      keyInput.dispatchEvent(new window.Event('input', { bubbles: true }));
    });
    await click('Validate configuration');
    await click('Continue');
    const rows = document.querySelectorAll('input[type="checkbox"]');
    await act(async () => rows[0].click());
    await act(async () => rows[1].click());
    await click('Add provider');
    assert.equal(created.primaryModel, 'opaque-primary');
    assert.deepEqual(created.secondaryModels, ['opaque-secondary']);
    assert.deepEqual(created.allowedModels, ['opaque-primary', 'opaque-secondary']);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

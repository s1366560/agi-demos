import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const webRequire = createRequire(new URL('../../../../web/package.json', import.meta.url));
const { Window } = await import(pathToFileURL(webRequire.resolve('happy-dom')).href);
const window = new Window({ url: 'http://localhost/' });
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Event'])
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value: key === 'window' ? window : window[key],
  });
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react');
const { act } = React;
const { createRoot } = require('react-dom/client');
const {
  PluginInstancesV2,
} = require('/tmp/agistack-desktop-test-dist/src/features/settings/PluginInstancesV2.js');
const { I18nContext } = require('/tmp/agistack-desktop-test-dist/src/i18nContext.js');

test('invalid JSON blocks the entire batch instead of applying an older valid draft', async () => {
  const response = {
    revision: 'revision-1',
    scope: { tenant_id: 'tenant-1', project_id: 'project-1' },
    publication: { status: 'ready' },
    instances: [
      {
        entry_id: 'example',
        display_name: 'Example',
        enabled: true,
        editable: true,
        config_editable: true,
        config: { payload: { value: 1 } },
        config_schema: { properties: { payload: { type: 'object' } } },
        replacement_candidates: [],
        state: { status: 'enabled' },
      },
    ],
  };
  const applied = [];
  const client = {
    list: async () => response,
    apply: async (...args) => {
      applied.push(args);
      return { ...response, revision: 'revision-2' };
    },
  };
  const operations = { instanceClient: () => client };
  const config = {
    mode: 'local',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const edit = async (value) => {
    const textarea = host.querySelector('textarea');
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      'value',
    ).set;
    await act(async () => {
      setter.call(textarea, value);
      textarea.dispatchEvent(new window.Event('input', { bubbles: true }));
    });
  };
  try {
    await act(async () =>
      root.render(
        React.createElement(
          I18nContext.Provider,
          { value: { locale: 'en-US', t: (key) => key } },
          React.createElement(PluginInstancesV2, {
            config,
            operations,
            canManage: true,
          }),
        ),
      ),
    );
    const apply = () =>
      [...host.querySelectorAll('button')].find((button) => button.textContent === 'Apply changes');
    await edit('{"value":2}');
    assert.equal(apply().disabled, false);
    await edit('{');
    assert.equal(apply().disabled, true);
    assert.match(host.querySelector('[role="alert"]').textContent, /valid JSON/);
    await act(async () => apply().click());
    assert.equal(applied.length, 0);
    await edit('[]');
    assert.equal(apply().disabled, true);
    await edit('{"value":3}');
    await act(async () => apply().click());
    assert.equal(applied.length, 1);
    assert.deepEqual(applied[0].slice(0, 2), [
      'revision-1',
      [{ entry_id: 'example', config: { payload: { value: 3 } } }],
    ]);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

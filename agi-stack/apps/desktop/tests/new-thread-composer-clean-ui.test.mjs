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
  'HTMLTextAreaElement',
  'CustomEvent',
  'Event',
  'NodeFilter',
  'Element',
  'Node',
  'DOMParser',
  'MutationObserver',
  'ResizeObserver',
  'getComputedStyle',
  'requestAnimationFrame',
  'cancelAnimationFrame',
]) {
  const value = key === 'window' ? window : window[key];
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value:
      typeof value === 'function' &&
      ['getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame'].includes(key)
        ? value.bind(window)
        : value,
  });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react'),
  { act } = React,
  { createRoot } = require('react-dom/client');
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const compiled = await esbuild.build({
  stdin: {
    contents:
      "export {NewThreadComposer} from './src/features/task/NewThreadComposer'; export {I18nProvider} from './src/i18n';",
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'ts',
  },
  write: false,
  bundle: true,
  platform: 'node',
  format: 'cjs',
  packages: 'external',
  loader: { '.css': 'empty' },
  define: { 'import.meta.env.DEV': 'false', 'import.meta.env.PROD': 'true' },
});
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(
  require,
  module,
  module.exports,
);
const { NewThreadComposer, I18nProvider } = module.exports;
const { Theme } = require('@radix-ui/themes');

function props(overrides = {}) {
  return {
    workspaceId: 'workspace',
    workspace: { id: 'workspace', name: 'Desktop Client' },
    workspaces: [{ id: 'workspace', name: 'Desktop Client' }],
    api: {},
    conversations: [],
    mode: 'work',
    policy: { reasoning_effort: 'medium', permission_mode: 'automatic' },
    modelOptions: [{ value: 'local/model', modelId: 'Test model', roles: [], selected: true }],
    canManagePolicy: true,
    loadingPolicy: false,
    compatibilityMode: false,
    disabledReason: null,
    creating: false,
    error: null,
    onModeChange() {},
    onWorkspaceChange() {},
    onCreate() {},
    onOpenThread() {},
    onManageModels() {},
    ...overrides,
  };
}

async function mount(input) {
  const element = document.createElement('div');
  document.body.append(element);
  const root = createRoot(element);
  await act(async () =>
    root.render(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(Theme, null, React.createElement(NewThreadComposer, input)),
      ),
    ),
  );
  return {
    element,
    async close() {
      await act(async () => root.unmount());
      element.remove();
    },
  };
}

async function openOptions(element) {
  const trigger = element.querySelector('.composer-options-button');
  await act(async () => {
    trigger.focus();
    trigger.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  });
  return trigger;
}

test('clean composer keeps explicit permissions, places reasoning in options, and sends the selected effort', async () => {
  let submitted;
  const view = await mount(
    props({
      onCreate(value) {
        submitted = value;
      },
    }),
  );
  try {
    assert.equal(view.element.querySelectorAll('h1').length, 1);
    assert.equal(view.element.querySelector('.new-thread-suggestions'), null);
    assert.equal(view.element.querySelector('.new-thread-recent'), null);
    assert.match(view.element.textContent, /Automatic/);
    assert.equal(document.querySelector('[role="menuitemradio"]'), null);
    const trigger = await openOptions(view.element);
    const high = [...document.querySelectorAll('[role="menuitemradio"]')].find(
      (node) => node.textContent === 'High',
    );
    assert.ok(high);
    await act(async () => high.click());
    assert.equal(document.querySelector('[role="menuitemradio"]'), null);
    await act(async () => new Promise((resolve) => setTimeout(resolve, 10)));
    assert.ok(document.activeElement === trigger, 'selection restores focus to options');
    const textarea = view.element.querySelector('textarea');
    await act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(
        textarea,
        'Summarize the release',
      );
      textarea.dispatchEvent(new window.Event('input', { bubbles: true }));
    });
    await act(async () => view.element.querySelector('.send-button').click());
    assert.equal(submitted.reasoningEffort, 'high');
    assert.equal(submitted.permissionMode, 'automatic');
    assert.equal(submitted.prompt, 'Summarize the release');
  } finally {
    await view.close();
  }
});

test('read-only policy keeps full access visible and prevents changing effort', async () => {
  const view = await mount(
    props({
      canManagePolicy: false,
      policy: { reasoning_effort: 'medium', permission_mode: 'full_access' },
    }),
  );
  try {
    assert.match(view.element.textContent, /Full access/);
    await openOptions(view.element);
    const choices = [...document.querySelectorAll('[role="menuitemradio"]')];
    assert.equal(choices.length, 3);
    assert.ok(choices.every((choice) => choice.getAttribute('aria-disabled') === 'true'));
  } finally {
    await view.close();
  }
});

test('blocking errors remain visible and prevent sending', async () => {
  const view = await mount(props({ disabledReason: 'Runtime disconnected' }));
  try {
    assert.equal(view.element.querySelector('[role="alert"]').textContent, 'Runtime disconnected');
    assert.equal(view.element.querySelector('.send-button').disabled, true);
  } finally {
    await view.close();
  }
});

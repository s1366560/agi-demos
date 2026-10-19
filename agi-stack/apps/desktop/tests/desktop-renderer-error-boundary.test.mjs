import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const webRequire = createRequire(new URL('../../../../web/package.json', import.meta.url));
const { Window } = webRequire('happy-dom');
const ts = require('typescript');
const notification = 'ResizeObserver loop completed with undelivered notifications.';
const source = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
const code = ts.transpileModule(source.replaceAll('import.meta', 'importMeta'), {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.CommonJS,
    jsx: ts.JsxEmit.ReactJSX,
    esModuleInterop: true,
  },
}).outputText;

function mountEntry() {
  const window = new Window({ url: 'http://localhost/' });
  window.document.body.innerHTML = '<div id="root"></div>';
  const root = window.document.getElementById('root');
  const module = { exports: {} };
  new Function('require', 'module', 'exports', 'window', 'document', 'importMeta', code)(
    (id) => {
      if (id.endsWith('.css')) return {};
      if (id === 'react-dom/client') {
        return {
          createRoot: () => ({
            render: () => {
              root.textContent = 'Application mounted';
            },
          }),
        };
      }
      if (id === './App') return { App: () => null };
      if (id === './features/feedback/ToastCenter') return { ToastProvider: () => null };
      if (id === './i18n') return { I18nProvider: () => null };
      if (id === './theme') return { ThemePreferenceProvider: () => null };
      if (id === './plugins/useDesktopPluginGenerationV2') {
        return { activateDesktopPluginGenerationRootV2() {} };
      }
      return require(id);
    },
    module,
    module.exports,
    window,
    window.document,
    { env: { DEV: false } }
  );
  return { window, root };
}

test('a browser resize-loop notification preserves the mounted application', () => {
  const { window, root } = mountEntry();
  const event = new window.ErrorEvent('error', { message: notification, cancelable: true });
  window.dispatchEvent(event);
  assert.equal(root.textContent, 'Application mounted');
  assert.equal(event.defaultPrevented, false, 'browser diagnostics remain observable');
});

test('a real exception with the same resize-loop message remains fatal', () => {
  const { window, root } = mountEntry();
  window.dispatchEvent(
    new window.ErrorEvent('error', {
      message: notification,
      error: new Error(notification),
    })
  );
  assert.ok(root.querySelector('.app-fatal-error'));
  assert.match(root.querySelector('pre').textContent, /^Error: ResizeObserver/);
});

test('other error notifications and unhandled rejections remain fatal', () => {
  for (const message of ['Script error.', `${notification} unexpected details`]) {
    const { window, root } = mountEntry();
    window.dispatchEvent(new window.ErrorEvent('error', { message }));
    assert.ok(root.querySelector('.app-fatal-error'));
    assert.equal(root.querySelector('pre').textContent, message);
  }
  const { window, root } = mountEntry();
  const event = new window.Event('unhandledrejection');
  event.reason = new Error('unhandled terminal failure');
  window.dispatchEvent(event);
  assert.ok(root.querySelector('.app-fatal-error'));
  assert.match(root.querySelector('pre').textContent, /unhandled terminal failure/);
});

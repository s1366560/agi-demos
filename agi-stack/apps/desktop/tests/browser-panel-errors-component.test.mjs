import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
const require = createRequire(import.meta.url);
const webRequire = createRequire(
  new URL("../../../../web/package.json", import.meta.url),
);
const { Window } = await import(
  pathToFileURL(webRequire.resolve("happy-dom")).href
);
const window = new Window({ url: "http://localhost/" });
for (const key of [
  "window",
  "document",
  "navigator",
  "HTMLElement",
  "Element",
  "Node",
  "DOMParser",
  "MutationObserver",
  "ResizeObserver",
  "getComputedStyle",
  "requestAnimationFrame",
  "cancelAnimationFrame",
]) {
  const value = key === "window" ? window : window[key];
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value:
      typeof value === "function" &&
      [
        "getComputedStyle",
        "requestAnimationFrame",
        "cancelAnimationFrame",
      ].includes(key)
        ? value.bind(window)
        : value,
  });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require("react"),
  { act } = React,
  { createRoot } = require("react-dom/client");
const esbuild = createRequire(require.resolve("vite"))("esbuild");
const compiled = await esbuild.build({
  stdin: {
    contents: "export {BrowserPanel} from './src/features/browser/BrowserPanel';",
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'ts',
  },
  write: false, bundle: true, platform: 'node', format: 'cjs', packages: 'external',
  loader: { '.css': 'empty' },
  plugins: [{ name: 'i18n-test', setup(build) {
    build.onResolve({ filter: /i18n$/ }, () => ({ path: 'i18n', namespace: 'mock' }));
    build.onLoad({ filter: /.*/, namespace: 'mock' }, () => ({ contents: 'exports.useI18n = () => ({ t: key => key });' }));
  } }],
});
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(require, module, module.exports);
const { BrowserPanel } = module.exports;

for (const operation of ['listTabs', 'showPane', 'focusTab', 'createTab', 'closeTab']) {
  test(`browser reports ${operation} failure and retries the failed operation`, async () => {
    let failing = true;
    let calls = 0;
    const tab = { tabId: 1, windowId: 1, title: 'Example', url: 'https://example.com', active: true };
    const bridge = {
      listTabs: async () => ({ tabs: [tab] }),
      onTabsChanged: () => () => {},
      showPane: async () => {}, setBounds: async () => {}, hidePane: async () => {},
      focusTab: async () => {}, createTab: async () => {}, closeTab: async () => {},
    };
    const original = bridge[operation];
    bridge[operation] = async (...args) => {
      calls += 1;
      if (failing) throw new Error('private internal error');
      return original(...args);
    };
    window.__MEMSTACK_DESKTOP__ = { iab: bridge };
    const container = document.createElement('div');
    document.body.append(container);
    const root = createRoot(container);
    try {
      await act(async () => root.render(React.createElement(BrowserPanel)));
      const selectors = {
        focusTab: '[role="tab"]',
        createTab: '.browser-panel-new-tab',
        closeTab: '.browser-panel-tab-close',
      };
      if (selectors[operation]) {
        await act(async () => container.querySelector(selectors[operation]).click());
      }
      assert.ok(container.querySelector('[role="alert"]'));
      assert.equal(container.textContent.includes('private internal error'), false);
      assert.equal(container.querySelector('.browser-panel-empty'), null);
      failing = false;
      await act(async () => container.querySelector('[role="alert"] button').click());
      assert.equal(calls, 2);
      assert.equal(container.querySelector('[role="alert"]'), null);
      assert.ok(container.querySelector('[role="tab"]'));
    } finally {
      await act(async () => root.unmount());
      container.remove();
    }
  });
}

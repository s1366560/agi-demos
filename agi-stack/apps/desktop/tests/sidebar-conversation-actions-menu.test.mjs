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
  "HTMLInputElement",
  "HTMLTextAreaElement",
  "CustomEvent",
  "Event",
  "NodeFilter",
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
    contents:
      "export {ConversationActionsMenu} from './src/features/workspace/ConversationActionsMenu'; export {I18nProvider} from './src/i18n';",
    resolveDir: new URL("..", import.meta.url).pathname,
    loader: "ts",
  },
  write: false,
  bundle: true,
  platform: "node",
  format: "cjs",
  packages: "external",
  loader: { ".css": "empty" },
  define: { "import.meta.env.DEV": "false", "import.meta.env.PROD": "true" },
});
const module = { exports: {} };
new Function("require", "module", "exports", compiled.outputFiles[0].text)(
  require,
  module,
  module.exports,
);
const { ConversationActionsMenu, I18nProvider } = module.exports;
const { Theme } = require("@radix-ui/themes");

async function mountMenu() {
  const element = document.createElement("div");
  element.style.overflow = "hidden";
  document.body.append(element);
  const root = createRoot(element);
  let renamed = 0;
  let deleted = 0;
  await act(async () =>
    root.render(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(
          Theme,
          null,
          React.createElement(ConversationActionsMenu, {
            title: "Regression",
            actionRef() {},
            onRename() {
              renamed += 1;
            },
            onDelete() {
              deleted += 1;
            },
          }),
        ),
      ),
    ),
  );
  return {
    element,
    counts: () => ({ renamed, deleted }),
    async close() {
      await act(async () => root.unmount());
      element.remove();
    },
  };
}

async function key(target, value) {
  await act(async () => {
    target.dispatchEvent(
      new window.KeyboardEvent("keydown", { key: value, bubbles: true }),
    );
    await new Promise((resolve) => setTimeout(resolve, 30));
  });
}

test("sidebar menu escapes the clipped list and supports keyboard navigation and Escape focus", async () => {
  const view = await mountMenu();
  try {
    const trigger = view.element.querySelector("button");
    trigger.focus();
    await key(trigger, "ArrowDown");
    const menu = document.querySelector('[role="menu"]');
    assert.ok(menu);
    assert.equal(view.element.contains(menu), false);
    const items = [...menu.querySelectorAll('[role="menuitem"]')];
    assert.ok(document.activeElement === items[0], "first menu item has focus");
    await key(items[0], "End");
    assert.ok(document.activeElement === items[1], "last menu item has focus");
    await key(items[1], "Home");
    assert.ok(document.activeElement === items[0], "first menu item has focus");
    await key(items[0], "Escape");
    await act(async () => new Promise((resolve) => setTimeout(resolve, 30)));
    assert.equal(document.querySelector('[role="menu"]'), null);
    assert.ok(
      document.activeElement === trigger,
      "Escape restores the trigger focus",
    );
    assert.deepEqual(view.counts(), { renamed: 0, deleted: 0 });
  } finally {
    await view.close();
  }
});

test("sidebar rename selects only the requested lifecycle action and closes its menu", async () => {
  const view = await mountMenu();
  try {
    const trigger = view.element.querySelector("button");
    await key(trigger, "Enter");
    const rename = document.querySelector('[role="menuitem"]');
    await act(async () => rename.click());
    assert.deepEqual(view.counts(), { renamed: 1, deleted: 0 });
    assert.equal(document.querySelector('[role="menu"]'), null);
  } finally {
    await view.close();
  }
});

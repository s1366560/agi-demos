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
    contents: "export {TimelineInspectionProvider,useTimelineInspection} from './src/features/session/TimelineInspectionContext';",
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'ts',
  },
  write: false, bundle: true, platform: 'node', format: 'cjs', packages: 'external',
});
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(require, module, module.exports);
const { TimelineInspectionProvider, useTimelineInspection } = module.exports;

test('inspection survives hiding and session switches; dismiss only clears current session', async () => {
  let inspection;
  const Capture = () => { inspection = useTimelineInspection(); return null; };
  const container = document.createElement('div');
  document.body.append(container);
  const trigger = document.createElement('button');
  document.body.append(trigger);
  const root = createRoot(container);
  let opens = 0;
  const render = (sessionKey, isOpen) => act(async () => root.render(
    React.createElement(TimelineInspectionProvider, { sessionKey, isOpen, onOpen: () => { opens += 1; } }, React.createElement(Capture))
  ));
  try {
    await render('a', false);
    await act(async () => inspection.inspect([{ id: 'a-tool' }], trigger));
    await render('a', true);
    await render('a', false);
    assert.equal(inspection.items[0].id, 'a-tool');
    await render('b', false);
    assert.deepEqual(inspection.items, []);
    await act(async () => inspection.inspect([{ id: 'b-tool' }], trigger));
    await render('a', true);
    assert.equal(inspection.items[0].id, 'a-tool');
    await act(async () => inspection.dismiss());
    assert.deepEqual(inspection.items, []);
    await render('b', true);
    assert.equal(inspection.items[0].id, 'b-tool');
    assert.equal(opens, 2);
  } finally {
    await act(async () => root.unmount());
    container.remove();
    trigger.remove();
  }
});

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
    contents:
      "export {SubAgentControlPanel} from './src/features/chat/SubAgentControlPanel'; export {I18nProvider} from './src/i18n';",
    resolveDir: new URL("..", import.meta.url).pathname,
    loader: "ts",
  },
  write: false,
  bundle: true,
  platform: "node",
  format: "cjs",
  packages: "external",
  loader: { ".css": "empty", ".svg": "text" },
  define: { "import.meta.env.DEV": "false", "import.meta.env.PROD": "true" },
});
const module = { exports: {} };
new Function("require", "module", "exports", compiled.outputFiles[0].text)(
  require,
  module,
  module.exports,
);
const { SubAgentControlPanel, I18nProvider } = module.exports;

test('lost response keeps the exact command and locks editing across advanced Cloud snapshots', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  const commands = [];
  let revision = 0;
  const onControl = async (command) => {
    commands.push(command);
    return { accepted: commands.length > 1, reasonCode: commands.length === 1 ? 'cloud_child_control_http_503' : null };
  };
  const render = () => act(async () => root.render(React.createElement(I18nProvider, null,
    React.createElement(SubAgentControlPanel, {
      group: { runId: 'child', subagentId: '', status: 'running' },
      authority: { availability: 'available', conversationId: 'conversation', authorityRevision: null, participantAgentIds: [], allowedActions: [],
        cloudControls: [{ runId: 'child', controlRevision: revision, status: 'running', allowedActions: ['steer', 'kill_run'] }] }, onControl,
    }))));
  try {
    await render();
    const textarea = container.querySelector('textarea');
    await act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set.call(textarea, 'original instruction');
      textarea.dispatchEvent(new window.Event('input', { bubbles: true }));
    });
    assert.equal(container.querySelector('.subagent-steer-control button').disabled, false);
    await act(async () => container.querySelector('.subagent-steer-control button').click());
    assert.equal(commands.length, 1);
    assert.equal(container.querySelector('textarea').disabled, true);
    revision = 1;
    await render();
    await act(async () => container.querySelector('.subagent-steer-control button').click());
    assert.equal(commands.length, 2);
    assert.deepEqual(commands[1], commands[0]);
    assert.equal(commands[1].expectedControlRevision, 0);
    assert.equal(commands[1].expectedRunRevision, null);
    assert.equal(container.querySelector('textarea').disabled, false);
  } finally { await act(async () => root.unmount()); container.remove(); }
});

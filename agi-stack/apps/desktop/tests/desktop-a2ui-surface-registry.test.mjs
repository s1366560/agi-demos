import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
const require = createRequire(import.meta.url);

const surfaceSource = readFileSync(
  new URL("../src/features/chat/DesktopA2UISurface.tsx", import.meta.url),
  "utf8",
);
const registrySource = readFileSync(
  new URL("../src/features/chat/a2uiDesktopRegistry.tsx", import.meta.url),
  "utf8",
);

test("registry registration happens once at module scope, never during render", () => {
  const callCount = surfaceSource.split("ensureDesktopA2UIRegistry();").length - 1;
  assert.equal(callCount, 1, "exactly one registration call site remains");
  const callIndex = surfaceSource.indexOf("ensureDesktopA2UIRegistry();");
  const componentIndex = surfaceSource.indexOf(
    "export function DesktopA2UISurface(",
  );
  assert.ok(callIndex !== -1 && componentIndex !== -1);
  assert.ok(
    callIndex < componentIndex,
    "the registration call is module-scope, above the component body",
  );
});

test("no wire-to-renderer kind remapping remains in the surface", () => {
  assert.doesNotMatch(surfaceSource, /toRendererComponent/u);
  assert.doesNotMatch(surfaceSource, /MultipleChoice/u);
  assert.match(registrySource, /\['Checkbox', 'CheckBox'\]/u);
  assert.match(registrySource, /\['Select', 'MultipleChoice'\]/u);
  assert.match(registrySource, /initializeDefaultCatalog\(\)/u);
});

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
      "export {DesktopA2UISurface} from './src/features/chat/DesktopA2UISurface'; export {I18nProvider} from './src/i18n'; export {ComponentRegistry} from './src/vendor/a2uiRendererInternals.mjs';",
    resolveDir: new URL("..", import.meta.url).pathname,
    loader: "ts",
  },
  write: false,
  bundle: true,
  platform: "node",
  format: "cjs",
  // Keep React external, but bundle @copilotkit/a2ui-renderer so the vendored
  // internals shim and the viewer share one ComponentRegistry module instance.
  external: ["react", "react-dom", "react-dom/client", "react/jsx-runtime"],
  loader: { ".css": "empty", ".svg": "text" },
  define: { "import.meta.env.DEV": "false", "import.meta.env.PROD": "true" },
});
const module = { exports: {} };
new Function("require", "module", "exports", compiled.outputFiles[0].text)(
  require,
  module,
  module.exports,
);
const { DesktopA2UISurface, I18nProvider, ComponentRegistry } = module.exports;
const flush = async () => {
  for (let index = 0; index < 5; index += 1) {
    await act(async () => {
      await new Promise(setImmediate);
    });
  }
};

function line(value) {
  return JSON.stringify(value);
}

function surfaceMessages(components) {
  return [
    line({ beginRendering: { surfaceId: "surface-1", root: "root" } }),
    line({
      surfaceUpdate: {
        surfaceId: "surface-1",
        components: [
          {
            id: "root",
            component: { Column: { children: { explicitList: components.map((c) => c.id) } } },
          },
          ...components,
        ],
      },
    }),
  ].join("\n");
}

function surfaceProps(messages) {
  return {
    messages,
    requestId: "request-1",
    authorityRevision: 3,
    idempotencyKey: "request-1:3:a2ui_action",
    allowedActions: [{ source_component_id: "root", action_name: "submit" }],
    onCommand: () => {},
  };
}

async function renderSurface(props) {
  const element = document.createElement("div");
  document.body.append(element);
  const root = createRoot(element);
  await act(async () =>
    root.render(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(DesktopA2UISurface, props),
      ),
    ),
  );
  await flush();
  return {
    element,
    unmount: async () => {
      await act(async () => root.unmount());
      element.remove();
    },
  };
}

test("registry aliases desktop kinds onto the vendored components", () => {
  const registry = ComponentRegistry.getInstance();
  for (const kind of ["Badge", "Radio", "Table", "Progress"]) {
    assert.ok(registry.get(kind), `${kind} is registered`);
  }
  assert.equal(
    registry.get("Checkbox"),
    registry.get("CheckBox"),
    "Checkbox aliases the vendored CheckBox",
  );
  assert.equal(
    registry.get("Select"),
    registry.get("MultipleChoice"),
    "Select aliases the vendored MultipleChoice",
  );
});

test("wire kinds Checkbox and Select render without any remapping", async () => {
  const { element, unmount } = await renderSurface(
    surfaceProps(
      surfaceMessages([
        {
          id: "check-1",
          component: { Checkbox: { label: { literalString: "Accept terms" } } },
        },
        {
          id: "select-1",
          component: {
            Select: {
              description: { literalString: "Pick one" },
              options: [
                { label: { literalString: "First" }, value: "first" },
                { label: { literalString: "Second" }, value: "second" },
              ],
            },
          },
        },
      ]),
    ),
  );
  try {
    const checkbox = element.querySelector('.a2ui-checkbox input[type="checkbox"]');
    assert.ok(checkbox, "Checkbox wire kind renders the vendored checkbox input");
    const select = element.querySelector(".a2ui-multiplechoice select");
    assert.ok(select, "Select wire kind renders the vendored select element");
    assert.deepEqual(
      [...select.querySelectorAll("option")].map((option) => option.value),
      ["first", "second"],
    );
  } finally {
    await unmount();
  }
});

test("unsupported component kinds still fail closed", async () => {
  const { element, unmount } = await renderSurface(
    surfaceProps(
      surfaceMessages([
        { id: "evil-1", component: { Script: { src: "https://evil.example" } } },
      ]),
    ),
  );
  try {
    const state = element.querySelector(".desktop-a2ui-surface-state");
    assert.ok(state, "the surface refuses to render");
    assert.match(state.textContent, /a2ui_component_unsupported/u);
    assert.equal(element.querySelector("script"), null);
  } finally {
    await unmount();
  }
});

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { test } from "node:test";
const require = createRequire(import.meta.url);

const appSource = readFileSync(
  new URL("../src/App.tsx", import.meta.url),
  "utf8",
);
const overviewSource = readFileSync(
  new URL("../src/features/workspace/WorkspaceOverview.tsx", import.meta.url),
  "utf8",
);

test("App wires resolve through an explicit documented alias of the retry gate", () => {
  // The autonomy-attention capability contract exposes no distinct resolve
  // capability; the alias must stay named and documented so a future role
  // divergence cannot silently mis-gate resolution.
  assert.match(
    appSource,
    /const canResolveWorkspaceAutonomyAttention = canRetryWorkspaceAutonomyAttention;/u,
  );
  const aliasIndex = appSource.indexOf(
    "const canResolveWorkspaceAutonomyAttention = canRetryWorkspaceAutonomyAttention;",
  );
  const commentBefore = appSource.slice(Math.max(0, aliasIndex - 700), aliasIndex);
  assert.match(commentBefore, /no[\s\S]*?distinct\s+resolve\s+capability/iu);
  assert.match(commentBefore, /backend\s+re-checks\s+authorization/iu);
  assert.match(
    appSource,
    /canRetryAutonomyAttention: canRetryWorkspaceAutonomyAttention,/u,
  );
  assert.match(
    appSource,
    /canResolveAutonomyAttention: canResolveWorkspaceAutonomyAttention,/u,
  );
  assert.doesNotMatch(
    appSource,
    /canResolveAutonomyAttention: canRetryWorkspaceAutonomyAttention,/u,
  );
});

test("WorkspaceOverview keeps retry and resolve gates as distinct props", () => {
  assert.match(overviewSource, /canRetryAutonomyAttention\?: boolean;/u);
  assert.match(overviewSource, /canResolveAutonomyAttention\?: boolean;/u);
  assert.match(overviewSource, /canRetry=\{canRetryAutonomyAttention\}/u);
  assert.match(overviewSource, /canResolve=\{canResolveAutonomyAttention\}/u);
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
      "export {WorkspaceAutonomyAttentionCard} from './src/features/workspace/WorkspaceAutonomyAttentionCard'; export {I18nProvider} from './src/i18n';",
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
  (name) => {
    const value = require(name);
    // Node 22 loads ESM namespaces through require; preserve their default export for esbuild.
    return value?.[Symbol.toStringTag] === "Module"
      ? { ...value, __esModule: true }
      : value;
  },
  module,
  module.exports,
);
const { WorkspaceAutonomyAttentionCard, I18nProvider } = module.exports;

function attention(sourceKind) {
  return {
    attention_id: `attention-${sourceKind}`,
    root_task_id: "task-1",
    source_kind: sourceKind,
    source_id: "source-1",
    reason: "Judge blocked the run",
    status: "open",
    created_at_ms: 1784000000000,
  };
}

function cardProps(overrides) {
  return {
    authority: {
      status: "ready",
      items: [attention("judge_block"), attention("progression_dead_letter")],
      error: null,
    },
    canRetry: false,
    canResolve: false,
    retryingAttentionId: null,
    resolvingAttentionId: null,
    onRetry: () => {},
    onResolve: () => {},
    onRefresh: () => {},
    ...overrides,
  };
}

async function renderCard(props) {
  const element = document.createElement("div");
  document.body.append(element);
  const root = createRoot(element);
  await act(async () =>
    root.render(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(WorkspaceAutonomyAttentionCard, props),
      ),
    ),
  );
  return {
    labels: () =>
      [...element.querySelectorAll("button")].map((button) =>
        button.textContent.trim(),
      ),
    unmount: async () => {
      await act(async () => root.unmount());
      element.remove();
    },
  };
}

test("attention card gates retry and resolve independently", async () => {
  const neither = await renderCard(cardProps({}));
  assert.deepEqual(neither.labels(), []);
  await neither.unmount();

  const retryOnly = await renderCard(cardProps({ canRetry: true }));
  assert.equal(retryOnly.labels().length, 1);
  assert.match(retryOnly.labels()[0], /retry/iu);
  await retryOnly.unmount();

  const resolveOnly = await renderCard(cardProps({ canResolve: true }));
  assert.equal(resolveOnly.labels().length, 1);
  assert.match(resolveOnly.labels()[0], /mark handled/iu);
  await resolveOnly.unmount();

  const both = await renderCard(cardProps({ canRetry: true, canResolve: true }));
  assert.equal(both.labels().length, 2);
  await both.unmount();
});

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
      "export {NewTaskFlow} from './src/features/task/NewTaskFlow'; export {I18nProvider} from './src/i18n'; export {DesktopApiError} from './src/api/client';",
    resolveDir: new URL("..", import.meta.url).pathname,
    loader: "ts",
  },
  plugins: [
    {
      name: "observe-child-props",
      setup(build) {
        build.onLoad({ filter: /NewTaskFlowStages\.tsx$/ }, () => ({
          loader: "js",
          contents: `
      import React from 'react';
      export function NewTaskDefinitionStage(props) { globalThis.__taskDefinition = props; return React.createElement('div'); }
      export function NewTaskReviewStage(props) { globalThis.__taskReview = props; return React.createElement('div'); }
      export function NewTaskPlanningStage() { return React.createElement('div'); }
    `,
        }));
      },
    },
  ],
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
    if (
      ["react-markdown", "remark-gfm", "remark-math", "rehype-katex"].includes(
        name,
      )
    )
      return value.default;
    // Node 22 loads ESM namespaces through require; preserve their default export for esbuild.
    return value?.[Symbol.toStringTag] === "Module"
      ? { ...value, __esModule: true }
      : value;
  },
  module,
  module.exports,
);
const { NewTaskFlow, I18nProvider, DesktopApiError } = module.exports;
const flush = async () => {
  for (let index = 0; index < 5; index += 1) {
    await act(async () => {
      await new Promise(setImmediate);
    });
  }
};

const config = {
  mode: "local",
  apiBaseUrl: "http://localhost",
  tenantId: "tenant",
  projectId: "project",
  workspaceRoot: "/workspace",
  workspaceId: "",
};

function flowProps(api) {
  return {
    open: true,
    actorId: "owner",
    config,
    newTaskFlowClientV2: { bindOperation: () => api },
    workspaces: [],
    resumeDraft: null,
    onClose: () => {},
    onSessionPersisted: () => {},
    onSessionReady: () => {},
    onRunAgentTurn: async () => "acknowledged",
    onOpenRuntimeSettings: () => {},
    onError: () => {},
  };
}

const conflictApi = {
  listAgentPlanTasks: async () => ({ tasks: [], approval: null }),
  getConversationMessages: async () => ({ timeline: [] }),
  listWorkspaces: async () => [],
  createTaskSession: async () => {
    throw new DesktopApiError("conflict", 409, {
      code: "TASK_SESSION_IDEMPOTENCY_CONFLICT",
    });
  },
};

test("unresolved session-creation conflict suppresses primary actions and shows an edit hint", async () => {
  const element = document.createElement("div");
  document.body.append(element);
  const root = createRoot(element);
  try {
    await act(async () =>
      root.render(
        React.createElement(
          I18nProvider,
          null,
          React.createElement(NewTaskFlow, flowProps(conflictApi)),
        ),
      ),
    );
    await flush();
    await act(async () =>
      globalThis.__taskDefinition.onTitleChange("Conflicting task"),
    );
    await act(async () =>
      globalThis.__taskDefinition.onObjectiveChange("Investigate the conflict"),
    );

    const generate = document.querySelector(
      ".new-task-review-footer-actions button.primary",
    );
    assert.ok(generate, "generate-plan action is available before the conflict");
    assert.equal(generate.disabled, false);
    await act(async () => generate.click());
    await flush();

    // Dead-end: the conflict matches the unchanged definition and the earlier
    // workspace could not be recovered, so no primary action remains.
    assert.equal(
      document.querySelectorAll(".new-task-review-footer-actions button.primary")
        .length,
      0,
      "all primary actions are suppressed while the conflict is unresolved",
    );
    assert.ok(
      document.querySelector(".new-task-error"),
      "the conflict error banner is shown",
    );
    const hint = document.querySelector(".new-task-conflict-hint");
    assert.ok(hint, "an inline hint replaces the suppressed primary action");
    assert.match(hint.textContent, /[Ee]dit any field/);

    // Editing any definition field changes the fingerprint and restores the
    // normal generate-plan action.
    await act(async () =>
      globalThis.__taskDefinition.onObjectiveChange(
        "Investigate the conflict, revised",
      ),
    );
    assert.equal(document.querySelector(".new-task-conflict-hint"), null);
    const restored = document.querySelector(
      ".new-task-review-footer-actions button.primary",
    );
    assert.ok(restored, "editing a field restores the primary action");
    assert.equal(restored.disabled, false);
  } finally {
    await act(async () => root.unmount());
    element.remove();
  }
});

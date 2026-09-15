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
      "export {NewTaskFlow} from './src/features/task/NewTaskFlow'; export {I18nProvider} from './src/i18n';",
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
const { NewTaskFlow, I18nProvider } = module.exports;
const flush = async () => {
  await act(async () => {
    await new Promise(setImmediate);
  });
};
const task = {
  id: "task",
  conversation_id: "conversation",
  content: "Read source",
  status: "pending",
  priority: "medium",
  order_index: 0,
};
const plan = {
  id: "plan",
  conversation_id: "conversation",
  version: 1,
  status: "draft",
  tasks: [task],
};
const api = {
  listAgentPlanTasks: async () => ({
    tasks: [task],
    approval: { kind: "versioned_atomic", plan_version: plan },
  }),
  getConversationMessages: async () => ({ timeline: [] }),
};
const base = {
  open: true,
  actorId: "owner",
  newTaskFlowClientV2: { bindOperation: () => api },
  workspaces: [],
  onClose: () => {},
  onSessionPersisted: () => {},
  onSessionReady: () => {},
  onRunAgentTurn: async () => "acknowledged",
  onOpenRuntimeSettings: () => {},
  onError: () => {},
};
function props(mode, kind = "programming", resume = true) {
  const config = {
    mode,
    apiBaseUrl: "http://localhost",
    tenantId: "tenant",
    projectId: "project",
    workspaceRoot: "/workspace",
    workspaceId: "workspace",
  };
  return {
    ...base,
    config,
    preferredKind: kind,
    resumeDraft: resume
      ? {
          definition: {
            title: "QA",
            objective: "Inspect workspace",
            kind,
            workspaceRoot: "/workspace",
            contextSources: [],
          },
          session: {
            config,
            workspace: { id: "workspace", name: "Workspace" },
            conversation: {
              id: "conversation",
              user_id: "owner",
              current_mode: "plan",
            },
          },
          tasks: [task],
        }
      : null,
  };
}
test("NewTaskFlow restores, reopens and changes mode without inventing a Cloud worktree", async () => {
  const element = document.createElement("div");
  document.body.append(element);
  const root = createRoot(element);
  const render = async (p) => {
    await act(async () =>
      root.render(
        React.createElement(
          I18nProvider,
          null,
          React.createElement(NewTaskFlow, p),
        ),
      ),
    );
    await flush();
  };
  try {
    await render(props("cloud"));
    assert.equal(globalThis.__taskReview.environmentKind, "local");
    assert.equal(globalThis.__taskReview.permissionProfile, "workspace_write");
    await render({ ...props("cloud"), open: false });
    await render(props("local"));
    assert.equal(globalThis.__taskReview.environmentKind, "worktree");
    await render(props("cloud"));
    assert.equal(globalThis.__taskReview.environmentKind, "local");
    await render({ ...props("cloud"), open: false });
    await render(props("cloud", "general", false));
    await act(async () =>
      globalThis.__taskDefinition.onKindChange("programming"),
    );
    assert.equal(globalThis.__taskDefinition.kind, "programming");
    await render({ ...props("cloud"), open: false });
    await render(props("cloud", "programming"));
    assert.equal(globalThis.__taskReview.environmentKind, "local");
    await render({ ...props("local"), open: false });
    await render(props("local", "general"));
    assert.equal(globalThis.__taskReview.environmentKind, "local");
  } finally {
    await act(async () => root.unmount());
    element.remove();
  }
});

test("NewTaskFlow approval sends the same mode-scoped environment shown in its review", async () => {
  for (const [mode, expected] of [
    ["cloud", "local"],
    ["local", "worktree"],
  ]) {
    const element = document.createElement("div");
    document.body.append(element);
    const root = createRoot(element);
    const requests = [];
    const input = props(mode);
    input.newTaskFlowClientV2 = {
      bindOperation: () => ({
        ...api,
        approvePlanAndStart: async (request) => {
          requests.push(request);
          return { conversation: input.resumeDraft.session.conversation };
        },
      }),
    };
    try {
      await act(async () =>
        root.render(
          React.createElement(
            I18nProvider,
            null,
            React.createElement(NewTaskFlow, input),
          ),
        ),
      );
      await flush();
      await act(async () => globalThis.__taskReview.onAcknowledgeVersion());
      const approve = document.querySelector(
        ".new-task-review-footer-actions button.primary",
      );
      assert.ok(approve);
      assert.equal(approve.disabled, false);
      await act(async () => approve.click());
      await flush();
      assert.equal(requests.length, 1);
      assert.equal(requests[0].environmentKind, expected);
      assert.equal(requests[0].permissionProfile, "workspace_write");
    } finally {
      await act(async () => root.unmount());
      element.remove();
    }
  }
});

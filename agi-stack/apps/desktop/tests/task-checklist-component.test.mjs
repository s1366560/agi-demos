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
      "export {TaskChecklist} from './src/features/chat/TaskChecklist'; export {AgentTimeline} from './src/features/chat/ChatTimeline'; export {I18nProvider} from './src/i18n'; export {ToastProvider} from './src/features/feedback/ToastCenter';",
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
    return value?.[Symbol.toStringTag] === "Module"
      ? { ...value, __esModule: true }
      : value;
  },
  module,
  module.exports,
);
const { TaskChecklist, AgentTimeline, I18nProvider, ToastProvider } = module.exports;

const ITEMS = [
  { id: "a", content: "Write the model", status: "completed", priority: "high", orderIndex: 0 },
  { id: "b", content: "Wire the panel", status: "in_progress", priority: "medium", orderIndex: 1 },
  { id: "c", content: "Polish styles", status: "pending", priority: "low", orderIndex: 2 },
  { id: "d", content: "Retried step", status: "failed", priority: "medium", orderIndex: 3 },
  { id: "e", content: "Dropped idea", status: "cancelled", priority: "medium", orderIndex: 4 },
];

const render = (items) => {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(TaskChecklist, { items }),
      ),
    );
  });
  return { container, root };
};

test("renders nothing when there are no todos", () => {
  const { container, root } = render([]);
  assert.equal(container.querySelector(".task-checklist"), null);
  act(() => root.unmount());
  container.remove();
});

test("renders the progress header with counts, percent, and ARIA progressbar", () => {
  const { container, root } = render(ITEMS);
  const panel = container.querySelector(".task-checklist");
  assert.ok(panel, "panel renders");
  assert.equal(
    container.querySelector(".task-checklist-count").textContent,
    "1/5 completed",
  );
  assert.equal(
    container.querySelector(".task-checklist-percent").textContent,
    "20%",
  );
  const progressbar = container.querySelector("[role='progressbar']");
  assert.ok(progressbar, "progressbar exists");
  assert.equal(progressbar.getAttribute("aria-valuenow"), "20");
  const fill = container.querySelector(".task-checklist-progress-fill");
  assert.ok(fill.style.transform.includes("scaleX(0.2)"));
  assert.equal(
    container.querySelector(".task-checklist-active").textContent,
    "1 in progress",
  );
  act(() => root.unmount());
  container.remove();
});

test("renders one row per task with status icons, active tint, and priority dots", () => {
  const { container, root } = render(ITEMS);
  const rows = container.querySelectorAll(".task-checklist-item");
  assert.equal(rows.length, 5);
  const statuses = [...rows].map((row) =>
    [...row.classList].find((name) => name.startsWith("status-")),
  );
  assert.deepEqual(statuses, [
    "status-completed",
    "status-in_progress",
    "status-pending",
    "status-failed",
    "status-cancelled",
  ]);
  assert.equal(rows[1].classList.contains("is-active"), true);
  assert.equal(
    rows[1].querySelector(".task-checklist-icon").getAttribute("aria-label"),
    "In progress",
  );
  // Priority dots render only for non-medium priorities.
  assert.ok(rows[0].querySelector(".task-checklist-priority.is-high"));
  assert.ok(rows[2].querySelector(".task-checklist-priority.is-low"));
  assert.equal(rows[1].querySelector(".task-checklist-priority"), null);
  act(() => root.unmount());
  container.remove();
});

test("header toggles the item list while keeping the progress header visible", () => {
  const { container, root } = render(ITEMS);
  const header = container.querySelector(".task-checklist-header");
  const body = container.querySelector(".task-checklist-body");
  assert.equal(header.getAttribute("aria-expanded"), "true");
  assert.equal(body.hasAttribute("hidden"), false);
  act(() => {
    header.click();
  });
  assert.equal(header.getAttribute("aria-expanded"), "false");
  assert.equal(body.hasAttribute("hidden"), true);
  assert.ok(container.querySelector("[role='progressbar']"), "progress stays visible");
  act(() => root.unmount());
  container.remove();
});

// --- todowrite timeline-row summarization (audit §1.6, second half) --------

test("a todowrite tool call renders a status-count row title", () => {
  const state = {
    conversationId: "conv-todo",
    items: [
      {
        id: "call-1",
        type: "act",
        toolName: "todowrite",
        eventTimeUs: 1_784_282_066_000_000,
        eventCounter: 1,
        toolInput: {
          todos: [
            { content: "Alpha", status: "completed" },
            { content: "Beta", status: "pending" },
          ],
        },
      },
      {
        id: "result-1",
        type: "observe",
        toolName: "todowrite",
        eventTimeUs: 1_784_282_067_000_000,
        eventCounter: 2,
        toolOutput: { ok: true },
      },
    ],
    approvalRequests: [],
    artifactVersions: [],
    artifactDeliveries: [],
    toolInvocations: [],
    loading: false,
    loadingEarlier: false,
    error: null,
    hasMore: false,
    firstCursor: null,
    lastCursor: null,
  };
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(
          ToastProvider,
          null,
          React.createElement(AgentTimeline, {
            imagePreviewClient: null,
            state,
            expandedItems: {},
            onToggleItem: () => {},
            onLoadEarlier: () => {},
            onShowEarlier: () => {},
            earlierRenderAllowance: 0,
            onRetry: () => {},
            onRespondToHitl: async () => {},
            respondableHitlRequestIds: [],
            activityPresence: "recorded",
          }),
        ),
      ),
    );
  });
  const preview = container.querySelector(".timeline-step-copy");
  assert.ok(preview, "tool-call row renders");
  assert.equal(
    preview.textContent,
    "Update 2 todos: 1 completed, 1 pending: Alpha, Beta",
  );
  const stepLabel = container.querySelector(".timeline-row-step-label");
  assert.equal(stepLabel, null, "redundant tool label is not repeated");
  act(() => root.unmount());
  container.remove();
});

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
      "export {mergeLiveTimelineEvent} from './src/features/chat/appTimelineEventModel'; export {coalesceStreamingTextEvents} from './src/features/chat/streamingTextEventModel'; export {AgentTimeline} from './src/features/chat/ChatTimeline'; export {I18nProvider} from './src/i18n'; export {ToastProvider} from './src/features/feedback/ToastCenter';",
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
    if (
      ["react-markdown", "remark-gfm", "remark-math", "rehype-katex"].includes(
        name,
      )
    ) {
      return value.default;
    }
    return value?.[Symbol.toStringTag] === "Module"
      ? { ...value, __esModule: true }
      : value;
  },
  module,
  module.exports,
);
const {
  mergeLiveTimelineEvent,
  coalesceStreamingTextEvents,
  AgentTimeline,
  I18nProvider,
  ToastProvider,
} = module.exports;

for (const terminal of ["assistant_message", "text_end"]) {
  test(`local deltas paint before ${terminal} and settle into one assistant bubble`, async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    let items = [];
    let counter = 0;
    const event = (type, data) => ({
      type,
      conversation_id: "streaming-conversation",
      message_id: "local-assistant-user-1-0",
      event_time_us: 1_790_000_000_000_000 + ++counter,
      event_counter: counter,
      data,
    });
    const renderBatch = async (events) => {
      for (const item of coalesceStreamingTextEvents(events)) {
        items = mergeLiveTimelineEvent(items, item);
      }
      await act(async () =>
        root.render(
          React.createElement(
            I18nProvider,
            null,
            React.createElement(
              ToastProvider,
              null,
              React.createElement(AgentTimeline, {
                imagePreviewClient: null,
                state: {
                  conversationId: "streaming-conversation",
                  items,
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
                },
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
        ),
      );
    };
    try {
      await renderBatch([event("text_delta", { delta: "流式" })]);
      assert.match(container.textContent, /流式/);
      assert.ok(
        container.querySelector(".is-streaming"),
        "first token is visible while pending",
      );
      assert.equal(items[0].metadata.streaming, true);
      const firstId = items[0].id;
      await renderBatch([
        event("text_delta", { delta: " " }),
        event("text_delta", { delta: "输出" }),
        event("text_delta", { delta: "\n\n第二段" }),
      ]);
      assert.match(container.textContent, /流式 输出/);
      assert.match(container.textContent, /第二段/);
      assert.equal(items[0].content, "流式 输出\n\n第二段");
      assert.equal(items[0].id, firstId);
      await renderBatch([
        event(
          terminal,
          terminal === "assistant_message"
            ? { content: "流式 输出\n\n第二段" }
            : {},
        ),
      ]);
      assert.equal(
        items.length,
        1,
        "terminal snapshot replaces the streamed response",
      );
      assert.equal(items[0].metadata.streaming, false);
      assert.equal(container.querySelector(".is-streaming"), null);
      assert.match(container.textContent, /流式 输出/);
      await renderBatch([event("text_delta", { delta: "late duplicate" })]);
      assert.doesNotMatch(container.textContent, /late duplicate/);
    } finally {
      await act(async () => root.unmount());
      container.remove();
    }
  });
}

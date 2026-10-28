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
      "export {HitlResponseCard} from './src/features/chat/HitlResponseCard'; export {AgentTimeline} from './src/features/chat/ChatTimeline'; export {I18nProvider} from './src/i18n';",
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
const { HitlResponseCard, AgentTimeline, I18nProvider } = module.exports;
test("declared permission description displays punctuation and markup as inert text", async () => {
  const description =
    "Write if it doesn't exist; mode='append'. Keep &amp; <img src=x onerror=alert(1)> literal.";
  const element = document.createElement("div");
  document.body.append(element);
  const root = createRoot(element);
  try {
    await act(async () =>
      root.render(
        React.createElement(
          I18nProvider,
          null,
          React.createElement(HitlResponseCard, {
            item: {
              id: "event",
              type: "permission_asked",
              requestId: "permission",
              payload: { request_id: "permission" },
            },
            hitlType: "permission",
            canRespond: true,
            onRespond: async () => {},
            approvalRequest: {
              id: "permission",
              type: "permission",
              authority_revision: 1,
              permission: {
                tool_name: "sandbox_write",
                action: "execute",
                description,
                risk_level: "medium",
                allow_remember: false,
              },
            },
          }),
        ),
      ),
    );
    const text = element.querySelector(".timeline-approval-evidence p");
    assert.equal(text.textContent, description);
    assert.equal(text.querySelector("img"), null);
    assert.equal(text.children.length, 0);
    assert.ok(!text.textContent.includes("&#x27;"));
  } finally {
    await act(async () => root.unmount());
    element.remove();
  }
});

test("real timeline distinguishes loading authority from ready or failed missing fields", async () => {
  const element = document.createElement("div");
  document.body.append(element);
  const root = createRoot(element);
  const request = {
    id: "permission",
    type: "permission",
    authority_revision: 1,
    permission: {
      tool_name: "write",
      action: "execute",
      description: "Actual tool description",
      risk_level: "medium",
      allow_remember: false,
    },
  };
  const item = {
    id: "event",
    type: "permission_asked",
    requestId: "permission",
    eventTimeUs: 1000000,
    eventCounter: 0,
    payload: { request_id: "permission" },
  };
  const render = async (loading, authority, error = null) => {
    await act(async () =>
      root.render(
        React.createElement(
          I18nProvider,
          null,
          React.createElement(AgentTimeline, {
            imagePreviewClient: null,
            state: {
              conversationId: "conversation",
              items: [item],
              approvalRequests: authority ? [authority] : [],
              approvalAuthorityLoading: loading,
              artifactVersions: [],
              artifactDeliveries: [],
              toolInvocations: [],
              loading: false,
              loadingEarlier: false,
              error,
              hasMore: false,
              firstCursor: null,
              lastCursor: null,
            },
            expandedItems: { event: true },
            onToggleItem: () => {},
            onLoadEarlier: () => {},
            onShowEarlier: () => {},
            earlierRenderAllowance: 0,
            onRetry: () => {},
            onRespondToHitl: async () => {},
            respondableHitlRequestIds: authority ? ["permission"] : [],
            activityPresence: "recorded",
          }),
        ),
      ),
    );
  };
  try {
    await render(true, null);
    assert.match(element.textContent, /Synchronizing approval|正在同步审批/);
    assert.doesNotMatch(element.textContent, /Missing fields|缺少字段/);
    await render(false, request);
    assert.match(element.textContent, /Actual tool description/);
    assert.doesNotMatch(
      element.textContent,
      /Synchronizing approval|正在同步审批|Missing fields|缺少字段/,
    );
    await render(false, null);
    assert.match(element.textContent, /Missing fields|缺少字段/);
    await render(false, null, "authority_unavailable");
    assert.match(element.textContent, /Missing fields|缺少字段/);
    assert.doesNotMatch(
      element.textContent,
      /Synchronizing approval|正在同步审批/,
    );
  } finally {
    await act(async () => root.unmount());
    element.remove();
  }
});

test("device MCP approval renders only Once and denial and submits the formal responses", async () => {
  const element = document.createElement("div");
  document.body.append(element);
  const root = createRoot(element);
  const submissions = [];
  const render = async (kind) => {
    await act(async () => root.render(React.createElement(
      I18nProvider,
      null,
      React.createElement(HitlResponseCard, {
        item: {
          id: "device-mcp-event",
          type: "permission_asked",
          requestId: "device-mcp-permission",
          payload: { request_id: "device-mcp-permission" },
        },
        hitlType: "permission",
        canRespond: true,
        onRespond: async (submission) => submissions.push(submission),
        approvalRequest: {
          id: "device-mcp-permission",
          kind: "permission",
          status: "pending",
          authority_revision: 4,
          permission: {
            tool_name: "mcp_owned",
            action: "execute",
            description: "Invoke the connected MCP tool once",
            risk_level: "low",
            allow_remember: false,
          },
          decision: {
            action: { name: "mcp_owned", label: "Invoke MCP tool" },
            target: { kind, id: "pending-device-mcp" },
            data: { summary: "Apply the approved input" },
            reason: "The task requires this invocation",
            risk: { level: "low", rationale: "Restricted to the approved input" },
            reversibility: { mode: "reversible" },
            scope: { kind: "tool", ids: ["mcp_owned"] },
            evidence: [{ kind: "tool", id: "mcp_owned", label: "Connected tool" }],
          },
        },
      }),
    )));
  };
  const button = (label) => [...element.querySelectorAll("button")]
    .find((candidate) => candidate.textContent.trim() === label);
  try {
    await render("device_mcp_tool");
    assert.equal(button("Always allow this tool"), undefined);
    assert.equal(button("Allow once")?.disabled, false);
    assert.equal(button("Deny")?.disabled, false);
    await act(async () => button("Allow once").click());
    assert.equal(submissions.length, 1);
    assert.deepEqual(submissions[0], {
      requestId: "device-mcp-permission",
      hitlType: "permission",
      responseData: { action: "allow", granted: true, scope: "once" },
      expectedRevision: 4,
      idempotencyKey: "device-mcp-permission:4:permission",
    });
    await act(async () => button("Deny").click());
    await act(async () => button("Deny without feedback").click());
    assert.equal(submissions.length, 2);
    assert.deepEqual(submissions[1].responseData, {
      action: "deny", granted: false, scope: "once",
    });

    await render("repl_step");
    assert.equal(button("Always allow this tool"), undefined);
    await render("tool");
    assert.equal(button("Always allow this tool")?.disabled, false);
  } finally {
    await act(async () => root.unmount());
    element.remove();
  }
});

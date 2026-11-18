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
      "export {ChatPanel} from './src/features/chat/ChatPanel'; export {AgentTimeline} from './src/features/chat/ChatTimeline'; export {I18nProvider} from './src/i18n'; export {ToastProvider} from './src/features/feedback/ToastCenter';",
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
    if (['react-markdown', 'remark-gfm', 'remark-math', 'rehype-katex'].includes(name)) return value.default;
    // Node 22 loads ESM namespaces through require; preserve their default export for esbuild.
    return value?.[Symbol.toStringTag] === 'Module' ? { ...value, __esModule: true } : value;
  },
  module,
  module.exports,
);
const { ChatPanel, I18nProvider, ToastProvider } = module.exports;

const noop = () => {};
let sequence = 0;
function baseProps() {
  const conversation = {
    id: `stop-controls-${++sequence}`, tenant_id: 'tenant', project_id: 'project',
    workspace_id: null, agent_config: {},
    execution_selection: { agent_id: null, forced_skill_id: null, subagent_id: null },
  };
  return {
    api: {
      listWorkspaceAgents: async () => [], listManagedAgents: async () => [],
      listManagedSkills: async () => [], listMarketplacePlugins: async () => [],
      listManagedSubAgents: async () => [], listPromptTemplates: async () => [],
      readExecutionSelection: async () => conversation,
    },
    conversations: [conversation], selectedConversationId: conversation.id,
    messages: [], timelineState: null, agentTaskSignals: [], sessionTitle: 'Stop controls',
    scopeLabel: 'Project', activityPresence: 'recorded', activityStructuredEvidence: null,
    composerVariant: 'session', composerResetKey: conversation.id, initialInput: 'Continue with my request',
    sending: true, canonicalRunStatus: 'running', disabledReason: 'Run is active',
    activeWorkflowTarget: 'conversation', runInputDelivery: null, runInputDeliveryOptions: [],
    runInputs: [], runInputsLoading: false, runInputsError: null, promotingRunInputId: null,
    runInputAuthorityRunId: null, references: [], onRunInputDeliveryChange: noop,
    onPromoteRunInput: noop, onRemoveReference: noop, onSend: noop, onRefresh: noop,
    onLoadEarlier: noop, onRespondToHitl: async () => {}, respondableHitlRequestIds: [],
    onWorkflowSelect: noop, imagePreviewClient: null, voiceSessionOperations: {},
    desktopRuntimeConfig: {
      mode: 'local', apiBaseUrl: 'http://localhost', apiKey: '', localApiToken: '',
      tenantId: 'tenant', projectId: 'project', workspaceId: '', workspaceRoot: '',
      deviceAuthorizationBaseUrl: '',
    },
  };
}

async function renderPanel(overrides = {}) {
  const props = { ...baseProps(), ...overrides };
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(React.createElement(I18nProvider, null,
    React.createElement(ToastProvider, null, React.createElement(ChatPanel, props)),
  )));
  for (let i = 0; i < 2; i++) await act(async () => { await new Promise(setImmediate); });
  return {
    container,
    rerender: async (patch) => {
      Object.assign(props, patch);
      await act(async () => root.render(React.createElement(I18nProvider, null,
        React.createElement(ToastProvider, null, React.createElement(ChatPanel, props)),
      )));
    },
    cleanup: async () => { await act(async () => root.unmount()); container.remove(); },
  };
}

test('active full ChatPanel without a cancellation target does not advertise ordinary send', async () => {
  const view = await renderPanel();
  try {
    assert.equal(view.container.querySelector('.send-pill'), null);
    assert.equal(view.container.querySelector('.stop-response-pill'), null);
    assert.equal(view.container.querySelector('textarea').disabled, true);
  } finally { await view.cleanup(); }
});

test('active full ChatPanel keeps available stop independent from disabled message input', async () => {
  let stopped = 0;
  const view = await renderPanel({
    onStopResponse: async () => { stopped++; return { status: 'cancel_requested' }; },
    stopResponseTransportConnected: true,
  });
  try {
    const stop = view.container.querySelector('.stop-response-pill');
    assert.ok(stop);
    assert.equal(stop.disabled, false);
    assert.equal(view.container.querySelector('.send-pill'), null);
    assert.equal(view.container.querySelector('textarea').disabled, true);
    await act(async () => stop.click());
    assert.equal(stopped, 1);
    assert.equal(view.container.querySelector('.stop-response-pill').disabled, true);
  } finally { await view.cleanup(); }
});

test('disconnected full ChatPanel shows a disabled stop without invoking the transport', async () => {
  let stopped = 0;
  const view = await renderPanel({
    onStopResponse: async () => { stopped++; return { status: 'cancel_requested' }; },
    stopResponseTransportConnected: false,
  });
  try {
    const stop = view.container.querySelector('.stop-response-pill');
    assert.ok(stop);
    assert.equal(stop.disabled, true);
    assert.match(stop.title, /Reconnect|connection|连接/i);
    await act(async () => stop.click());
    assert.equal(stopped, 0);
    assert.equal(view.container.querySelector('.send-pill'), null);
  } finally { await view.cleanup(); }
});

test('terminal full ChatPanel removes stop and restores ordinary send', async () => {
  let sent = 0, stopped = 0;
  const view = await renderPanel({
    canonicalRunStatus: 'completed', sending: false, disabledReason: null,
    onStopResponse: async () => { stopped++; return { status: 'cancel_requested' }; },
    stopResponseTransportConnected: true,
    onSend: () => { sent++; },
  });
  try {
    assert.equal(view.container.querySelector('.stop-response-pill'), null);
    const send = view.container.querySelector('.send-pill');
    assert.ok(send);
    assert.equal(send.disabled, false);
    await act(async () => send.click());
    assert.equal(sent, 1);
    assert.equal(stopped, 0);
  } finally { await view.cleanup(); }
});

test('explicit compose-ahead capability retains queue input during an active run', async () => {
  let sent = 0;
  const view = await renderPanel({
    disabledReason: null, sending: false, composeAheadFallbackAllowed: true,
    onSend: () => { sent++; },
  });
  try {
    const queue = view.container.querySelector('.composer-send-split .send-pill');
    assert.ok(queue, 'authorized compose-ahead queue stays available');
    assert.equal(queue.disabled, false);
    await act(async () => queue.click());
    assert.equal(sent, 0, 'queueing must not dispatch ordinary input to the active run');
    assert.ok(view.container.querySelector('.compose-ahead-queue'));
    assert.match(view.container.textContent, /Continue with my request/);
    await view.rerender({ canonicalRunStatus: 'completed' });
    assert.equal(sent, 1, 'queued input dispatches only after the authoritative run ends');
  } finally { await view.cleanup(); }
});

for (const delivery of ['queue_next', 'steer_now']) {
  test(`explicit ${delivery} capability delivers input while the full ChatPanel is running`, async () => {
    const sent = [];
    const view = await renderPanel({
      disabledReason: null, sending: true,
      runInputDelivery: delivery, runInputDeliveryOptions: [delivery], runInputAuthorityRunId: 'bound-run',
      onSend: (content, contextItems, done) => { sent.push({ content, contextItems }); done?.(); },
    });
    try {
      const send = view.container.querySelector('.send-pill');
      assert.ok(send);
      assert.equal(send.disabled, false, 'active response streaming must not disable authorized run input');
      await act(async () => send.click());
      assert.equal(sent.length, 1);
      assert.equal(sent[0].content, 'Continue with my request');
      assert.equal(view.container.querySelector('textarea').value, '');
    } finally { await view.cleanup(); }
  });
}

for (const [name, patch] of [
  ['missing run authority', { runInputAuthorityRunId: null }],
  ['missing delivery capability', { runInputDeliveryOptions: [] }],
  ['no selected delivery', { runInputDelivery: null }],
  ['selected delivery was revoked', { runInputDeliveryOptions: ['steer_now'] }],
  ['authority unavailable', { disabledReason: 'Authority unavailable' }],
  ['run is already terminal', { canonicalRunStatus: 'completed', sending: false }],
]) {
  test(`full ChatPanel does not send run input with ${name}`, async () => {
    let sent = 0;
    const view = await renderPanel({
      disabledReason: null, sending: true,
      runInputDelivery: 'queue_next', runInputDeliveryOptions: ['queue_next'], runInputAuthorityRunId: 'bound-run',
      onSend: () => { sent++; }, ...patch,
    });
    try {
      const send = view.container.querySelector('.send-pill');
      assert.ok(!send || send.disabled);
      if (send) await act(async () => send.click());
      assert.equal(sent, 0);
    } finally { await view.cleanup(); }
  });
}

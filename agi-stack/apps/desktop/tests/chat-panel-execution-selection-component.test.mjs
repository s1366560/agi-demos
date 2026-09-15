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
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
};
const flush = async () => {
  await act(async () => {
    await new Promise(setImmediate);
  });
};
test("complete ChatPanel restores binding and awaits successful clear while active-run failure retains chip", async () => {
  let stored = {
    id: "selection-ui",
    tenant_id: "tenant",
    project_id: "project",
    workspace_id: null,
    agent_config: { selected_agent_id: "builtin:all-access" },
    execution_selection: {
      agent_id: null,
      forced_skill_id: "saved-skill",
      subagent_id: null,
    },
  };
  let mutation;
  const calls = [],
    sent = [];
  const api = {
    listWorkspaceAgents: async () => [],
    listManagedAgents: async () => [],
    listManagedSkills: async () => [
      { id: "saved-skill", name: "Saved skill", status: "active" },
    ],
    listMarketplacePlugins: async () => [],
    listManagedSubAgents: async () => [],
    listPromptTemplates: async () => [],
    readExecutionSelection: async () => stored,
    updateExecutionSelection: async (c, p) => {
      calls.push({ id: c.id, patch: p });
      mutation = deferred();
      return mutation.promise;
    },
  };
  const noop = () => {};
  const props = {
    api,
    conversations: [stored],
    selectedConversationId: stored.id,
    messages: [],
    timelineState: null,
    agentTaskSignals: [],
    sessionTitle: "Selection",
    scopeLabel: "Project",
    activityPresence: "recorded",
    activityStructuredEvidence: null,
    composerVariant: "session",
    composerResetKey: "one",
    initialInput: "Check current tools",
    sending: false,
    disabledReason: null,
    activeWorkflowTarget: "conversation",
    runInputDelivery: null,
    runInputDeliveryOptions: [],
    runInputs: [],
    runInputsLoading: false,
    runInputsError: null,
    promotingRunInputId: null,
    runInputAuthorityRunId: null,
    references: [],
    onRunInputDeliveryChange: noop,
    onPromoteRunInput: noop,
    onRemoveReference: noop,
    onSend: (text, items, done) => {
      sent.push({ text, items });
      done?.();
    },
    onRefresh: noop,
    onLoadEarlier: noop,
    onRespondToHitl: async () => {},
    respondableHitlRequestIds: [],
    onWorkflowSelect: noop,
    imagePreviewClient: null,
    voiceSessionOperations: {},
    voiceTranscriptionConfig: {
      mode: "local",
      apiBaseUrl: "http://localhost",
      apiKey: "",
      localApiToken: "",
      tenantId: "tenant",
      projectId: "project",
      workspaceId: "",
      workspaceRoot: "",
      deviceAuthorizationBaseUrl: "",
    },
  };
  const container = document.createElement("div");
  document.body.append(container);
  let root = createRoot(container);
  const render = async () => {
    await act(async () =>
      root.render(
        React.createElement(
          I18nProvider,
          null,
          React.createElement(
            ToastProvider,
            null,
            React.createElement(ChatPanel, props),
          ),
        ),
      ),
    );
    await flush();
    await flush();
  };
  const chip = () =>
    [...container.querySelectorAll("button")].find((b) =>
      b.getAttribute("aria-label")?.includes("Saved skill"),
    );
  try {
    await render();
    assert.ok(chip(), "authoritative skill must be visible");
    await act(async () => container.querySelector("button.send-pill").click());
    await flush();
    assert.equal(sent.length, 1);
    assert.equal(
      sent[0].items.find((item) => item.kind === "skill").metadata
        .execution_skill_name,
      "saved-skill",
    );
    assert.ok(chip(), "send success must retain the persistent execution chip");
    await act(async () => chip().click());
    assert.ok(chip());
    assert.equal(chip().disabled, true);
    assert.deepEqual(calls[0], {
      id: "selection-ui",
      patch: { forced_skill_id: null },
    });
    await act(async () => mutation.reject(new Error("active run")));
    await flush();
    assert.ok(chip(), "failed clear must retain binding");
    assert.match(container.textContent, /active run/);
    await act(async () => chip().click());
    assert.ok(chip());
    stored = {
      ...stored,
      execution_selection: {
        ...stored.execution_selection,
        forced_skill_id: null,
      },
    };
    await act(async () => mutation.resolve(stored));
    await flush();
    assert.equal(chip(), undefined, "successful clear removes the chip");
    await act(async () => root.unmount());
    root = createRoot(container);
    props.conversations = [stored];
    await render();
    assert.equal(chip(), undefined, "reload cannot resurrect cleared binding");
    await act(async () => container.querySelector("button.send-pill").click());
    assert.equal(sent.length, 2);
    assert.equal(
      sent[1].items.some((item) => item.kind === "skill"),
      false,
    );
    stored = {
      ...stored,
      id: "selection-a",
      execution_selection: {
        ...stored.execution_selection,
        forced_skill_id: "saved-skill",
      },
    };
    props.conversations = [stored];
    props.selectedConversationId = stored.id;
    await render();
    await act(async () => chip().click());
    const firstMutation = mutation;
    const firstConversation = stored;
    stored = { ...stored, id: "selection-b" };
    props.conversations = [stored];
    props.selectedConversationId = stored.id;
    await render();
    assert.equal(
      chip().disabled,
      false,
      "previous conversation pending cannot block current clear",
    );
    await act(async () => chip().click());
    const secondMutation = mutation;
    assert.notEqual(secondMutation, firstMutation);
    assert.equal(chip().disabled, true);
    await act(async () =>
      firstMutation.resolve({
        ...firstConversation,
        execution_selection: {
          ...firstConversation.execution_selection,
          forced_skill_id: null,
        },
      }),
    );
    await flush();
    assert.equal(
      chip().disabled,
      true,
      "old completion cannot clear current pending or binding",
    );
    await act(async () =>
      secondMutation.reject(new Error("current active run")),
    );
    await flush();
    assert.ok(chip());
    assert.equal(chip().disabled, false);
    assert.match(container.textContent, /current active run/);
  } finally {
    await act(async () => root.unmount());
    container.remove();
  }
});

test('child trace failure keeps conversation messages and independent history controls usable', async () => {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  let retried = 0, earlier = 0;
  const props = {
    imagePreviewClient: null,
    state: { conversationId: 'conversation', items: [{id:'user',type:'user_message',role:'user',content:'Persisted parent message',eventTimeUs:1,eventCounter:1}],
      approvalRequests:[], artifactVersions:[], artifactDeliveries:[],toolInvocations:[],loading:false,loadingEarlier:false,error:null,subagentTraceError:'Trace temporarily unavailable',hasMore:true,firstCursor:{timeUs:1,counter:1},lastCursor:{timeUs:1,counter:1}},
    expandedItems:{},onToggleItem:()=>{},onLoadEarlier:()=>{earlier++;},onShowEarlier:()=>{},earlierRenderAllowance:50,onRetry:()=>{retried++;},onRespondToHitl:async()=>{},respondableHitlRequestIds:[],activityPresence:'recorded',
  };
  try {
    await act(async()=>root.render(React.createElement(I18nProvider,null,React.createElement(ToastProvider,null,React.createElement(module.exports.AgentTimeline,props)))));
    assert.match(container.textContent,/Persisted parent message/);
    assert.match(container.querySelector('[role="alert"]').textContent,/Trace temporarily unavailable/);
    const retry=container.querySelector('[role="alert"] button');
    await act(async()=>retry.click()); assert.equal(retried,1);
    const history=container.querySelector('.timeline-history-control button');
    assert.ok(history,'trace failure must preserve pagination control');
    await act(async()=>history.click()); assert.equal(earlier,1);
  } finally { await act(async()=>root.unmount());container.remove(); }
});

test('actual full cancellation timeline renders one child card across parent activity', async () => {
  const frames=JSON.parse(require('node:fs').readFileSync(new URL('./fixtures/cloud-subagent-cancel-full-timeline.json',import.meta.url),'utf8'));
  const base='/tmp/agistack-desktop-test-dist/apps/desktop/src';
  const {normalizeSubagentLifecycleEnvelope}=require(`${base}/hooks/subagentLifecycleEnvelope.js`);
  const {mergeLiveTimelineEvent}=require(`${base}/features/chat/appTimelineEventModel.js`);
  const first=frames.find(e=>e.type==='subagent_lifecycle');
  const scope={mode:'cloud',tenantId:first.tenant_id,projectId:first.project_id};
  const items=frames.map(e=>normalizeSubagentLifecycleEnvelope(e,scope)).filter(Boolean).reduce(mergeLiveTimelineEvent,[]);
  const container=document.createElement('div');document.body.append(container);const root=createRoot(container);
  const props={imagePreviewClient:null,state:{conversationId:first.data.data.conversation_id,items,approvalRequests:[],artifactVersions:[],artifactDeliveries:[],toolInvocations:[],loading:false,loadingEarlier:false,error:null,hasMore:false,firstCursor:null,lastCursor:null},expandedItems:{},onToggleItem:()=>{},onLoadEarlier:()=>{},onShowEarlier:()=>{},earlierRenderAllowance:200,onRetry:()=>{},onRespondToHitl:async()=>{},respondableHitlRequestIds:[],activityPresence:'recorded'};
  try {
    await act(async()=>root.render(React.createElement(I18nProvider,null,React.createElement(ToastProvider,null,React.createElement(module.exports.AgentTimeline,props)))));
    const cards=container.querySelectorAll('.timeline-subagent-group');
    assert.equal(cards.length,1);
    assert.ok(cards[0].classList.contains('status-killed'));
    await act(async () => cards[0].querySelector('.subagent-group-header').click());
    assert.match(cards[0].textContent, /Termination reason|终止原因/);
    assert.doesNotMatch(cards[0].textContent, /Failure|失败原因/);
    assert.ok(container.querySelector('.timeline-tool-group'),'parent tool activity remains independently visible');
  } finally {await act(async()=>root.unmount());container.remove();}
});

test('actual reloaded cloud todowrite history has one completed tool card across assistant commit', async () => {
  const response=JSON.parse(require('node:fs').readFileSync(new URL('./fixtures/cloud-task-display-messages.json',import.meta.url),'utf8'));
  const container=document.createElement('div');document.body.append(container);const root=createRoot(container);
  const props={imagePreviewClient:null,state:{conversationId:response.conversationId,items:response.timeline,approvalRequests:[],artifactVersions:[],artifactDeliveries:[],toolInvocations:[],loading:false,loadingEarlier:false,error:null,hasMore:false,firstCursor:null,lastCursor:null},expandedItems:{},onToggleItem:()=>{},onLoadEarlier:()=>{},onShowEarlier:()=>{},earlierRenderAllowance:200,onRetry:()=>{},onRespondToHitl:async()=>{},respondableHitlRequestIds:[],activityPresence:'recorded'};
  try {
    await act(async()=>root.render(React.createElement(I18nProvider,null,React.createElement(ToastProvider,null,React.createElement(module.exports.AgentTimeline,props)))));
    assert.equal(container.querySelectorAll('.timeline-tool-group').length,1,'one actual execution must produce one card');
    assert.equal(container.querySelectorAll('.timeline-tool-group.status-running').length,0);
    assert.equal(container.querySelectorAll('.timeline-tool-group.status-complete').length,1);
  } finally {await act(async()=>root.unmount());container.remove();}
});

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const webRequire = createRequire(new URL('../../../../web/package.json', import.meta.url));
const { Window } = await import(pathToFileURL(webRequire.resolve('happy-dom')).href);
const window = new Window({ url: 'http://localhost/' });
for (const key of [
  'window',
  'document',
  'navigator',
  'HTMLElement',
  'Element',
  'Node',
  'DOMParser',
  'MutationObserver',
  'ResizeObserver',
  'getComputedStyle',
  'requestAnimationFrame',
  'cancelAnimationFrame',
]) {
  const value = key === 'window' ? window : window[key];
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value:
      typeof value === 'function' &&
      ['getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame'].includes(key)
        ? value.bind(window)
        : value,
  });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react'),
  { act } = React,
  { createRoot } = require('react-dom/client');
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const compiled = await esbuild.build({
  stdin: {
    contents:
      "export {ChatPanel} from './src/features/chat/ChatPanel'; export {ChatOverflowMenu} from './src/features/chat/ChatOverflowMenu'; export {NarrativeMessageFrame} from './src/features/chat/ChatTranscript'; export {AgentTimeline} from './src/features/chat/ChatTimeline'; export {I18nProvider} from './src/i18n'; export {ToastProvider} from './src/features/feedback/ToastCenter'; export {SessionWorkspace} from './src/features/session/SessionWorkspace'; export {PlatformPluginConversationSlots} from './src/features/chat/PlatformPluginConversationSlots'; export {DesktopRendererGenerationProviderV2} from './src/plugins/desktopRendererGenerationContextV2'; export {TitlebarToolbarProvider} from './src/features/chat/ConversationToolbar'; export {DesktopTitlebar} from './src/features/chrome/DesktopTitlebar';",
    resolveDir: new URL('..', import.meta.url).pathname,
    loader: 'ts',
  },
  write: false,
  bundle: true,
  platform: 'node',
  format: 'cjs',
  packages: 'external',
  loader: { '.css': 'empty', '.svg': 'text' },
  define: { 'import.meta.env.DEV': 'false', 'import.meta.env.PROD': 'true' },
});
const module = { exports: {} };
new Function('require', 'module', 'exports', compiled.outputFiles[0].text)(
  (name) => {
    const value = require(name);
    if (['react-markdown', 'remark-gfm', 'remark-math', 'rehype-katex'].includes(name))
      return value.default;
    // Node 22 loads ESM namespaces through require; preserve their default export for esbuild.
    return value?.[Symbol.toStringTag] === 'Module' ? { ...value, __esModule: true } : value;
  },
  module,
  module.exports,
);
const { ChatPanel, ChatOverflowMenu, NarrativeMessageFrame, I18nProvider, ToastProvider, SessionWorkspace, PlatformPluginConversationSlots, DesktopRendererGenerationProviderV2, TitlebarToolbarProvider, DesktopTitlebar } =
  module.exports;

async function mount(Component, props) {
  const element = document.createElement('div');
  document.body.append(element);
  const root = createRoot(element);
  await act(async () =>
    root.render(
      React.createElement(
        I18nProvider,
        null,
        React.createElement(ToastProvider, null, React.createElement(Component, props)),
      ),
    ),
  );
  return {
    element,
    async close() {
      await act(async () => root.unmount());
      element.remove();
    },
  };
}

test('secondary tools stay mounted inside closed overflow and Escape restores the trigger', async () => {
  let invoked = 0;
  const view = await mount(ChatOverflowMenu, {
    label: 'Tools',
    children: React.createElement(
      'button',
      {
        onClick() {
          invoked += 1;
        },
      },
      'Context',
    ),
  });
  try {
    const details = view.element.querySelector('details');
    const action = details.querySelector('button');
    assert.equal(details.open, false);
    assert.ok(action, 'closed disclosure retains mounted tool state');
    details.open = true;
    await act(async () => action.click());
    assert.equal(invoked, 1);
    await act(async () =>
      action.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })),
    );
    assert.equal(details.open, false);
    assert.ok(document.activeElement === details.querySelector('summary'));
    details.open = true;
    await act(async () =>
      document.body.dispatchEvent(new window.PointerEvent('pointerdown', { bubbles: true })),
    );
    assert.equal(details.open, false);
  } finally {
    await view.close();
  }
});

test('message content omits decorative avatars while preserving sender identity and metadata', async () => {
  const view = await mount(NarrativeMessageFrame, {
    kind: 'user',
    label: 'Alex',
    badge: '@Reviewer',
    time: '10:42',
    content: 'Review the release',
    className: 'workspace-message',
    children: React.createElement('p', null, 'Review the release'),
  });
  try {
    assert.ok(view.element.querySelector('.session-thread-avatar') === null);
    assert.equal(view.element.querySelector('.session-message-label').textContent, 'Alex');
    assert.equal(view.element.querySelector('.session-message-badge').textContent, '@Reviewer');
    assert.equal(view.element.querySelector('time').textContent, '10:42');
    assert.ok(view.element.querySelector('time svg') === null);
    assert.equal(view.element.querySelector('article').getAttribute('data-has-identity'), 'true');
    assert.ok(
      view.element.querySelector('[role="toolbar"] button'),
      'copy remains keyboard accessible',
    );
  } finally {
    await view.close();
  }
});

test('actual composer keeps permissions and send outside options while templates/context/idle voice are inside', async () => {
  let commands = 0;
  const conversation = {
    id: 'thread',
    tenant_id: 'tenant',
    project_id: 'project',
    workspace_id: null,
    agent_config: { selected_agent_id: 'builtin:all-access' },
    execution_selection: { agent_id: null, forced_skill_id: null, subagent_id: null },
  };
  const noop = () => {};
  function Conversation(props) {
    return React.createElement(TitlebarToolbarProvider, null,
      React.createElement(DesktopTitlebar, {
        contextTitle: 'Review', sidebarCollapsed: false, rightSidebarOpen: false,
        onToggleSidebar: noop, onToggleRightSidebar: noop,
      }),
      React.createElement(DesktopRendererGenerationProviderV2, {
      value: {
        state: { authority: { status: 'unavailable', error: 'Plugin unavailable', slotDefinitions: [] } },
        composition: { resolveConversationRendererModule: () => null },
        meta: { status: 'error' },
      },
    }, React.createElement(SessionWorkspace, {
      viewModel: { id: 'thread', title: 'Review', status: 'running', runActions: [], runRevision: 1, stage: 'unavailable' },
      liveConnected: true, liveError: null, runActionPending: null,
      onRunAction: noop, onOpenCanvas: noop,
      thread: React.createElement(React.Fragment, null,
        React.createElement(ChatPanel, props),
        React.createElement(PlatformPluginConversationSlots, {
          active: true, conversationId: 'thread', disabled: false,
          messageCount: 0, onOpenCommands: noop, sending: false,
          workflowTarget: 'changes',
        }),
      ),
    })));
  }
  const view = await mount(Conversation, {
    api: {
      listConversations: async () => [conversation],
      getConversationMessages: async () => [],
      listWorkspaceAgents: async () => [],
      listManagedAgents: async () => [],
      listManagedSkills: async () => [],
      listMarketplacePlugins: async () => [],
      listManagedSubAgents: async () => [],
      listPromptTemplates: async () => [],
      readExecutionSelection: async () => conversation,
    },
    conversations: [conversation],
    selectedConversationId: 'thread',
    messages: [],
    timelineState: null,
    agentTaskSignals: [],
    sessionTitle: 'Review',
    scopeLabel: 'Project',
    activityPresence: 'recorded',
    activityStructuredEvidence: null,
    composerVariant: 'session',
    composerResetKey: 'test',
    initialInput: 'Review',
    sending: false,
    disabledReason: null,
    activeWorkflowTarget: 'conversation',
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
    onSend: noop,
    onRefresh: noop,
    onLoadEarlier: noop,
    onRespondToHitl: async () => {},
    respondableHitlRequestIds: [],
    onWorkflowSelect: noop,
    imagePreviewClient: null,
    voiceSessionOperations: {},
    permissionPreset: 'full',
    permissionPresetFullAccessAcknowledged: true,
    onPermissionPresetChange: noop,
    onAcknowledgeFullAccessWarning: noop,
    onOpenCommands() {
      commands += 1;
    },
    desktopRuntimeConfig: {
      mode: 'local',
      apiBaseUrl: 'http://localhost',
      apiKey: '',
      localApiToken: '',
      tenantId: 'tenant',
      projectId: 'project',
      workspaceId: '',
      workspaceRoot: '',
      deviceAuthorizationBaseUrl: '',
    },
  });
  try {
    const menu = view.element.querySelector('.composer-utility-menu');
    assert.ok(menu);
    assert.equal(menu.open, false);
    assert.ok(menu.querySelector('.prompt-template-library'));
    assert.equal(menu.querySelectorAll('.composer-voice-button').length, 2);
    assert.ok(
      view.element.querySelector('.composer-right-actions .composer-voice-button') === null,
    );
    const permission = view.element.querySelector('.permission-preset-control');
    assert.ok(permission && !permission.closest('.chat-overflow-menu'));
    assert.ok(view.element.querySelector('.send-pill'));
    menu.open = true;
    const context = [...menu.querySelectorAll('button')].find(
      (button) => button.textContent.trim() === 'Context',
    );
    assert.ok(context);
    await act(async () => context.click());
    assert.equal(commands, 1);

    const host = view.element.querySelector('.desktop-titlebar .conversation-toolbar-host');
    assert.ok(host, 'the actual native titlebar owns the shared host');
    assert.equal(view.element.querySelector('.session-workspace-header .conversation-toolbar-host'), null);
    assert.equal(view.element.querySelector('.session-workspace-header details'), null);
    assert.ok(view.element.querySelector('.session-workspace-shell.has-titlebar-toolbar'));
    const tools = host.querySelector('.chat-conversation-actions > details');
    const plugins = host.querySelector('.conversation-plugin-menu');
    const session = view.element.querySelector('.session-workspace-more');
    assert.ok(tools && plugins && session, 'all three real menu owners share the titlebar');
    assert.ok(host.contains(session));
    assert.equal(view.element.querySelectorAll('.chat-conversation-actions').length, 1);
    assert.equal(view.element.querySelectorAll('.conversation-plugin-menu').length, 1);
    assert.equal(view.element.querySelector('.session-workspace-thread .chat-conversation-actions'), null);
    assert.equal(view.element.querySelector('.session-workspace-thread .conversation-plugin-menu'), null);
    const triggers = [tools, plugins, session].map((details) => details.querySelector('summary'));
    assert.deepEqual(triggers.map((trigger) => trigger.getAttribute('aria-label')), [
      'Conversation tools', 'Plugins', 'More session actions',
    ]);
    assert.equal(new Set(triggers.map((trigger) => trigger.querySelector('svg').innerHTML)).size, 3,
      'Reader, Cube, and session dots have different icon silhouettes');
    assert.equal(plugins.open, true, 'plugin errors open their disclosure automatically');
    assert.equal(plugins.querySelector('[role="alert"]').textContent, 'Plugin unavailable');
    assert.equal(tools.open, false);
    for (const details of [tools, plugins, session]) {
      // Happy DOM requires native disclosure toggle state to be simulated.
      details.open = true;
      await act(async () => details.dispatchEvent(new window.Event('toggle')));
      const summary = details.querySelector('summary');
      await act(async () => summary.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
      await act(async () => new Promise((resolve) => window.requestAnimationFrame(resolve)));
      assert.equal(details.open, false);
      assert.equal(document.activeElement, summary, 'Escape restores this menu trigger');
      details.open = true;
      await act(async () => details.dispatchEvent(new window.Event('toggle')));
      await act(async () => document.body.dispatchEvent(new window.PointerEvent('pointerdown', { bubbles: true })));
      assert.equal(details.open, false, 'outside click closes this menu');
    }
  } finally {
    await view.close();
  }
});

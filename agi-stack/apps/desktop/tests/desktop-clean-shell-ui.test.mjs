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
  'HTMLInputElement',
  'HTMLTextAreaElement',
  'CustomEvent',
  'Event',
  'NodeFilter',
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
    contents: `
      export {DesktopSidebar} from './src/features/navigation/DesktopSidebar';
      export {DesktopStatusBar} from './src/features/chrome/DesktopStatusBar';
      export {DesktopTitlebar} from './src/features/chrome/DesktopTitlebar';
      export {WorkbenchTabBar} from './src/features/chrome/WorkbenchTabBar';
      export {I18nProvider} from './src/i18n';
      export {SessionWorkspace} from './src/features/session/SessionWorkspace';
    `,
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
  require,
  module,
  module.exports,
);
const { DesktopSidebar, DesktopStatusBar, DesktopTitlebar, WorkbenchTabBar, I18nProvider, SessionWorkspace } =
  module.exports;
const { Theme } = require('@radix-ui/themes');

async function mount(Component, props) {
  const element = document.createElement('div');
  document.body.append(element);
  const root = createRoot(element);
  const render = async (nextProps) => {
    await act(async () =>
      root.render(
        React.createElement(
          I18nProvider,
          null,
          React.createElement(Theme, null, React.createElement(Component, nextProps)),
        ),
      ),
    );
  };
  await render(props);
  return {
    element,
    render,
    async close() {
      await act(async () => root.unmount());
      element.remove();
    },
  };
}

const healthyStatus = {
  connection: 'ready',
  liveConnected: true,
  liveError: null,
  tenantName: 'Northstar',
  projectName: 'Desktop',
};

test('healthy connections take no status row; failures expose the recovery action', async () => {
  let recoveries = 0;
  const view = await mount(DesktopStatusBar, healthyStatus);
  try {
    assert.equal(view.element.querySelector('footer'), null);
    for (const state of [
      { connection: 'error', liveConnected: true, liveError: null },
      { connection: 'ready', liveConnected: false, liveError: 'Socket disconnected' },
    ]) {
      await view.render({
        ...healthyStatus,
        ...state,
        onOpenConnectionSettings() {
          recoveries += 1;
        },
      });
      const status = view.element.querySelector('[role="status"]');
      assert.ok(status);
      assert.equal(status.getAttribute('aria-live'), 'polite');
      if (state.liveError) assert.ok(status.textContent.includes(state.liveError));
      await act(async () => status.querySelector('button').click());
    }
    assert.equal(recoveries, 2);
    await view.render(healthyStatus);
    assert.equal(view.element.querySelector('footer'), null);
  } finally {
    await view.close();
  }
});

test('conversation tabs stay absent even with multiple conversations open', async () => {
  const first = { kind: 'view', section: 'home' };
  const second = {
    kind: 'conversation',
    conversationId: 'thread',
    projectId: 'project',
    workspaceId: 'workspace',
    title: 'Release review',
  };
  let activated, closed;
  const input = {
    tabs: [first],
    activeTabKey: 'view:home',
    onActivate(tab) {
      activated = tab;
    },
    onClose(tab) {
      closed = tab;
    },
  };
  const view = await mount(WorkbenchTabBar, input);
  try {
    assert.ok(view.element.querySelector('[role="tablist"]') === null, 'tab row stays hidden');
    const implicit = { kind: 'view', section: 'workspace' };
    await view.render({ ...input, tabs: [first, implicit] });
    assert.ok(view.element.querySelector('[role="tablist"]') === null, 'tab row stays hidden');
    await view.render({ ...input, tabs: [first, implicit, second] });
    assert.ok(view.element.querySelector('[role="tablist"]') === null, 'tab row stays hidden');
    const third = { ...second, conversationId: 'another-thread', title: 'Planning' };
    await view.render({ ...input, tabs: [first, second, third] });
    assert.equal(view.element.querySelector('[role="tablist"]'), null);
    assert.equal(activated, undefined);
    assert.equal(closed, undefined);
  } finally {
    await view.close();
  }
});

test('titlebar shows one context title and hides unavailable panel controls', async () => {
  let sidebarToggles = 0,
    panelToggles = 0;
  const input = {
    contextTitle: 'Release review',
    sidebarCollapsed: false,
    rightSidebarOpen: false,
    rightSidebarAvailable: false,
    onToggleSidebar() {
      sidebarToggles += 1;
    },
    onToggleRightSidebar() {
      panelToggles += 1;
    },
  };
  const view = await mount(DesktopTitlebar, input);
  try {
    assert.equal(
      view.element.querySelector('.desktop-titlebar-title').textContent,
      'Release review',
    );
    assert.equal(view.element.querySelectorAll('button').length, 1);
    await act(async () => view.element.querySelector('button').click());
    await view.render({ ...input, rightSidebarAvailable: true, rightSidebarOpen: true });
    const buttons = view.element.querySelectorAll('button');
    assert.equal(buttons.length, 2);
    assert.equal(buttons[1].getAttribute('aria-pressed'), 'true');
    await act(async () => buttons[1].click());
    assert.equal(sidebarToggles, 1);
    assert.equal(panelToggles, 1);
  } finally {
    await view.close();
  }
});

test('simplified sidebar preserves create, search, functions, account, settings and workspace actions', async () => {
  const events = [];
  const input = {
    activeSection: 'home',
    taskCount: 10,
    activityUnreadCount: 8,
    tenantName: 'Northstar',
    projectName: 'Desktop',
    user: { name: 'Alex', email: 'alex@example.test' },
    workspaces: [],
    conversationsByWorkspace: {},
    nodeState: { projects: { project: { loading: false, error: null } }, workspaces: {} },
    currentProjectId: 'project',
    currentWorkspaceId: '',
    currentConversationId: null,
    workspaceTreeSelectionMode: 'none',
    expandedWorkspaceIds: new Set(),
    newTaskDisabledReason: null,
    onNavigate(value) {
      events.push(value);
    },
    onNewTask() {
      events.push('create');
    },
    onOpenSearch() {
      events.push('search');
    },
    onOpenFeatureDirectory(trigger) {
      assert.ok(trigger instanceof HTMLElement);
      events.push('functions');
    },
    onCreateWorkspace() {
      events.push('createWorkspace');
    },
    onOpenAccountSettings() {
      events.push('settings');
    },
    onSwitchWorkspace() {
      events.push('switchWorkspace');
    },
    onSignOut() {
      events.push('signOut');
    },
    onToggleWorkspace() {},
    onRetryProject() {},
    onRetryWorkspace() {},
    onSelectWorkspace() {},
    onSelectConversation() {},
  };
  const view = await mount(DesktopSidebar, input);
  try {
    const click = async (selector) => {
      const button = view.element.querySelector(selector);
      assert.ok(button, selector);
      await act(async () => button.click());
    };
    await click('.desktop-design-brand');
    await click('.desktop-design-new-task');
    await click('.desktop-design-primary-nav button');
    await click('.desktop-design-feature-button');
    await click('.desktop-workspace-heading-actions button');
    for (const label of ['Account settings', 'Switch workspace', 'Sign out']) {
      await click('.desktop-design-profile');
      const item = [...view.element.querySelectorAll('[role="menuitem"]')].find(
        (node) => node.textContent.trim() === label,
      );
      assert.ok(item, label);
      await act(async () => item.click());
      assert.equal(view.element.querySelector('[role="menu"]'), null);
    }
    assert.deepEqual(events, [
      'home',
      'create',
      'search',
      'functions',
      'createWorkspace',
      'settings',
      'switchWorkspace',
      'signOut',
    ]);
    await click('.desktop-design-profile');
    await act(async () =>
      document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })),
    );
    assert.equal(view.element.querySelector('[role="menu"]'), null);
    assert.equal(document.activeElement, view.element.querySelector('.desktop-design-profile'));
  } finally {
    await view.close();
  }
});


test('session chrome keeps recovery and approval actionable while details stay behind the more menu', async () => {
  window.localStorage.setItem('agistack.desktop.locale', 'en');
  const actions = [];
  const viewModel = {
    id: 'session-clean', title: 'A unique conversation title', summary: null,
    workspaceLabel: 'Research workspace', status: 'running',
    executionAuthorityKind: 'desktop_run', capabilityMode: 'work', executionMode: 'build',
    stage: 'implement', conversationMode: null, participantCount: 7, linkedTaskId: null,
    modelLabel: 'Test model', environmentLabel: 'Local environment', branchLabel: 'main',
    elapsedLabel: '2m', runRevision: 3, runActions: [], error: null,
  };
  const props = {
    viewModel, thread: React.createElement('p', null, 'Conversation body'),
    runActionPending: null, liveConnected: true, liveError: null,
    onRunAction: (action) => actions.push(action), onOpenCanvas: () => {},
  };
  const view = await mount(SessionWorkspace, props);
  try {
    assert.equal(view.element.querySelector('h1'), null);
    assert.equal(view.element.querySelector('.session-pane-label'), null);
    assert.equal(view.element.querySelector('.session-workspace-status-banner'), null);
    assert.equal(view.element.querySelector('.session-workspace-status'), null);
    assert.ok(!view.element.textContent.includes(viewModel.title));
    assert.ok(!view.element.textContent.includes('Session log'));
    const more = view.element.querySelector('details.session-workspace-more');
    const details = more.querySelector('details.session-workspace-details');
    assert.equal(more.open, false);
    assert.equal(details.open, false);
    assert.ok(more.querySelector('summary[aria-label="More session actions"]'));
    await act(async () => {
      // Happy DOM does not implement summary's native toggle default action.
      more.open = true;
      more.dispatchEvent(new window.Event('toggle'));
      details.open = true;
    });
    assert.equal(more.open, true);
    assert.equal(details.open, true);
    assert.ok(details.textContent.includes('Test model'));
    assert.ok(details.textContent.includes('Research workspace'));
    await act(async () => more.querySelector('summary').dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
    assert.equal(more.open, false);

    await view.render({ ...props, liveConnected: false, liveError: 'Reconnect required',
      viewModel: { ...viewModel, status: 'disconnected', runActions: ['reconnect'] } });
    const recovery = [...view.element.querySelectorAll('button')].find((button) => button.textContent.includes('Reattach'));
    assert.ok(recovery && !recovery.disabled);
    assert.equal(recovery.closest('details'), null);
    assert.ok(view.element.querySelector('.session-connection-warning').textContent.includes('Reconnect required'));
    await act(async () => recovery.click());
    assert.deepEqual(actions, ['reconnect']);

    await view.render({ ...props, viewModel: { ...viewModel, status: 'ready_review', runActions: ['approve', 'request_changes'] } });
    const approval = [...view.element.querySelectorAll('button')].find((button) => button.textContent.includes('Approve run'));
    assert.ok(approval && !approval.disabled);
    assert.equal(approval.closest('details'), null);
    await act(async () => approval.click());
    assert.deepEqual(actions, ['reconnect', 'approve']);
  } finally {
    await view.close();
  }
});

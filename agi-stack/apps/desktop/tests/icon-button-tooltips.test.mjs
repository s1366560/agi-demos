import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const { ToastProvider, ToastViewport } = require(
  '/tmp/agistack-desktop-test-dist/src/features/feedback/ToastCenter.js',
);

const readSource = (path) =>
  readFileSync(new URL(`../src/${path}`, import.meta.url), 'utf8');

// Escapes regex metacharacters, then makes whitespace runs flexible so
// multi-line JSX expressions match regardless of indentation.
const flex = (text) =>
  text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+');

// Source contract: an icon-only button must expose the SAME localized
// expression as both aria-label (screen readers) and title (hover tooltip),
// with the title placed immediately after the aria-label.
const assertTitleMirrorsAriaLabel = (source, ariaExpression, label) => {
  const pair = new RegExp(
    `aria-label=\\{\\s*${flex(ariaExpression)}\\s*\\}\\s*title=\\{\\s*${flex(ariaExpression)}\\s*\\}`,
  );
  assert.match(source, pair, label);
};

const workspaceDockSource = readSource('features/workspace/WorkspaceDock.tsx');
const chatTimelineSource = readSource('features/chat/ChatTimeline.tsx');
const desktopSearchSource = readSource('features/search/DesktopSearch.tsx');
const composerControlsSource = readSource('features/chat/ComposerControls.tsx');
const toastCenterSource = readSource('features/feedback/ToastCenter.tsx');
const keyboardShortcutsDialogSource = readSource(
  'features/navigation/KeyboardShortcutsDialog.tsx',
);
const sessionAgentsCanvasSource = readSource('features/session/SessionAgentsCanvas.tsx');
const sessionExecutionGraphCanvasSource = readSource(
  'features/session/SessionExecutionGraphCanvas.tsx',
);
const loginScreenSource = readSource('features/auth/LoginScreen.tsx');
const promptTemplateLibrarySource = readSource('features/chat/PromptTemplateLibrary.tsx');
const newThreadComposerSource = readSource('features/task/NewThreadComposer.tsx');
const newTaskFlowSource = readSource('features/task/NewTaskFlow.tsx');
const newTaskFlowStagesSource = readSource('features/task/NewTaskFlowStages.tsx');
const settingsWindowSource = readSource('features/settings/SettingsWindow.tsx');
const modelProviderWorkspaceSource = readSource('features/settings/ModelProviderWorkspace.tsx');
const providerConnectionPanelSource = readSource(
  'features/settings/ProviderConnectionPanel.tsx',
);
const channelConnectionsDialogSource = readSource(
  'features/settings/ChannelConnectionsDialog.tsx',
);
const i18nSource = readSource('i18n.tsx');

test('workspace tree expand/collapse toggles expose localized tooltips', () => {
  assertTitleMirrorsAriaLabel(
    workspaceDockSource,
    "unboundTasksExpanded ? t('workspaceTree.collapse', { name: t('workspaceTree.tasks') }) : t('workspaceTree.expand', { name: t('workspaceTree.tasks') })",
    'unbound tasks toggle',
  );
  assertTitleMirrorsAriaLabel(
    workspaceDockSource,
    "workspaceExpanded ? t('workspaceTree.collapse', { name: workspaceLabel(workspace) }) : t('workspaceTree.expand', { name: workspaceLabel(workspace) })",
    'workspace toggle',
  );
});

test('chat timeline row toggles expose localized tooltips', () => {
  assertTitleMirrorsAriaLabel(
    chatTimelineSource,
    "t(expanded ? 'chat.collapseItem' : 'chat.expandItem', { item: title })",
    'tool-call pair toggle',
  );
  assertTitleMirrorsAriaLabel(
    chatTimelineSource,
    "t(expanded ? 'chat.collapseItem' : 'chat.expandItem', { item: timelineTitle(item, t), })",
    'timeline item toggle',
  );
});

test('search view switcher icon buttons expose localized tooltips', () => {
  assertTitleMirrorsAriaLabel(desktopSearchSource, "t('search.view.grid')", 'grid view');
  assertTitleMirrorsAriaLabel(desktopSearchSource, "t('search.view.list')", 'list view');
});

test('composer add-files button keeps its tooltip identical to the aria label', () => {
  assert.match(
    composerControlsSource,
    /aria-label=\{t\('composer\.addFiles'\)\}\s*title=\{t\('composer\.addFiles'\)\}/,
  );
});

test('composer toolbar landmark is localized', () => {
  assert.match(composerControlsSource, /aria-label=\{t\('composer\.toolsLabel'\)\}/);
});

test('toast dismiss button exposes a localized tooltip', () => {
  assertTitleMirrorsAriaLabel(toastCenterSource, "t('toast.dismiss')", 'toast dismiss');
});

test('keyboard shortcuts dialog close button exposes a localized tooltip', () => {
  assertTitleMirrorsAriaLabel(
    keyboardShortcutsDialogSource,
    "t('common.close')",
    'shortcuts dialog close',
  );
});

test('session agent tree child toggle exposes a localized tooltip', () => {
  assertTitleMirrorsAriaLabel(
    sessionAgentsCanvasSource,
    "t(expanded ? 'session.agents.collapseChildren' : 'session.agents.expandChildren', { agent: label, })",
    'agent tree toggle',
  );
});

test('execution graph open-session icon button exposes a localized tooltip', () => {
  assertTitleMirrorsAriaLabel(
    sessionExecutionGraphCanvasSource,
    "t('session.graph.openSessionFor', { node: node.label })",
    'graph open session',
  );
});

test('login screen icon buttons expose localized tooltips', () => {
  assertTitleMirrorsAriaLabel(
    loginScreenSource,
    "t(showPassword ? 'login.hidePassword' : 'login.showPassword')",
    'password visibility toggle',
  );
  assertTitleMirrorsAriaLabel(loginScreenSource, "t('login.deviceCancel')", 'device cancel');
});

test('prompt template delete button exposes a localized tooltip', () => {
  assertTitleMirrorsAriaLabel(
    promptTemplateLibrarySource,
    "t('chat.templates.deleteTemplate', { title: template.title, })",
    'template delete',
  );
});

test('new thread composer send button exposes a localized tooltip', () => {
  assertTitleMirrorsAriaLabel(newThreadComposerSource, "t('task.startThread')", 'start thread');
});

test('new task flow close button exposes a localized tooltip', () => {
  assert.match(
    newTaskFlowSource,
    /aria-label=\{t\('task\.close'\)\} title=\{t\('task\.close'\)\}/,
  );
});

test('plan step toggle and edit buttons expose localized tooltips', () => {
  assertTitleMirrorsAriaLabel(
    newTaskFlowStagesSource,
    "t(step.enabled ? 'task.disableStep' : 'task.enableStep', { step: step.content, })",
    'step enable toggle',
  );
  assertTitleMirrorsAriaLabel(
    newTaskFlowStagesSource,
    "t('task.editStep', { step: step.content })",
    'step edit',
  );
});

test('settings window close button exposes a localized tooltip', () => {
  assert.match(
    settingsWindowSource,
    /aria-label=\{t\('settings\.close'\)\} title=\{t\('settings\.close'\)\}/,
  );
});

test('provider workspace icon buttons expose localized tooltips', () => {
  assertTitleMirrorsAriaLabel(
    modelProviderWorkspaceSource,
    "t('providers.addProvider')",
    'add provider',
  );
  assertTitleMirrorsAriaLabel(
    modelProviderWorkspaceSource,
    "t('providers.copyProviderId')",
    'copy provider id',
  );
});

test('provider secret visibility toggle exposes a localized tooltip', () => {
  assertTitleMirrorsAriaLabel(
    providerConnectionPanelSource,
    "t(showSecret ? 'providers.hideSecret' : 'providers.showSecret')",
    'secret visibility toggle',
  );
});

test('channel edit and delete icon buttons expose localized tooltips', () => {
  assertTitleMirrorsAriaLabel(
    channelConnectionsDialogSource,
    "t('settings.channels.editNamed', { name: channel.name })",
    'channel edit',
  );
  assertTitleMirrorsAriaLabel(
    channelConnectionsDialogSource,
    "t('settings.channels.deleteNamed', { name: channel.name })",
    'channel delete',
  );
});

test('tooltip copy keys exist in both i18n dictionaries', () => {
  for (const key of [
    'workspaceTree.collapse',
    'workspaceTree.expand',
    'workspaceTree.tasks',
    'chat.collapseItem',
    'chat.expandItem',
    'search.view.grid',
    'search.view.list',
    'toast.dismiss',
    'common.close',
    'session.agents.collapseChildren',
    'session.agents.expandChildren',
    'session.graph.openSessionFor',
    'login.hidePassword',
    'login.showPassword',
    'login.deviceCancel',
    'chat.templates.deleteTemplate',
    'task.startThread',
    'task.close',
    'task.disableStep',
    'task.enableStep',
    'task.editStep',
    'settings.close',
    'providers.addProvider',
    'providers.copyProviderId',
    'providers.hideSecret',
    'providers.showSecret',
    'settings.channels.editNamed',
    'settings.channels.deleteNamed',
  ]) {
    assert.equal(
      (i18nSource.match(new RegExp(`'${key.replaceAll('.', '\\.')}'`, 'g')) ?? []).length,
      2,
      key,
    );
  }
});

function withStoredLocale(locale, render) {
  const previousWindow = globalThis.window;
  globalThis.window = {
    localStorage: {
      getItem: (key) => (key === 'agistack.desktop.locale' ? locale : null),
      setItem: () => {},
    },
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  try {
    return render();
  } finally {
    if (previousWindow === undefined) {
      delete globalThis.window;
    } else {
      globalThis.window = previousWindow;
    }
  }
}

function renderToastViewport() {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(
        ToastProvider,
        null,
        React.createElement(ToastViewport, {
          toasts: [{ id: 'toast-1', kind: 'success', message: 'Saved' }],
          onDismiss: () => {},
        }),
      ),
    ),
  );
}

test('toast dismiss button renders its localized tooltip in markup', () => {
  const markup = withStoredLocale('en', renderToastViewport);
  assert.match(markup, /aria-label="Dismiss notification"/);
  assert.match(markup, /title="Dismiss notification"/);
});

test('toast dismiss button renders a zh-CN tooltip when the locale is stored', () => {
  const markup = withStoredLocale('zh-CN', renderToastViewport);
  assert.match(markup, /aria-label="关闭通知"/);
  assert.match(markup, /title="关闭通知"/);
});

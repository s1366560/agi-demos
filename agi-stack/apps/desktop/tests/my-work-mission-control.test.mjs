import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { I18nProvider } = require('/tmp/agistack-desktop-test-dist/src/i18n.js');
const { MyWorkQueue } = require(
  '/tmp/agistack-desktop-test-dist/src/features/my-work/MyWorkQueue.js'
);
const appSource = require('node:fs').readFileSync(
  new URL('../src/App.tsx', import.meta.url),
  'utf8',
);

const baseItem = {
  authority_kind: 'desktop_run',
  authority_id: 'run-1',
  id: 'run-1',
  run_id: 'run-1',
  conversation_id: 'conversation-1',
  workspace_id: 'workspace-1',
  project_id: 'project-1',
  title: 'Run one',
  capability_mode: 'work',
  group: 'running',
  status: 'running',
  required_action: 'observe',
  revision: 4,
  permission_profile: 'workspace_write',
  attempt_number: null,
  environment: { id: 'environment-1', kind: 'cloud', label: 'Cloud workspace' },
  error: null,
  created_at: '2026-07-13T00:00:00Z',
  updated_at: '2026-07-13T00:05:00Z',
  last_heartbeat_at: '2026-07-13T00:05:00Z',
};

const items = [
  {
    ...baseItem,
    authority_id: 'run-input',
    id: 'run-input',
    run_id: 'run-input',
    title: 'Input request',
    group: 'needs_input',
    status: 'needs_input',
    required_action: 'provide_input',
  },
  {
    ...baseItem,
    authority_id: 'run-approval',
    id: 'run-approval',
    run_id: 'run-approval',
    title: 'Approval request',
    group: 'needs_approval',
    status: 'needs_approval',
    required_action: 'review_approval',
  },
  baseItem,
  {
    ...baseItem,
    authority_id: 'run-ready',
    id: 'run-ready',
    run_id: 'run-ready',
    title: 'Review result',
    group: 'ready_review',
    status: 'ready_review',
    required_action: 'review_result',
  },
];

function renderMyWork(overrides = {}) {
  return renderToStaticMarkup(
    React.createElement(
      I18nProvider,
      null,
      React.createElement(MyWorkQueue, {
        items,
        error: null,
        loading: false,
        mode: 'work',
        projectName: 'Project One',
        workspaceLabels: { 'workspace-1': 'Workspace One' },
        onRefresh: () => {},
        onOpenSession: () => {},
        ...overrides,
      }),
    ),
  );
}

test('My Work renders the source Mission Control queue anatomy', () => {
  const markup = renderMyWork();

  assert.match(markup, /MISSION CONTROL/);
  assert.match(markup, /<kbd>(?:⌘ K|Ctrl K)<\/kbd>/);
  assert.match(markup, />All<\/button>/);
  assert.match(markup, />Assigned to me<\/button>/);
  assert.match(markup, />Recent<\/button>/);
  assert.equal((markup.match(/class="my-work-group-heading"/g) ?? []).length, 3);
  assert.match(markup, /Needs input/);
  assert.match(markup, /class="my-work-task-menu"/);
  assert.match(markup, /class="my-work-inline-action"/);
});

test('My Work replaces the authority inspector with a task canvas hierarchy', () => {
  const markup = renderMyWork();

  assert.match(markup, /class="my-work-progress-strip"/);
  assert.match(markup, /Stage data unavailable/);
  assert.doesNotMatch(markup, />Understand<|>Analyze<|>Draft<|>Review</);
  assert.match(markup, /class="my-work-insight-grid"/);
  assert.match(markup, /class="my-work-artifact-panel"/);
  assert.match(markup, /class="my-work-action-dock"/);
  assert.match(markup, /class="my-work-steer-composer"/);
  assert.match(markup, /Task updated/);
  assert.equal((markup.match(/>Open session<\/button>/g) ?? []).length, 2);
  assert.doesNotMatch(markup, /<textarea/);
  assert.doesNotMatch(markup, /Authority ID|Current authority|Persisted record only/);
});

test('My Work loading and error states never render a stale task canvas', () => {
  const loadingMarkup = renderMyWork({ items: [], loading: true });
  const refreshingMarkup = renderMyWork({ loading: true });
  const errorMarkup = renderMyWork({ items: [], error: 'Not found' });

  assert.doesNotMatch(loadingMarkup, /class="my-work-detail"/);
  assert.match(refreshingMarkup, /class="my-work-refreshing"/);
  assert.match(refreshingMarkup, /Updating current work/);
  assert.match(refreshingMarkup, /class="my-work-action-dock"[^]*?<button type="button" class="primary" disabled=""/);
  assert.doesNotMatch(errorMarkup, /class="my-work-detail"/);
  assert.match(errorMarkup, /role="alert"/);
});

test('My Work exposes unavailable filters to assistive technology and distinguishes Code mode', () => {
  const markup = renderMyWork({
    mode: 'code',
    items: items.map((item) => ({ ...item, capability_mode: 'code' })),
  });

  assert.match(markup, /CODE SESSIONS/);
  assert.match(markup, /role="group"/);
  assert.match(markup, /aria-describedby="my-work-filter-unavailable"/);
  assert.match(markup, /id="my-work-filter-unavailable"/);
});

test('My Work search owns Command-K while the global palette remains the fallback', () => {
  const keyboardHandler =
    appSource.match(/const handleKeyDown = \(event: KeyboardEvent\) => \{[\s\S]*?\n    \};/)?.[0] ?? '';

  assert.match(keyboardHandler, /activeSectionRef\.current === 'board'/);
  assert.match(keyboardHandler, /input\[name="my-work-search"\]/);
  assert.ok(keyboardHandler.indexOf('search.focus()') < keyboardHandler.indexOf('openCommandPalette()'));
});

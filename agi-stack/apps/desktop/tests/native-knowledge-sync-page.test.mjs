import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { cloudContext, pullContext, record, status } from './nativeKnowledgeFixtures.mjs';
const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const root = '/tmp/agistack-desktop-test-dist/src';
const { I18nProvider } = require(`${root}/i18n.js`);
const { NativeKnowledgeSyncPanel } = require(
  `${root}/features/project-knowledge/NativeKnowledgeSyncPanel.js`,
);
const { NativeKnowledgeConflictEditor } = require(
  `${root}/features/project-knowledge/NativeKnowledgeConflictEditor.js`,
);
const h = React.createElement;
const render = (element) => renderToStaticMarkup(h(I18nProvider, null, element));
const noop = () => {};
const syncController = { refresh: noop, sync: noop, moreOutbox: noop, morePending: noop };
const conflictController = {
  open: noop,
  choose: noop,
  setDraft: noop,
  submit: noop,
  retry: noop,
  reload: noop,
  close: noop,
  decisions: () => ['use_local', 'use_remote', 'keep_both', 'merged'],
};
const syncModel = {
  phase: 'ready',
  allowedActions: ['sync_status', 'sync_push', 'sync_pull'],
  status,
  outbox: null,
  pending: null,
  pullConflicts: [],
  pushConflicts: [],
  resolutions: [],
  error: null,
  result: null,
  recoveryRequired: false,
  outboxHasMore: false,
};
const conflictModel = {
  phase: 'reviewing',
  allowedActions: ['pull_conflict_context', 'resolve_pull'],
  selection: { kind: 'pull', id: 'memory-1' },
  context: pullContext,
  record: null,
  decision: null,
  draft: null,
  error: null,
  pendingReconciliation: false,
};
const syncPage = (model, extra = {}) =>
  render(
    h(NativeKnowledgeSyncPanel, {
      model,
      controller: syncController,
      conflicts: conflictController,
      ...extra,
    }),
  );
const conflictPage = (model, extra = {}) =>
  render(h(NativeKnowledgeConflictEditor, { model, controller: conflictController, ...extra }));

test('sync UI labels configured links as unverified and never offers an arbitrary remote link form', () => {
  const html = syncPage(syncModel);
  assert.match(html, /Association configured\. Remote authorization is unverified/);
  assert.match(html, /remote-actor/);
  assert.match(html, /Pull one page/);
  assert.match(html, /Push one change/);
  assert.doesNotMatch(html, /<input|<select/);
  const unlinked = syncPage({ ...syncModel, status: { ...status, link: null } });
  assert.match(unlinked, /Remote project selection is not available yet/);
  assert.match(unlinked, /disabled="">Pull one page/);
});

test('sync UI checks exact operation declarations, recovery locks writes but exposes refresh', () => {
  assert.equal(syncPage({ ...syncModel, allowedActions: ['view', 'update'] }), '');
  const readOnly = syncPage({ ...syncModel, allowedActions: ['sync_status'] });
  assert.doesNotMatch(readOnly, /Pull one page|Push one change/);
  const uncertain = syncPage({
    ...syncModel,
    phase: 'error',
    recoveryRequired: true,
    error: 'failed',
  });
  assert.match(uncertain, /synchronization result is unknown/);
  assert.match(uncertain, /disabled="">Push one change/);
  assert.match(uncertain, /<button type="button">Refresh<\/button>/);
  assert.doesNotMatch(uncertain, /Retry the same request/);
  assert.match(syncPage(syncModel, { disabled: true }), /<fieldset[^>]*disabled=""/);
});

test('conflict editor displays full comparison and original proposal instead of calling it current local', () => {
  const html = conflictPage(
    { ...conflictModel, selection: { kind: 'push', localSequence: 1 }, context: cloudContext },
    {
      controller: {
        ...conflictController,
        decisions: () => ['keep_current', 'use_proposed', 'merged'],
      },
    },
  );
  for (const text of [
    'Current local version',
    'Shared baseline',
    'Current remote version',
    'Original push proposal',
    'Submit original proposal',
  ])
    assert.ok(html.includes(text));
  assert.match(html, /current local version may have changed/);
  assert.doesNotMatch(html, /Keep both versions/);
  assert.match(html, /Full version and metadata/);
  assert.match(
    conflictPage({
      ...conflictModel,
      context: {
        ...pullContext,
        local_deleted: true,
        remote: { ...pullContext.remote, deleted: true },
      },
    }),
    /Deleted version/,
  );
});

test('unknown resolution retains read-only merged content and only the same-request retry can write', () => {
  const html = conflictPage({
    ...conflictModel,
    phase: 'uncertain',
    error: 'uncertain',
    decision: 'merged',
    draft: { ...pullContext.remote.content, content: 'pending merge' },
  });
  assert.match(html, /readOnly=""[^>]*>pending merge/);
  assert.match(html, /Retry the same request/);
  assert.doesNotMatch(html, /Confirm this decision/);
  assert.match(html, /disabled="">Close/);
  assert.match(
    conflictPage({ ...conflictModel, phase: 'accepted', pendingReconciliation: true }),
    /local reconciliation is still pending/,
  );
});

test('saved resolution state distinguishes resumable, rejected, and already reconciled records', () => {
  const base = {
    ...conflictModel,
    selection: { kind: 'resolution', id: record.resolution_id },
    context: null,
    allowedActions: ['resolution', 'resume_resolution'],
  };
  assert.match(
    conflictPage({ ...base, record: { ...record, receipt: null } }),
    /Resume saved resolution/,
  );
  assert.doesNotMatch(
    conflictPage({
      ...base,
      record: { ...record, receipt: null, rejection: { reason: 'rejected' } },
    }),
    /Resume saved resolution/,
  );
  assert.doesNotMatch(
    conflictPage({ ...base, record: { ...record, reconciliation: { local_revision: 2 } } }),
    /Resume saved resolution/,
  );
});

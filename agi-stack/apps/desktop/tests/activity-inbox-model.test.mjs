import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  ACTIVITY_CATEGORIES,
  activityCategoryForItem,
  activityEntryForItem,
  buildActivityInboxEntries,
  groupActivityEntries,
} = require('/tmp/agistack-desktop-test-dist/src/features/activity/activityInboxModel.js');
const {
  ACTIVITY_READ_STATE_STORAGE_PREFIX,
  activityEntryIsRead,
  countUnreadActivityEntries,
  createLocalStorageReadStateStore,
  markActivityConversationRead,
  markActivityEntriesRead,
  markActivityEntryRead,
} = require('/tmp/agistack-desktop-test-dist/src/features/activity/activityReadState.js');

const baseItem = {
  authority_kind: 'desktop_run',
  authority_id: 'run-1',
  conversation_id: 'conversation-1',
  project_id: 'project-1',
  workspace_id: 'workspace-1',
  title: 'Review release evidence',
  capability_mode: 'code',
  group: 'ready_review',
  status: 'ready_review',
  required_action: 'review_result',
  summary: null,
  created_at: '2026-07-13T01:00:00Z',
  updated_at: '2026-07-13T04:00:00Z',
};

const items = [
  baseItem,
  {
    ...baseItem,
    authority_kind: 'hitl_request',
    authority_id: 'hitl-1',
    conversation_id: 'conversation-2',
    title: 'Clarify research scope',
    group: 'needs_input',
    status: 'needs_input',
    required_action: 'provide_input',
    summary: 'Agent asked a question',
    updated_at: '2026-07-13T05:00:00Z',
  },
  {
    ...baseItem,
    authority_id: 'run-2',
    conversation_id: 'conversation-3',
    title: 'Publish workspace package',
    group: 'running',
    status: 'failed',
    required_action: 'inspect_failure',
    updated_at: '2026-07-13T03:00:00Z',
  },
  {
    ...baseItem,
    authority_id: 'run-3',
    conversation_id: 'conversation-4',
    title: 'Watch long-running sync',
    group: 'running',
    status: 'running',
    required_action: 'observe',
    updated_at: '2026-07-13T06:00:00Z',
  },
];

test('Activity inbox derives categories from structured authority facts only', () => {
  assert.equal(
    activityCategoryForItem({ group: 'needs_input', status: 'needs_input', required_action: 'provide_input' }),
    'needs_input',
  );
  assert.equal(
    activityCategoryForItem({ group: 'needs_approval', status: 'needs_approval', required_action: 'review_approval' }),
    'needs_input',
  );
  assert.equal(
    activityCategoryForItem({ group: 'ready_review', status: 'ready_review', required_action: 'review_result' }),
    'ready_for_review',
  );
  for (const status of ['failed', 'cancelled', 'interrupted', 'disconnected']) {
    assert.equal(
      activityCategoryForItem({ group: 'running', status, required_action: 'observe' }),
      'attention',
      status,
    );
  }
  assert.equal(
    activityCategoryForItem({ group: 'running', status: 'running', required_action: 'inspect_failure' }),
    'attention',
  );
  assert.equal(
    activityCategoryForItem({ group: 'running', status: 'running', required_action: 'observe' }),
    null,
  );
});

test('Activity inbox entries reuse the My Work authority identity and sort by recency', () => {
  const entries = buildActivityInboxEntries(items);
  assert.deepEqual(
    entries.map((entry) => entry.id),
    ['hitl_request:hitl-1', 'desktop_run:run-1', 'desktop_run:run-2'],
  );
  assert.deepEqual(
    entries.map((entry) => entry.category),
    ['needs_input', 'ready_for_review', 'attention'],
  );
  assert.equal(entries[0].conversationId, 'conversation-2');
  assert.equal(entries[0].subtitle, 'Agent asked a question');
  assert.equal(entries[1].subtitle, null);
});

test('Activity inbox never infers categories from narrative titles', () => {
  const decoys = [
    { ...baseItem, authority_id: 'decoy-1', title: 'Failed while running', group: 'ready_review', status: 'ready_review' },
    { ...baseItem, authority_id: 'decoy-2', title: 'Ready for review now', group: 'running', status: 'running' },
  ];
  assert.deepEqual(
    buildActivityInboxEntries(decoys).map((entry) => entry.id),
    ['desktop_run:decoy-1'],
  );
});

test('Activity inbox groups keep a fixed category order including empty groups', () => {
  assert.deepEqual(ACTIVITY_CATEGORIES, ['needs_input', 'ready_for_review', 'attention']);
  const groups = groupActivityEntries(buildActivityInboxEntries(items));
  assert.deepEqual(
    groups.map(({ category, entries }) => ({ category, ids: entries.map((entry) => entry.id) })),
    [
      { category: 'needs_input', ids: ['hitl_request:hitl-1'] },
      { category: 'ready_for_review', ids: ['desktop_run:run-1'] },
      { category: 'attention', ids: ['desktop_run:run-2'] },
    ],
  );
});

test('Activity inbox entry tolerates an unparseable timestamp', () => {
  const entry = activityEntryForItem({
    ...baseItem,
    created_at: 'not-a-date',
    updated_at: '',
  });
  assert.equal(entry.timestampMs, 0);
});

test('Unread state is derived from read markers older than the entry timestamp', () => {
  const entries = buildActivityInboxEntries(items);
  const entry = entries[0];
  const entryMs = entry.timestampMs;

  assert.equal(activityEntryIsRead(entry, {}), false);
  assert.equal(countUnreadActivityEntries(entries, {}), 3);

  const read = markActivityEntryRead({}, entry.id, entryMs);
  assert.equal(activityEntryIsRead(entry, read), true);
  assert.equal(countUnreadActivityEntries(entries, read), 2);

  // 条目在已读之后有新进展(更新时间变晚)时重新变为未读。
  const progressed = { ...entry, timestampMs: entryMs + 60_000 };
  assert.equal(activityEntryIsRead(progressed, read), false);
});

test('Marking a conversation read only touches that conversation entries', () => {
  const entries = buildActivityInboxEntries(items);
  const now = Date.parse('2026-07-13T07:00:00Z');
  const next = markActivityConversationRead({}, entries, 'conversation-1', now);
  assert.deepEqual(next, { 'desktop_run:run-1': now });

  const unchanged = markActivityConversationRead(next, entries, 'conversation-unknown', now);
  assert.equal(unchanged, next);
});

test('Marking all read is a no-op when there are no entries', () => {
  const state = { 'desktop_run:run-1': 1 };
  assert.equal(markActivityEntriesRead(state, [], 2), state);
  const next = markActivityEntriesRead(state, [{ id: 'a' }, { id: 'b' }], 2);
  assert.deepEqual(next, { 'desktop_run:run-1': 1, a: 2, b: 2 });
});

function createMemoryStorage() {
  const map = new Map();
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
  };
}

test('localStorage read-state store round-trips and isolates scopes', () => {
  const storage = createMemoryStorage();
  const store = createLocalStorageReadStateStore(storage);
  const state = { 'desktop_run:run-1': 42 };

  store.save('tenant-1:project-1', state);
  assert.deepEqual(store.load('tenant-1:project-1'), state);
  assert.deepEqual(store.load('tenant-2:project-1'), {});
  assert.equal(
    storage.getItem(`${ACTIVITY_READ_STATE_STORAGE_PREFIX}:tenant-1:project-1`),
    JSON.stringify(state),
  );
});

test('localStorage read-state store fails closed on corrupt payloads', () => {
  const storage = createMemoryStorage();
  const store = createLocalStorageReadStateStore(storage);

  storage.setItem(`${ACTIVITY_READ_STATE_STORAGE_PREFIX}:scope`, '{not json');
  assert.deepEqual(store.load('scope'), {});

  storage.setItem(`${ACTIVITY_READ_STATE_STORAGE_PREFIX}:scope`, JSON.stringify(['array']));
  assert.deepEqual(store.load('scope'), {});

  storage.setItem(
    `${ACTIVITY_READ_STATE_STORAGE_PREFIX}:scope`,
    JSON.stringify({ valid: 7, bogus: 'x', nan: Number.NaN }),
  );
  assert.deepEqual(store.load('scope'), { valid: 7 });
});

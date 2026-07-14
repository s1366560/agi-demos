import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  countMyWorkGroups,
  filterMyWorkItems,
  myWorkConversationMatchesScope,
  socketEventInvalidatesMyWork,
} = require('/tmp/agistack-desktop-test-dist/src/features/my-work/myWorkModel.js');

const items = [
  {
    id: 'approval',
    title: 'Approve release boundary',
    group: 'needs_approval',
    capability_mode: 'code',
    updated_at: '2026-07-13T02:00:00Z',
    created_at: '2026-07-13T01:00:00Z',
  },
  {
    id: 'input',
    title: 'Clarify research scope',
    group: 'needs_input',
    capability_mode: 'work',
    updated_at: '2026-07-13T03:00:00Z',
    created_at: '2026-07-13T01:00:00Z',
  },
  {
    id: 'review',
    title: 'Review release evidence',
    group: 'ready_review',
    capability_mode: 'code',
    updated_at: '2026-07-13T04:00:00Z',
    created_at: '2026-07-13T01:00:00Z',
  },
];

test('My Work filters only explicit backend groups and capability modes', () => {
  assert.deepEqual(
    filterMyWorkItems(items, 'all', 'code').map((item) => item.id),
    ['review', 'approval']
  );
  assert.deepEqual(
    filterMyWorkItems(items, 'needs_input', 'all').map((item) => item.id),
    ['input']
  );
});

test('My Work search is a case-insensitive title filter inside the selected mode', () => {
  assert.deepEqual(
    filterMyWorkItems(items, 'all', 'code', 'RELEASE').map((item) => item.id),
    ['review', 'approval']
  );
  assert.deepEqual(
    filterMyWorkItems(items, 'all', 'work', 'release').map((item) => item.id),
    []
  );
});

test('My Work counts preserve the four authoritative attention groups', () => {
  assert.deepEqual(countMyWorkGroups(items), {
    needs_input: 1,
    needs_approval: 1,
    running: 0,
    ready_review: 1,
  });
});

test('My Work refreshes only for structured run, HITL, and review state events', () => {
  assert.equal(
    socketEventInvalidatesMyWork({ type: 'event', payload: { event_type: 'run_status' } }),
    true
  );
  assert.equal(socketEventInvalidatesMyWork({ event_type: 'permission_asked' }), true);
  assert.equal(socketEventInvalidatesMyWork({ type: 'review_decision' }), true);
  assert.equal(socketEventInvalidatesMyWork({ type: 'text_delta' }), false);
  assert.equal(socketEventInvalidatesMyWork({ payload: { type: 'assistant_message' } }), false);
});

test('My Work opens only the exact tenant, project, workspace, and conversation scope', () => {
  const item = {
    ...items[0],
    project_id: 'project-1',
    workspace_id: 'workspace-1',
    conversation_id: 'conversation-1',
  };
  const conversation = {
    id: 'conversation-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: 'workspace-1',
  };
  const context = { tenantId: 'tenant-1', projectId: 'project-1' };

  assert.equal(myWorkConversationMatchesScope(item, conversation, context), true);
  assert.equal(
    myWorkConversationMatchesScope(
      item,
      { ...conversation, workspace_id: null },
      context
    ),
    false
  );
  assert.equal(
    myWorkConversationMatchesScope(
      item,
      { ...conversation, tenant_id: 'tenant-2' },
      context
    ),
    false
  );
});

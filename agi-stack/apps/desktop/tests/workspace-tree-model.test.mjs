import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  buildWorkspaceTree,
  isWorkspaceConversationSelected,
  isWorkspaceOverviewSelected,
  reconcileExpandedWorkspaceIds,
  workspaceTreeRefreshFailed,
  workspaceTreeAvailability,
} = require('/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceTreeModel.js');

function conversation(id, title, updatedAt) {
  return {
    id,
    project_id: 'project-1',
    tenant_id: 'tenant-1',
    user_id: 'user-1',
    title,
    status: 'active',
    message_count: 1,
    created_at: '2026-07-01T00:00:00Z',
    updated_at: updatedAt,
  };
}

test('workspace tree preserves the authoritative server order within the current project', () => {
  const workspaces = [
    { id: 'workspace-b', name: 'Beta', project_id: 'project-1' },
    { id: 'workspace-a', name: 'Alpha', project_id: 'project-1' },
  ];
  const conversations = {
    'workspace-a': [
      conversation('conversation-z', 'Zebra task', '2026-07-02T00:00:00Z'),
      conversation('conversation-a', 'Alpha task', '2026-07-03T00:00:00Z'),
    ],
  };

  const tree = buildWorkspaceTree(workspaces, conversations, 'project');

  assert.deepEqual(
    tree.map((node) => node.workspace.id),
    ['workspace-b', 'workspace-a']
  );
  assert.deepEqual(
    tree[1].conversations.map((item) => item.id),
    ['conversation-z', 'conversation-a']
  );
  assert.equal(tree.some((node) => 'project' in node), false);
});

test('recent grouping orders workspaces and conversations by authoritative timestamps', () => {
  const workspaces = [
    { id: 'workspace-old', name: 'Old', updated_at: '2026-07-01T00:00:00Z' },
    { id: 'workspace-new', name: 'New', updated_at: '2026-07-02T00:00:00Z' },
  ];
  const conversations = {
    'workspace-old': [
      conversation('conversation-latest', 'Latest', '2026-07-13T10:00:00Z'),
      conversation('conversation-earlier', 'Earlier', '2026-07-13T09:00:00Z'),
    ],
  };

  const tree = buildWorkspaceTree(workspaces, conversations, 'recent');

  assert.equal(tree[0].workspace.id, 'workspace-old');
  assert.deepEqual(
    tree[0].conversations.map((item) => item.id),
    ['conversation-latest', 'conversation-earlier']
  );
});

test('workspace root is selected only while its overview is visible', () => {
  assert.equal(isWorkspaceOverviewSelected('workspace-a', 'workspace-a', 'overview'), true);
  assert.equal(isWorkspaceOverviewSelected('workspace-a', 'workspace-a', 'conversation'), false);
  assert.equal(isWorkspaceOverviewSelected('workspace-a', 'workspace-b', 'overview'), false);
});

test('conversation rows are selected only in conversation and My Work views', () => {
  assert.equal(
    isWorkspaceConversationSelected('conversation-a', 'conversation-a', 'conversation'),
    true
  );
  assert.equal(
    isWorkspaceConversationSelected('conversation-a', 'conversation-a', 'my-work'),
    true
  );
  assert.equal(
    isWorkspaceConversationSelected('conversation-a', 'conversation-a', 'overview'),
    false
  );
});

test('workspace refresh expands only the selected root on first load', () => {
  assert.deepEqual(
    [
      ...reconcileExpandedWorkspaceIds(
        new Set(),
        ['workspace-a', 'workspace-b'],
        'workspace-b',
        true
      ),
    ],
    ['workspace-b']
  );
});

test('workspace refresh preserves valid manual expansion and removes stale roots', () => {
  assert.deepEqual(
    [
      ...reconcileExpandedWorkspaceIds(
        new Set(['workspace-a', 'workspace-stale']),
        ['workspace-a', 'workspace-b'],
        'workspace-b',
        false
      ),
    ],
    ['workspace-a']
  );
});

test('same-project refresh preserves a manual collapse of the selected workspace', () => {
  assert.deepEqual(
    [
      ...reconcileExpandedWorkspaceIds(
        new Set(),
        ['workspace-a', 'workspace-b'],
        'workspace-b',
        false
      ),
    ],
    []
  );
});

test('same-project refresh keeps an already loaded tree visible', () => {
  assert.equal(workspaceTreeAvailability({ loading: true, error: null }, 3), 'ready');
  assert.equal(workspaceTreeAvailability({ loading: false, error: 'offline' }, 3), 'ready');
});

test('empty tree renders the authoritative loading, error, or empty state', () => {
  assert.equal(workspaceTreeAvailability({ loading: true, error: null }, 0), 'loading');
  assert.equal(workspaceTreeAvailability({ loading: false, error: 'offline' }, 0), 'error');
  assert.equal(workspaceTreeAvailability(undefined, 0), 'empty');
});

test('refresh failure settles the active project without discarding workspace node state', () => {
  assert.deepEqual(
    workspaceTreeRefreshFailed(
      {
        projects: {
          'project-a': { loading: true, error: null },
          'project-b': { loading: false, error: null },
        },
        workspaces: { 'workspace-a': { loading: false, error: null } },
      },
      'project-a',
      'offline'
    ),
    {
      projects: {
        'project-a': { loading: false, error: 'offline' },
        'project-b': { loading: false, error: null },
      },
      workspaces: { 'workspace-a': { loading: false, error: null } },
    }
  );
});

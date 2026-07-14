import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { buildWorkspaceTree } = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceTreeModel.js'
);

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

test('workspace tree represents only the current project workspace input', () => {
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
    ['workspace-a', 'workspace-b']
  );
  assert.deepEqual(
    tree[0].conversations.map((item) => item.id),
    ['conversation-a', 'conversation-z']
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

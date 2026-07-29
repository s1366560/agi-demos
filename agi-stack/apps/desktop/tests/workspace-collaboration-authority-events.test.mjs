import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { workspaceCollaborationAuthorityEvent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceCollaborationAuthorityEvent.js',
);

test('workspace collaboration authority recognizes exact scoped collaboration deltas', () => {
  for (const event of [
    {
      type: 'workspace_member_updated',
      data: { workspace_id: 'workspace-1', member: { id: 'member-1' } },
    },
    {
      event_type: 'blackboard_post_created',
      payload: { workspace_id: 'workspace-1', post_id: 'post-1' },
    },
    {
      type: 'workspace_message_created',
      data: { message: { id: 'message-1', workspace_id: 'workspace-1' } },
    },
    {
      type: 'topology_updated',
      data: { workspaceId: 'workspace-1' },
    },
  ]) {
    assert.equal(workspaceCollaborationAuthorityEvent(event, 'workspace-1'), true);
  }
});

test('workspace collaboration authority rejects cross-scope and malformed events', () => {
  assert.equal(
    workspaceCollaborationAuthorityEvent(
      {
        type: 'workspace_member_updated',
        data: { workspace_id: 'workspace-2' },
      },
      'workspace-1',
    ),
    false,
  );
  assert.equal(
    workspaceCollaborationAuthorityEvent(
      {
        type: 'assistant_message',
        data: { workspace_id: 'workspace-1' },
      },
      'workspace-1',
    ),
    false,
  );
  assert.equal(workspaceCollaborationAuthorityEvent(null, 'workspace-1'), false);
  assert.equal(workspaceCollaborationAuthorityEvent({}, ''), false);
});

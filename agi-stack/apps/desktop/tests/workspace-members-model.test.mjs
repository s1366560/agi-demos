import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  WORKSPACE_MEMBER_ROLES,
  canManageWorkspaceMembers,
  removeWorkspaceMemberByUserId,
  upsertWorkspaceMember,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceMembersModel.js'
);

function member(overrides = {}) {
  return {
    id: 'member-record-1',
    workspace_id: 'workspace-1',
    user_id: 'user-1',
    user_email: 'member@example.test',
    role: 'viewer',
    ...overrides,
  };
}

test('workspace member management accepts only the Web and backend role contract', () => {
  assert.deepEqual(WORKSPACE_MEMBER_ROLES, ['owner', 'editor', 'viewer']);
  assert.equal(
    canManageWorkspaceMembers(
      { status: 'ready', items: [member({ user_id: 'actor-1', role: 'owner' })], error: null },
      'actor-1',
    ),
    true,
  );
  assert.equal(
    canManageWorkspaceMembers(
      { status: 'ready', items: [member({ user_id: 'actor-1', role: 'editor' })], error: null },
      'actor-1',
    ),
    false,
  );
  assert.equal(
    canManageWorkspaceMembers(
      { status: 'loading', items: [member({ user_id: 'actor-1', role: 'owner' })], error: null },
      'actor-1',
    ),
    false,
  );
  assert.equal(
    canManageWorkspaceMembers(
      { status: 'ready', items: [member({ user_id: 'actor-1', role: 'owner' })], error: null },
      '',
    ),
    false,
  );
});

test('workspace member projection upserts by authority identity and preserves known email', () => {
  const owner = member({
    id: 'member-record-owner',
    user_id: 'owner-1',
    role: 'owner',
  });
  const viewer = member();
  const updated = upsertWorkspaceMember([owner, viewer], {
    ...viewer,
    user_email: null,
    role: 'editor',
  });
  assert.deepEqual(updated, [
    owner,
    {
      ...viewer,
      role: 'editor',
    },
  ]);

  const added = member({
    id: 'member-record-2',
    user_id: 'user-2',
    user_email: null,
  });
  assert.deepEqual(upsertWorkspaceMember(updated, added), [...updated, added]);
});

test('workspace member removal keys on user_id rather than membership record id', () => {
  const first = member();
  const second = member({ id: 'member-record-2', user_id: 'user-2' });
  assert.deepEqual(removeWorkspaceMemberByUserId([first, second], 'user-1'), [second]);
  assert.equal(removeWorkspaceMemberByUserId([first, second], 'member-record-1').length, 2);
});

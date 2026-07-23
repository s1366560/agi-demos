import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  availableWorkspaceAgentDefinitions,
  canManageWorkspaceAgentBindings,
  removeWorkspaceAgentBindingById,
  upsertWorkspaceAgentBinding,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/workspaceAgentBindingsModel.js'
);

function member(overrides = {}) {
  return {
    id: 'member-record-1',
    workspace_id: 'workspace-1',
    user_id: 'actor-1',
    user_email: 'actor@example.test',
    role: 'viewer',
    ...overrides,
  };
}

function binding(overrides = {}) {
  return {
    id: 'binding-1',
    workspace_id: 'workspace-1',
    agent_id: 'agent-1',
    display_name: 'Workspace Agent',
    description: null,
    config: {},
    is_active: true,
    ...overrides,
  };
}

function definition(overrides = {}) {
  return {
    id: 'agent-1',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    name: 'project-agent',
    display_name: 'Project Agent',
    enabled: true,
    model: 'project-model',
    ...overrides,
  };
}

test('workspace Agent binding mutations require an authoritative editor or owner role', () => {
  for (const role of ['owner', 'editor']) {
    assert.equal(
      canManageWorkspaceAgentBindings(
        { status: 'ready', items: [member({ role })], error: null },
        'actor-1',
      ),
      true,
    );
  }
  assert.equal(
    canManageWorkspaceAgentBindings(
      { status: 'ready', items: [member({ role: 'viewer' })], error: null },
      'actor-1',
    ),
    false,
  );
  assert.equal(
    canManageWorkspaceAgentBindings(
      { status: 'loading', items: [member({ role: 'owner' })], error: null },
      'actor-1',
    ),
    false,
  );
});

test('workspace Agent selector excludes definitions already bound by agent_id', () => {
  const available = availableWorkspaceAgentDefinitions(
    [
      definition(),
      definition({
        id: 'agent-2',
        name: 'tenant-agent',
        display_name: 'Tenant Agent',
        project_id: null,
      }),
    ],
    [binding({ is_active: false })],
  );
  assert.deepEqual(available.map((item) => item.id), ['agent-2']);
});

test('workspace Agent binding projection upserts by binding or Agent identity', () => {
  const first = binding();
  const updated = upsertWorkspaceAgentBinding([first], {
    ...first,
    display_name: 'Updated Agent',
  });
  assert.deepEqual(updated, [{ ...first, display_name: 'Updated Agent' }]);

  const rebound = binding({
    id: 'binding-rebound',
    display_name: 'Rebound Agent',
  });
  assert.deepEqual(upsertWorkspaceAgentBinding(updated, rebound), [rebound]);

  const second = binding({ id: 'binding-2', agent_id: 'agent-2' });
  assert.deepEqual(upsertWorkspaceAgentBinding([rebound], second), [rebound, second]);
});

test('workspace Agent unbind removes only the authoritative binding id', () => {
  const first = binding();
  const second = binding({ id: 'binding-2', agent_id: 'agent-2' });
  assert.deepEqual(removeWorkspaceAgentBindingById([first, second], 'binding-1'), [second]);
  assert.equal(removeWorkspaceAgentBindingById([first, second], 'agent-1').length, 2);
});

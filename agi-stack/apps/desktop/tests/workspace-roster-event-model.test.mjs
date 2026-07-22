import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { applyWorkspaceRosterStreamEvent } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/workspaceRosterEventModel.js',
);
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const ready = (items) => ({ status: 'ready', items, error: null });

test('workspace roster events upsert and remove members and Agent bindings', () => {
  let members = ready([]);
  let agents = ready([]);
  ({ members, agents } = applyWorkspaceRosterStreamEvent(members, agents, {
    type: 'workspace_member_joined', data: { workspace_id: 'workspace-1', member: {
      id: 'member-1', workspace_id: 'workspace-1', user_id: 'user-1', role: 'editor',
    } },
  }, 'workspace-1'));
  ({ members, agents } = applyWorkspaceRosterStreamEvent(members, agents, {
    type: 'workspace_member_updated', data: { workspace_id: 'workspace-1', member: {
      id: 'member-1', workspace_id: 'workspace-1', user_id: 'user-1', role: 'owner',
    } },
  }, 'workspace-1'));
  ({ members, agents } = applyWorkspaceRosterStreamEvent(members, agents, {
    type: 'workspace_agent_bound', data: { workspace_id: 'workspace-1', agent: {
      id: 'binding-1', workspace_id: 'workspace-1', agent_id: 'agent-1', is_active: true,
      display_name: 'Release agent',
    } },
  }, 'workspace-1'));
  assert.equal(members.items[0].role, 'owner');
  assert.equal(agents.items[0].display_name, 'Release agent');

  ({ members, agents } = applyWorkspaceRosterStreamEvent(members, agents, {
    type: 'workspace_member_left', data: {
      workspace_id: 'workspace-1', member_id: 'member-1', user_id: 'user-1',
    },
  }, 'workspace-1'));
  ({ members, agents } = applyWorkspaceRosterStreamEvent(members, agents, {
    type: 'workspace_agent_unbound', data: {
      workspace_id: 'workspace-1', workspace_agent_id: 'binding-1', agent_id: 'agent-1',
    },
  }, 'workspace-1'));
  assert.deepEqual(members.items, []);
  assert.deepEqual(agents.items, []);
});

test('workspace roster events reject cross-workspace and incomplete upserts', () => {
  const members = ready([]);
  const agents = ready([]);
  for (const event of [
    { type: 'workspace_member_joined', data: {
      workspace_id: 'workspace-2', member: {
        id: 'member-2', workspace_id: 'workspace-2', user_id: 'user-2', role: 'viewer',
      },
    } },
    { type: 'workspace_member_joined', data: {
      workspace_id: 'workspace-1', member: { id: 'member-1', workspace_id: 'workspace-1' },
    } },
    { type: 'workspace_agent_bound', data: {
      workspace_id: 'workspace-1', agent: {
        id: 'binding-1', workspace_id: 'workspace-1', agent_id: 'agent-1',
      },
    } },
  ]) {
    const result = applyWorkspaceRosterStreamEvent(members, agents, event, 'workspace-1');
    assert.equal(result.handled, false);
    assert.equal(result.members, members);
    assert.equal(result.agents, agents);
  }
});

test('Desktop applies workspace roster socket events to authority collections', () => {
  assert.match(appSource, /applyWorkspaceRosterStreamEvent\(/);
  assert.match(appSource, /workspaceRosterEventsHeadRef/);
});

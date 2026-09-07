import assert from 'node:assert/strict';
import test from 'node:test';
import { createAutomationConversationOpener } from '/tmp/agistack-desktop-test-dist/src/features/automations/automationConversationNavigation.js';

function fixture() {
  const conversation = { id: 'conversation', tenant_id: 'tenant', project_id: 'project', workspace_id: 'workspace', title: 'Result' };
  const state = { tenantId: 'tenant', projectId: 'project', contextRevision: 1, scopeEpoch: 2, conversations: [conversation] };
  const opened = [];
  const unavailable = [];
  const open = createAutomationConversationOpener({
    current: () => state,
    open: (...args) => opened.push(args),
    unavailable: () => unavailable.push(true),
  });
  return { state, conversation, opened, unavailable, open };
}

test('opens the current exact-scope conversation through the supplied navigation action', () => {
  const f = fixture();
  f.open({ id: 'conversation', workspaceId: 'workspace', title: 'Old title' });
  assert.deepEqual(f.opened, [['project', 'workspace', f.conversation, 'chat']]);
  assert.deepEqual(f.unavailable, []);
});

test('stale callbacks cannot navigate after project, identity, context or scope epoch changes', () => {
  for (const field of ['tenantId', 'projectId', 'contextRevision', 'scopeEpoch']) {
    const f = fixture();
    f.state[field] = typeof f.state[field] === 'number' ? 9 : 'other';
    f.open({ id: 'conversation', workspaceId: 'workspace', title: 'Result' });
    assert.deepEqual(f.opened, [], field);
  }
});

test('moved, removed, foreign and forged conversation choices cannot open', () => {
  for (const field of ['tenant_id', 'project_id', 'workspace_id', 'id', 'removed']) {
    const f = fixture();
    if (field === 'removed') f.state.conversations = [];
    else f.conversation[field] = 'other';
    f.open({ id: 'conversation', workspaceId: 'workspace', title: 'Result' });
    assert.deepEqual(f.opened, [], field);
    assert.equal(f.unavailable.length, 1, field);
  }
});

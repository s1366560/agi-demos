import assert from 'node:assert/strict';
import test from 'node:test';
import {
  automationConversationChoices,
  automationConversationBinding,
} from '/tmp/agistack-desktop-test-dist/src/features/automations/automationConversationModel.js';

const scope = { tenantId: 'tenant', projectId: 'project' };
const conversation = {
  id: 'conversation',
  tenant_id: 'tenant',
  project_id: 'project',
  workspace_id: 'workspace',
  title: 'Review',
};

test('conversation choices isolate scope, require a workspace and freeze detached values', () => {
  const source = { ...conversation };
  const choices = automationConversationChoices(
    [
      source,
      { ...conversation, id: 'foreign-tenant', tenant_id: 'other' },
      { ...conversation, id: 'foreign-project', project_id: 'other' },
      { ...conversation, id: 'no-workspace', workspace_id: null },
    ],
    scope,
  );
  assert.deepEqual(choices, [{ id: 'conversation', title: 'Review', workspaceId: 'workspace' }]);
  source.title = 'Later';
  source.workspace_id = 'moved';
  assert.equal(choices[0].title, 'Review');
  assert.equal(choices[0].workspaceId, 'workspace');
  assert.ok(Object.isFrozen(choices));
  assert.ok(Object.isFrozen(choices[0]));
});

test('reuse requires explicit selection and submits the matching workspace', () => {
  const choices = automationConversationChoices([conversation], scope);
  assert.equal(automationConversationBinding('reuse', '', choices, null), null);
  assert.equal(automationConversationBinding('reuse', 'unknown', choices, null), null);
  assert.deepEqual(automationConversationBinding('reuse', 'conversation', choices, null), {
    conversation_id: 'conversation',
    workspace_id: 'workspace',
  });
});

test('fresh omits saved IDs; unloaded existing bindings can be retained but never guessed', () => {
  const job = { conversation_id: 'saved', workspace_id: 'saved-workspace' };
  assert.deepEqual(automationConversationBinding('fresh', 'saved', [], job), {});
  assert.deepEqual(automationConversationBinding('reuse', 'saved', [], job), {
    conversation_id: 'saved',
    workspace_id: 'saved-workspace',
  });
  assert.equal(automationConversationBinding('reuse', 'different', [], job), null);
});

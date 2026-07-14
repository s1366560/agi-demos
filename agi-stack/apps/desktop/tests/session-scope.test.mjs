import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  planBelongsToConversation,
  planForConversation,
  socketEventBelongsToConversation,
  socketEventMatchesSessionScope,
  taskBelongsToConversation,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionScope.js');

test('session scope accepts only explicitly matching conversation events', () => {
  assert.equal(
    socketEventBelongsToConversation(
      { type: 'run_status', payload: { conversation_id: 'conversation-1' } },
      'conversation-1',
    ),
    true,
  );
  assert.equal(
    socketEventBelongsToConversation(
      { type: 'run_status', payload: { conversation_id: 'conversation-2' } },
      'conversation-1',
    ),
    false,
  );
  assert.equal(socketEventBelongsToConversation({ type: 'heartbeat' }, 'conversation-1'), false);
  assert.equal(
    socketEventBelongsToConversation(
      {
        conversation_id: 'conversation-2',
        payload: { data: { conversation_id: 'conversation-1' } },
      },
      'conversation-1',
    ),
    false,
  );
});

test('session scope accepts workspace-only authority events only when explicitly allowed', () => {
  const workspacePlanEvent = {
    event_type: 'workspace_plan_updated',
    workspace_id: 'workspace-1',
    payload: { workspace_id: 'workspace-1' },
  };

  assert.equal(
    socketEventMatchesSessionScope(
      workspacePlanEvent,
      { conversationId: 'conversation-1', workspaceId: 'workspace-1' },
      true,
    ),
    true,
  );
  assert.equal(
    socketEventMatchesSessionScope(
      workspacePlanEvent,
      { conversationId: 'conversation-1', workspaceId: 'workspace-2' },
      true,
    ),
    false,
  );
  assert.equal(
    socketEventMatchesSessionScope(
      workspacePlanEvent,
      { conversationId: 'conversation-1', workspaceId: 'workspace-1' },
      false,
    ),
    false,
  );
  assert.equal(
    socketEventMatchesSessionScope(
      {
        conversation_id: 'conversation-1',
        workspace_id: 'workspace-1',
        payload: { workspace_id: 'workspace-2' },
      },
      { conversationId: 'conversation-1', workspaceId: 'workspace-1' },
      false,
    ),
    false,
  );
  assert.equal(
    socketEventMatchesSessionScope(
      { conversation_id: 'conversation-1' },
      { conversationId: 'conversation-1', workspaceId: 'workspace-1' },
      false,
    ),
    true,
  );
});

test('session scope never attaches unscoped workspace tasks or plans', () => {
  assert.equal(taskBelongsToConversation({ id: 'task-1' }, 'conversation-1'), false);
  assert.equal(
    taskBelongsToConversation(
      { id: 'task-1', metadata: { conversation_id: 'conversation-1' } },
      'conversation-1',
    ),
    true,
  );
  assert.equal(planBelongsToConversation({ revision: 1 }, 'conversation-1'), false);
  assert.equal(
    planBelongsToConversation({ conversation_id: 'conversation-1', revision: 1 }, 'conversation-1'),
    true,
  );
});

test('session scope projects the selected conversation from a workspace execution snapshot', () => {
  const selected = planForConversation(
    {
      workspace_id: 'workspace-1',
      project_id: 'project-1',
      plan: null,
      conversation_plans: [
        {
          conversation_id: 'conversation-1',
          title: 'Selected session',
          plan: {
            id: 'plan-1',
            conversation_id: 'conversation-1',
            version: 2,
            status: 'approved',
            tasks: [],
            created_at: '2026-07-13T00:00:00Z',
          },
          run: { id: 'run-1', conversation_id: 'conversation-1' },
          pending_hitl: [{ id: 'hitl-1', conversation_id: 'conversation-1' }],
          artifacts: [{ id: 'artifact-1', conversation_id: 'conversation-1' }],
          delivery: [{ id: 'delivery-1', conversation_id: 'conversation-1' }],
        },
        {
          conversation_id: 'conversation-2',
          title: 'Other session',
          plan: null,
          run: null,
          pending_hitl: [],
          artifacts: [],
          delivery: [],
        },
      ],
      plan_history: [
        { id: 'plan-1', conversation_id: 'conversation-1' },
        { id: 'plan-2', conversation_id: 'conversation-2' },
      ],
    },
    'conversation-1',
  );

  assert.equal(selected.conversation_id, 'conversation-1');
  assert.equal(selected.plan.id, 'plan-1');
  assert.equal(selected.run_health[0].id, 'run-1');
  assert.deepEqual(selected.pending_hitl.map((item) => item.id), ['hitl-1']);
  assert.deepEqual(selected.artifact_index.map((item) => item.id), ['artifact-1']);
  assert.deepEqual(selected.delivery.map((item) => item.id), ['delivery-1']);
  assert.deepEqual(selected.plan_history.map((item) => item.id), ['plan-1']);
  assert.equal(planForConversation({ workspace_id: 'workspace-1' }, 'missing'), null);
});

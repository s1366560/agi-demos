import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  buildHitlSocketMessage,
  canQueuePendingAgentRunMessage,
  createPendingAgentMessageQueue,
  conversationSubscriptionMessages,
  createAgentSocketContextState,
  enqueuePendingAgentRunMessage,
  eventCursor,
  flushPendingAgentRunMessages,
  pendingAgentRunQueueScopeKey,
  reconnectDelay,
  resetAgentSocketContextState,
  transitionAgentSocketConversationSelection,
  socketEventKey,
  socketEventsSince,
} = require('/tmp/agistack-desktop-test-dist/src/hooks/useAgentSocket.js');

test('only an authenticated cloud socket may retain a turn for reconnect', () => {
  assert.equal(canQueuePendingAgentRunMessage('cloud', true, 'ms_sk_session'), true);
  assert.equal(canQueuePendingAgentRunMessage('cloud', false, 'ms_sk_session'), false);
  assert.equal(canQueuePendingAgentRunMessage('cloud', true, ''), false);
  assert.equal(canQueuePendingAgentRunMessage('local', true, 'local-session'), false);
});

test('cloud agent turns wait in a bounded deduplicated queue until the socket opens', () => {
  const queue = createPendingAgentMessageQueue();
  const message = {
    conversationId: 'conversation-1',
    projectId: 'project-1',
    message: 'Prepare the plan',
    messageId: 'message-1',
  };

  assert.equal(enqueuePendingAgentRunMessage(queue, message), true);
  assert.equal(enqueuePendingAgentRunMessage(queue, message), true);
  assert.equal(queue.size, 1);

  const sent = [];
  assert.equal(
    flushPendingAgentRunMessages(queue, (payload) => {
      sent.push(payload);
      return true;
    }),
    1,
  );
  assert.deepEqual(sent, [
    {
      type: 'send_message',
      conversation_id: 'conversation-1',
      project_id: 'project-1',
      message: 'Prepare the plan',
      message_id: 'message-1',
    },
  ]);
  assert.equal(queue.size, 0);
});

test('failed socket flush preserves pending cloud turns for the next reconnect', () => {
  const queue = createPendingAgentMessageQueue();
  enqueuePendingAgentRunMessage(queue, {
    conversationId: 'conversation-1',
    projectId: 'project-1',
    message: 'Prepare the plan',
    messageId: 'message-1',
  });
  enqueuePendingAgentRunMessage(queue, {
    conversationId: 'conversation-2',
    projectId: 'project-1',
    message: 'Review the result',
    messageId: 'message-2',
  });

  assert.equal(flushPendingAgentRunMessages(queue, () => false), 0);
  assert.equal(queue.size, 2);
});

test('pending cloud turns survive workspace activation within the same project', () => {
  const baseConfig = {
    apiBaseUrl: 'https://cloud.memstack.example',
    apiKey: 'cloud-session',
    localApiToken: '',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-before-create',
    mode: 'cloud',
    workspaceRoot: '',
  };

  assert.equal(
    pendingAgentRunQueueScopeKey(baseConfig, 7),
    pendingAgentRunQueueScopeKey(
      { ...baseConfig, workspaceId: 'workspace-created-for-session' },
      7,
    ),
  );
});

test('pending cloud turns reset when authenticated project authority changes', () => {
  const baseConfig = {
    apiBaseUrl: 'https://cloud.memstack.example',
    apiKey: 'cloud-session',
    localApiToken: '',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    mode: 'cloud',
    workspaceRoot: '',
  };
  const currentKey = pendingAgentRunQueueScopeKey(baseConfig, 7);

  assert.notEqual(
    currentKey,
    pendingAgentRunQueueScopeKey({ ...baseConfig, projectId: 'project-2' }, 7),
  );
  assert.notEqual(
    currentKey,
    pendingAgentRunQueueScopeKey({ ...baseConfig, apiKey: 'rotated-session' }, 7),
  );
  assert.notEqual(currentKey, pendingAgentRunQueueScopeKey(baseConfig, 8));
});

test('queued cloud turns preserve Agent, skill, mention, attachment, and composer context routing', () => {
  const queue = createPendingAgentMessageQueue();
  enqueuePendingAgentRunMessage(queue, {
    conversationId: 'conversation-1',
    projectId: 'project-1',
    message: '/review Review this change',
    messageId: 'message-context-1',
    agentId: 'definition-reviewer',
    forcedSkillName: 'source-research',
    mentions: ['agent-research'],
    fileMetadata: [
      {
        filename: 'evidence.txt',
        sandbox_path: '/workspace/input/evidence.txt',
        mime_type: 'text/plain',
        size_bytes: 42,
      },
    ],
    appModelContext: {
      desktop_composer_context: {
        resources: [{ kind: 'plugin', resource_id: 'github' }],
      },
    },
  });

  const sent = [];
  assert.equal(
    flushPendingAgentRunMessages(queue, (payload) => {
      sent.push(payload);
      return true;
    }),
    1,
  );
  assert.deepEqual(sent, [
    {
      type: 'send_message',
      conversation_id: 'conversation-1',
      project_id: 'project-1',
      message: '/review Review this change',
      message_id: 'message-context-1',
      agent_id: 'definition-reviewer',
      forced_skill_name: 'source-research',
      mentions: ['agent-research'],
      file_metadata: [
        {
          filename: 'evidence.txt',
          sandbox_path: '/workspace/input/evidence.txt',
          mime_type: 'text/plain',
          size_bytes: 42,
        },
      ],
      app_model_context: {
        desktop_composer_context: {
          resources: [{ kind: 'plugin', resource_id: 'github' }],
        },
      },
    },
  ]);
});

test('buildHitlSocketMessage preserves the backend WebSocket contract', () => {
  assert.deepEqual(
    buildHitlSocketMessage({
      requestId: 'clarification-1',
      hitlType: 'clarification',
      responseData: { answer: 'Use the indexed repository.' },
    }),
    {
      type: 'clarification_respond',
      request_id: 'clarification-1',
      answer: 'Use the indexed repository.',
    }
  );
  assert.deepEqual(
    buildHitlSocketMessage({
      requestId: 'permission-1',
      hitlType: 'permission',
      responseData: { granted: false },
    }),
    {
      type: 'permission_respond',
      request_id: 'permission-1',
      granted: false,
    }
  );
});

test('eventCursor accepts Python, server Rust, and desktop Rust cursor fields', () => {
  assert.deepEqual(
    eventCursor({ conversation_id: 'conversation-1', event_time_us: 41, event_counter: 2 }),
    { conversationId: 'conversation-1', timeUs: 41, counter: 2 }
  );
  assert.deepEqual(eventCursor({ conversation_id: 'conversation-2', time_us: 82, counter: 5 }), {
    conversationId: 'conversation-2',
    timeUs: 82,
    counter: 5,
  });
  assert.deepEqual(
    eventCursor({ conversation_id: 'conversation-3', eventTimeUs: 120, eventCounter: 9 }),
    { conversationId: 'conversation-3', timeUs: 120, counter: 9 }
  );
});

test('socketEventKey and reconnectDelay support replay dedupe and bounded backoff', () => {
  assert.equal(socketEventKey({ event_id: '10-0' }), 'event:10-0');
  assert.equal(
    socketEventKey({ conversation_id: 'c1', event_time_us: 41, event_counter: 2 }),
    'cursor:c1:41:2'
  );
  assert.equal(reconnectDelay(0), 500);
  assert.equal(reconnectDelay(8), 15_000);
});

test('socketEventsSince returns every coalesced event once in arrival order', () => {
  const oldest = { event_id: 'event-1' };
  const middle = { event_id: 'event-2' };
  const newest = { event_id: 'event-3' };
  const events = [newest, middle, oldest];

  assert.deepEqual(socketEventsSince(events, null), [oldest, middle, newest]);
  assert.deepEqual(socketEventsSince(events, oldest), [middle, newest]);
  assert.deepEqual(socketEventsSince(events, newest), []);
  assert.deepEqual(socketEventsSince(events, { event_id: 'evicted' }), [oldest, middle, newest]);
  assert.deepEqual(socketEventsSince([], newest), []);
});

test('workspace context changes clear every replay and subscription cursor', () => {
  const state = createAgentSocketContextState();
  state.conversationCursors.set('conversation-1', {
    conversationId: 'conversation-1',
    timeUs: 41,
    counter: 2,
  });
  state.subscribedConversations.add('conversation-1');
  state.workspaceEventId = 'workspace-event-9';
  state.seenEventKeys.add('event:workspace-event-9');

  resetAgentSocketContextState(state);

  assert.equal(state.conversationCursors.size, 0);
  assert.equal(state.subscribedConversations.size, 0);
  assert.equal(state.workspaceEventId, null);
  assert.equal(state.seenEventKeys.size, 0);
});

test('active conversation transition replaces stale subscriptions without clearing replay cursors', () => {
  const state = createAgentSocketContextState();
  state.subscribedConversations.add('conversation-old');
  state.conversationCursors.set('conversation-new', {
    conversationId: 'conversation-new',
    timeUs: 82,
    counter: 5,
  });

  const selected = transitionAgentSocketConversationSelection(state, ' conversation-new ');

  assert.deepEqual(selected, {
    unsubscribeConversationIds: ['conversation-old'],
    subscribeConversationId: 'conversation-new',
  });
  assert.deepEqual([...state.subscribedConversations], ['conversation-new']);
  assert.deepEqual(state.conversationCursors.get('conversation-new'), {
    conversationId: 'conversation-new',
    timeUs: 82,
    counter: 5,
  });
  assert.deepEqual(conversationSubscriptionMessages(state), [
    {
      type: 'subscribe',
      conversation_id: 'conversation-new',
      from_time_us: 82,
      from_counter: 6,
    },
  ]);

  const cleared = transitionAgentSocketConversationSelection(state, null);
  assert.deepEqual(cleared, {
    unsubscribeConversationIds: ['conversation-new'],
    subscribeConversationId: null,
  });
  assert.equal(state.subscribedConversations.size, 0);
});

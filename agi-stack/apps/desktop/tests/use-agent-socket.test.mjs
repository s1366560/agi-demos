import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  buildHitlSocketMessage,
  createAgentSocketContextState,
  eventCursor,
  reconnectDelay,
  resetAgentSocketContextState,
  socketEventKey,
  socketEventsSince,
} = require('/tmp/agistack-desktop-test-dist/src/hooks/useAgentSocket.js');

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

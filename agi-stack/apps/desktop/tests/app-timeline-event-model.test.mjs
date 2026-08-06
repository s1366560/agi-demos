import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const {
  agentTaskUpdateFromSocketEvent,
  mergeLiveTimelineEvent,
  mergeStreamingTextEvent,
  optimisticUserTimelineItem,
  timelineCursorFromFirst,
  timelineCursorFromLast,
  timelineItemFromSocketEvent,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/appTimelineEventModel.js'
);

test('agent task update maps send_message acknowledgements', () => {
  const update = agentTaskUpdateFromSocketEvent({
    type: 'ack',
    action: 'send_message',
    conversation_id: 'c1',
    message_id: 'm1',
    execution_message_id: 'e1',
  });
  assert.deepEqual(update, {
    conversationId: 'c1',
    messageId: 'm1',
    executionMessageId: 'e1',
    status: 'acknowledged',
    detail: 'Agent acknowledged the task over WebSocket.',
    eventType: 'ack:send_message',
  });
});

test('agent task update surfaces nested error detail as failure', () => {
  const update = agentTaskUpdateFromSocketEvent({
    type: 'run_error',
    conversation_id: 'c1',
    payload: { detail: 'boom' },
  });
  assert.equal(update.status, 'failed');
  assert.match(update.detail, /boom/);
});

test('agent task update ignores events without a conversation id', () => {
  assert.equal(agentTaskUpdateFromSocketEvent({ type: 'ack' }), null);
  assert.equal(agentTaskUpdateFromSocketEvent(null), null);
});

test('timeline item parses user messages with cursor fields', () => {
  const item = timelineItemFromSocketEvent({
    type: 'user_message',
    conversation_id: 'c1',
    time_us: 5000,
    counter: 2,
    data: { content: 'hello', message_id: 'm2' },
  });
  assert.equal(item.id, 'user_message-5000-2');
  assert.equal(item.role, 'user');
  assert.equal(item.content, 'hello');
  assert.equal(item.eventTimeUs, 5000);
  assert.equal(item.timestamp, 5);
  assert.equal(item.message_id, 'm2');
});

test('timeline item skips protocol control events', () => {
  assert.equal(timelineItemFromSocketEvent({ type: 'heartbeat' }), null);
  assert.equal(
    timelineItemFromSocketEvent({ type: 'act', action: 'subscribe' }),
    null,
  );
});

test('timeline item maps observe payloads to tool output rows', () => {
  const item = timelineItemFromSocketEvent({
    type: 'observe',
    time_us: 7000,
    data: { tool_name: 'read_file', observation: 'data', error: 'x' },
  });
  assert.equal(item.toolName, 'read_file');
  assert.equal(item.toolOutput, 'data');
  assert.equal(item.isError, true);
});

test('live ack rebinds the optimistic user message to the execution id', () => {
  const existing = [optimisticUserTimelineItem('m1', 'hi')];
  const merged = mergeLiveTimelineEvent(existing, {
    type: 'ack',
    action: 'send_message',
    conversation_id: 'c1',
    message_id: 'm1',
    execution_message_id: 'e9',
  });
  assert.equal(merged.length, 1);
  assert.equal(merged[0].message_id, 'e9');
  assert.equal(merged[0].executionMessageId, 'e9');
  assert.equal(merged[0].metadata.clientMessageId, 'm1');
});

test('orphan streaming deltas without protocol identity are dropped', () => {
  const existing = [];
  const merged = mergeLiveTimelineEvent(existing, {
    type: 'text_delta',
    conversation_id: 'c1',
    data: { delta: 'partial' },
  });
  assert.equal(merged, existing);
});

test('text_end materializes a settled assistant row from full_text', () => {
  const merged = mergeStreamingTextEvent(
    [],
    {
      conversation_id: 'c1',
      message_id: 'r1',
      time_us: 10000,
      counter: 1,
      data: { full_text: 'final text' },
    },
    'text_end',
  );
  assert.equal(merged.length, 1);
  assert.equal(merged[0].id, 'streaming-assistant-r1');
  assert.equal(merged[0].content, 'final text');
  assert.equal(merged[0].metadata.streaming, false);
});

test('timeline cursors derive from the boundary items only', () => {
  assert.equal(timelineCursorFromFirst([]), null);
  assert.equal(timelineCursorFromLast([]), null);
  const items = [
    { eventTimeUs: 10, eventCounter: 1 },
    { eventTimeUs: 20, eventCounter: 2 },
  ];
  assert.deepEqual(timelineCursorFromFirst(items), { timeUs: 10, counter: 1 });
  assert.deepEqual(timelineCursorFromLast(items), { timeUs: 20, counter: 2 });
});

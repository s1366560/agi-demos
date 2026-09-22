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

test('independent lifecycle items never define conversation pagination cursors', () => {
  const lifecycle = (time) => timelineItemFromSocketEvent({
    type: 'subagent_started', event_time_us: time,
    timeline_cursor_source: 'project_lifecycle', lifecycle_event_id: `event-${time}`,
    data: { run_id: 'child', execution_id: 'child' },
  });
  const first = { id: 'first', type: 'thought', eventTimeUs: 10, eventCounter: 2 };
  const last = { id: 'last', type: 'observe', eventTimeUs: 20, eventCounter: 3 };
  const before = lifecycle(1), after = lifecycle(100);
  assert.equal(before.cursorSource, 'project_lifecycle');
  for (const items of [[before, first, last, after], [first, after], [before, first]]) {
    assert.deepEqual(timelineCursorFromFirst(items), { timeUs: 10, counter: 2 });
    assert.deepEqual(timelineCursorFromLast(items), items.includes(last)
      ? { timeUs: 20, counter: 3 } : { timeUs: 10, counter: 2 });
  }
  assert.equal(timelineCursorFromFirst([before, after]), null);
  assert.equal(timelineCursorFromLast([before, after]), null);
  // ID spelling is irrelevant: legacy conversation records remain compatible.
  assert.deepEqual(timelineCursorFromLast([{ ...last, id: 'subagent-lifecycle:legacy' }]),
    { timeUs: 20, counter: 3 });
});

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

test('signed plugin events preserve authorized JSON output without fabricating withheld values', () => {
  const { pairToolCallItems, toolCallPairStatus } = require('/tmp/agistack-desktop-test-dist/src/features/chat/chatTimelineModel.js');
  const tool = 'plugin__b96e9e91893a6b27fc9aae3d7c35f19b74dece1e';
  const input = JSON.stringify({score: 20260914, api_key: '[REDACTED]'});
  for (const output of [JSON.stringify({score: 20260914}), '[UNAVAILABLE]']) {
    let items = mergeLiveTimelineEvent([], {
      type:'act',conversation_id:'plugin-conversation',message_id:'plugin-message',counter:1,time_us:1000,
      data:{tool_name:tool,tool_input:input,call_id:'plugin-call',tool_execution_id:'plugin-execution'},
    });
    items = mergeLiveTimelineEvent(items, {
      type:'observe',conversation_id:'plugin-conversation',message_id:'plugin-message',counter:2,time_us:2000,
      data:{tool_name:tool,tool_output:output,call_id:'plugin-call',tool_execution_id:'plugin-execution',is_error:false},
    });
    const pairs=pairToolCallItems(items);
    assert.equal(pairs.length,1);
    assert.equal(pairs[0].call.toolInput,input);
    assert.equal(pairs[0].result.toolOutput,output);
    assert.equal(toolCallPairStatus(pairs[0]),'complete');
  }
});

test('observe failure normalization trusts boolean envelope status without scanning content', () => {
  for (const toolOutput of [{ isError: true }, JSON.stringify({ is_error: true })]) {
    const item = timelineItemFromSocketEvent({ type: 'observe', data: { is_error: false, tool_output: toolOutput } });
    assert.equal(item.isError, true);
    assert.deepEqual(item.toolOutput, toolOutput);
  }
  for (const toolOutput of ['error', { isError: 'true' }, { content: [{ text: 'failed' }], isError: false }, { data: { isError: true } }]) {
    assert.equal(timelineItemFromSocketEvent({ type: 'observe', data: { tool_output: toolOutput } }).isError, false);
  }
  assert.equal(timelineItemFromSocketEvent({ type: 'observe', isError: true, data: { is_error: false } }).isError, true);
  assert.equal(timelineItemFromSocketEvent({ type: 'observe', data: { is_error: false, error: 'Denied' } }).isError, true);
});

test('runtime errors stay failed and preserve known metadata without requiring a flag', () => {
  const item = timelineItemFromSocketEvent({ type: 'error', payload: { error: 'Busy', error_code: 'runtime_conflict' } });
  assert.equal(item.isError, true);
  assert.equal(item.error, 'Busy');
  assert.equal(item.payload.error_code, 'runtime_conflict');
});

test('live todowrite preserves structured failure without classifying error prose', () => {
  const output = { success: false, code: 'PLAN_EXECUTION_NOT_APPROVED', error: 'Plan mode requires approval' };
  for (const toolOutput of [output, JSON.stringify(output), { success: false }, { error: { code: 'DENIED' } }]) {
    const item = timelineItemFromSocketEvent({ type: 'observe', data: { tool_name: 'todowrite', tool_output: toolOutput, is_error: false } });
    assert.equal(item.isError, true);
    assert.deepEqual(item.toolOutput, toolOutput);
  }
  assert.equal(timelineItemFromSocketEvent({type:'observe',data:{tool_output:{success:'false',error:null}}}).isError,false);
});

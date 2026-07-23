import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { reconcileAgentTaskSignals } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/agentTaskSignalModel.js',
);

function signal(id, messageId) {
  return {
    id,
    content: id,
    status: 'queued',
    detail: 'Queued',
    createdAt: '2026-07-23T00:00:00.000Z',
    conversationId: 'conversation-1',
    messageId,
  };
}

test('send acknowledgement rebinds only its matching signal to the execution id', () => {
  const current = [signal('task-1', 'client-1'), signal('task-2', 'client-2')];

  const next = reconcileAgentTaskSignals(current, {
    conversationId: 'conversation-1',
    messageId: 'client-1',
    executionMessageId: 'execution-1',
    status: 'acknowledged',
    detail: 'Acknowledged',
    eventType: 'ack:send_message',
  });

  assert.equal(next[0].messageId, 'execution-1');
  assert.equal(next[0].status, 'acknowledged');
  assert.deepEqual(next[1], current[1]);
});

test('completion removes only the signal with the exact execution id', () => {
  const current = [signal('task-1', 'execution-1'), signal('task-2', 'execution-2')];

  const next = reconcileAgentTaskSignals(current, {
    conversationId: 'conversation-1',
    messageId: 'execution-1',
    status: 'acknowledged',
    detail: 'Completed',
    eventType: 'complete',
  });

  assert.deepEqual(next.map((item) => item.id), ['task-2']);
});

test('unmatched or id-less updates never fall back to the latest task signal', () => {
  const current = [signal('task-1', 'execution-1'), signal('task-2', 'execution-2')];

  const unmatched = reconcileAgentTaskSignals(current, {
    conversationId: 'conversation-1',
    messageId: 'execution-other',
    status: 'failed',
    detail: 'Other turn failed',
    eventType: 'error',
  });
  const idless = reconcileAgentTaskSignals(current, {
    conversationId: 'conversation-1',
    status: 'failed',
    detail: 'Unassociated transport error',
    eventType: 'error',
  });

  assert.strictEqual(unmatched, current);
  assert.strictEqual(idless, current);
});

test('an exact error marks its signal failed for the dedicated error surface', () => {
  const current = [signal('task-1', 'execution-1')];

  const next = reconcileAgentTaskSignals(current, {
    conversationId: 'conversation-1',
    messageId: 'execution-1',
    status: 'failed',
    detail: 'Execution failed',
    eventType: 'error',
  });

  assert.equal(next[0].status, 'failed');
  assert.equal(next[0].detail, 'Execution failed');
});

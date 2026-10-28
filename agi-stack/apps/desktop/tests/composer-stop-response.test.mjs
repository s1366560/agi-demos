import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { composerStopMessageId, composerStopTarget, dispatchComposerStop } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/composerStopResponse.js',
);

const run = {
  id: 'rendered-run', conversation_id: 'conversation-1', message_id: 'message-1',
  status: 'running', revision: 7,
};
const local = { mode: 'local', scopeKey: 'owner-a', conversationId: 'conversation-1' };
const target = composerStopTarget({ ...local, run, messageId: 'message-1' });
const rejectSocket = () => assert.fail('authoritative run Stop must not send conversation-wide WS');

test('local Stop snapshots the rendered run id and revision', () => {
  const original = { ...run };
  const captured = composerStopTarget({ ...local, run: original });
  original.id = 'successor';
  original.revision = 9;
  assert.deepEqual(captured, {
    kind: 'local_run', scopeKey: 'owner-a', conversationId: 'conversation-1',
    runId: 'rendered-run', revision: 7, messageId: 'message-1',
  });
});

test('local planning requires a specific message id and never targets an existing terminal run', () => {
  assert.equal(composerStopTarget({ ...local, run: null }), undefined);
  assert.equal(composerStopTarget({ ...local, run: { ...run, status: 'completed' }, messageId: 'message-1' }), undefined);
  assert.deepEqual(composerStopTarget({ ...local, run: { ...run, status: 'completed' }, messageId: 'next-message' }), {
    kind: 'local_turn', scopeKey: 'owner-a', conversationId: 'conversation-1', messageId: 'next-message',
  });
  assert.equal(composerStopTarget({ ...local, run: { ...run, revision: NaN } }), undefined);
  assert.equal(composerStopTarget({ ...local, conversationId: ' ', run }), undefined);
});

test('message targeting uses structured execution identity and excludes ambiguous pending signals', () => {
  const signal = { conversationId: 'conversation-1', messageId: 'pending', status: 'acknowledged' };
  assert.equal(composerStopMessageId('conversation-1', [
    { role: 'user', message_id: 'old' },
    { role: 'user', message_id: 'client-id', executionMessageId: 'execution-id' },
    { role: 'assistant', message_id: 'assistant-id' },
  ], [signal]), 'execution-id');
  assert.equal(composerStopMessageId('conversation-1', [{ role: 'user', content: 'stop message secret-id' }], [signal]), 'pending');
  assert.equal(composerStopMessageId('conversation-1', [], [signal, { ...signal, messageId: 'other' }]), undefined);
  assert.equal(composerStopMessageId('conversation-2', [], [signal]), undefined);
  assert.equal(composerStopMessageId('conversation-1', [], [{ ...signal, eventType: 'complete' }]), undefined);
});

test('REST cancel_requested remains pending until authoritative cancellation', async () => {
  const calls = [];
  const applied = [];
  const outcome = { accepted: true, status: 'cancel_requested', run };
  assert.deepEqual(await dispatchComposerStop(target, {
    cancelRun: async (...args) => { calls.push(args); return outcome; },
    stopSession: rejectSocket,
    onRunOutcome: (value) => applied.push(value),
  }), { status: 'cancel_requested' });
  assert.deepEqual(calls, [['rendered-run', 7]]);
  assert.deepEqual(applied, [outcome]);
  assert.deepEqual(await dispatchComposerStop(target, {
    cancelRun: async () => ({ ...outcome, run: { ...run, status: 'cancelled', revision: 8 } }),
    stopSession: rejectSocket,
  }), { status: 'cancelled' });
});

test('a rejected stale revision never retries against a successor or falls back to WS', async () => {
  const calls = [];
  const receipt = await dispatchComposerStop(target, {
    cancelRun: async (...args) => { calls.push(args); throw new Error('409 revision conflict'); },
    stopSession: rejectSocket,
    onRunOutcome: () => assert.fail('rejected control must not project a run'),
  });
  assert.deepEqual(calls, [['rendered-run', 7]]);
  assert.deepEqual(receipt, { status: 'rejected', errorCode: 'STOP_SESSION_FAILED' });
});

test('REST Stop rejects mismatched authority outcomes', async () => {
  for (const returnedRun of [{ ...run, id: 'successor' }, { ...run, conversation_id: 'other' }]) {
    assert.deepEqual(await dispatchComposerStop(target, {
      cancelRun: async () => ({ accepted: true, status: 'cancel_requested', run: returnedRun }),
      stopSession: rejectSocket,
      onRunOutcome: () => assert.fail('mismatched outcome must not project a run'),
    }), { status: 'rejected', errorCode: 'STOP_SESSION_FAILED' });
  }
});

test('an in-flight REST operation retains its captured identity', async () => {
  let resolve;
  const mutableTarget = { ...target };
  const pending = dispatchComposerStop(mutableTarget, {
    cancelRun: () => new Promise((done) => { resolve = done; }),
    stopSession: rejectSocket,
  });
  mutableTarget.runId = 'successor';
  resolve({ accepted: true, status: 'cancel_requested', run });
  assert.deepEqual(await pending, { status: 'cancel_requested' });
});

test('planning Stop carries exact message identity while cloud retains its existing WS contract', async () => {
  const calls = [];
  const operations = {
    cancelRun: async () => assert.fail('planning/cloud uses its WS transport'),
    stopSession: (...args) => { calls.push(args); return true; },
  };
  const planning = composerStopTarget({ ...local, run: null, messageId: 'planning-message' });
  assert.deepEqual(await dispatchComposerStop(planning, operations), { status: 'cancel_requested' });
  const cloud = composerStopTarget({ ...local, mode: 'cloud', run, messageId: 'cloud-message' });
  assert.deepEqual(await dispatchComposerStop(cloud, operations), { status: 'cancel_requested' });
  assert.deepEqual(calls, [
    ['conversation-1', { messageId: 'planning-message' }],
    ['conversation-1'],
  ]);
  assert.deepEqual(await dispatchComposerStop(planning, { ...operations, stopSession: () => false }), {
    status: 'rejected', errorCode: 'socket_unavailable',
  });
});

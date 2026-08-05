import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  resolveSessionComposerDispatch,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionComposerDispatchModel.js');

test('stale queue intent fails closed instead of falling back to a conversation message', () => {
  assert.deepEqual(
    resolveSessionComposerDispatch({
      requestedDelivery: 'queue_next',
      availableDeliveries: [],
      hasActiveRun: false,
      canSendConversationMessage: true,
      canSendRunInput: false,
    }),
    {
      kind: 'blocked',
      reason: 'run_input_authority_stale',
    },
  );
});

test('an active run without a selected canonical delivery cannot use normal send', () => {
  assert.deepEqual(
    resolveSessionComposerDispatch({
      requestedDelivery: null,
      availableDeliveries: ['steer_now', 'queue_next'],
      hasActiveRun: true,
      canSendConversationMessage: true,
      canSendRunInput: true,
    }),
    {
      kind: 'blocked',
      reason: 'run_input_delivery_required',
    },
  );
});

test('available queue intent uses canonical run-input authority', () => {
  assert.deepEqual(
    resolveSessionComposerDispatch({
      requestedDelivery: 'queue_next',
      availableDeliveries: ['steer_now', 'queue_next'],
      hasActiveRun: true,
      canSendConversationMessage: true,
      canSendRunInput: true,
    }),
    {
      kind: 'run_input',
      delivery: 'queue_next',
    },
  );
});

test('terminal session without a stale run-input intent may send a new message', () => {
  assert.deepEqual(
    resolveSessionComposerDispatch({
      requestedDelivery: null,
      availableDeliveries: [],
      hasActiveRun: false,
      canSendConversationMessage: true,
      canSendRunInput: false,
    }),
    { kind: 'conversation_message' },
  );
});

import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  protocolClientMessageId,
  protocolStreamMessageId,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/chat/agentEventIdentityModel.js'
);

test('terminal replay falls back to the execution message identity', () => {
  const replayedComplete = {
    type: 'complete',
    time_us: 1_200_000,
    counter: 3,
    data: {
      execution_message_id: 'execution-message-1',
      execution_summary: { step_count: 2 },
    },
  };

  assert.equal(protocolStreamMessageId(replayedComplete), 'execution-message-1');
});

test('response message identity wins when both protocol identities are present', () => {
  const event = {
    data: {
      message_id: 'response-message-1',
      execution_message_id: 'execution-message-1',
    },
  };

  assert.equal(protocolStreamMessageId(event), 'response-message-1');
});

test('ack identity lookup never substitutes an execution identity for the client message', () => {
  assert.equal(
    protocolClientMessageId({
      type: 'ack',
      action: 'send_message',
      data: { execution_message_id: 'execution-message-1' },
    }),
    undefined,
  );
});

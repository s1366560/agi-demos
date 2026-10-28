import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  EMPTY_AGENT_STOP_REQUEST,
  agentStopRequestSettlesStreaming,
  agentStopResponseButtonDisabled,
  agentStopResponseButtonLabelKey,
  agentStopResponseButtonTitleKey,
  applyAgentStopEvent,
  applyAgentStopReceipt,
  beginAgentStopRequest,
  reconcileAgentStopScope,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/agentStopResponseModel.js'
);

test('stop request enters pending only after an immediate socket send succeeds', () => {
  assert.deepEqual(beginAgentStopRequest('conversation-1', true), {
    conversationId: 'conversation-1',
    status: 'stopping',
    errorCode: null,
  });
  assert.deepEqual(beginAgentStopRequest('conversation-1', false), {
    conversationId: 'conversation-1',
    status: 'error',
    errorCode: 'socket_unavailable',
  });
  assert.deepEqual(beginAgentStopRequest(' ', true), EMPTY_AGENT_STOP_REQUEST);
});

test('only the matching structured stop acknowledgment settles streaming', () => {
  const stopping = beginAgentStopRequest('conversation-1', true);
  const unrelated = applyAgentStopEvent(stopping, {
    type: 'ack',
    action: 'stop_session',
    conversation_id: 'conversation-2',
  });
  assert.equal(unrelated, stopping);

  const acknowledged = applyAgentStopEvent(stopping, {
    type: 'ack',
    action: 'stop_session',
    conversation_id: 'conversation-1',
  });
  assert.deepEqual(acknowledged, {
    conversationId: 'conversation-1',
    status: 'stopped',
    errorCode: null,
  });
  assert.equal(
    agentStopRequestSettlesStreaming(acknowledged, 'conversation-1'),
    true,
  );
  assert.equal(
    agentStopRequestSettlesStreaming(acknowledged, 'conversation-2'),
    false,
  );
});

test('a matching cancellation event settles while a structured stop error remains recoverable', () => {
  const stopping = beginAgentStopRequest('conversation-1', true);
  // Runtime wire shape: {type: "cancelled", data: {run_id, status: "cancelled"}}.
  assert.equal(
    applyAgentStopEvent(stopping, {
      type: 'cancelled',
      data: { conversation_id: 'conversation-1', run_id: 'run-1', status: 'cancelled' },
    }).status,
    'stopped',
  );
  // Legacy boolean alias still settles.
  assert.equal(
    applyAgentStopEvent(stopping, {
      event_type: 'cancelled',
      data: { conversation_id: 'conversation-1', cancelled: true },
    }).status,
    'stopped',
  );
  // A cancelled event without a recognisable cancelled marker does not settle.
  assert.equal(
    applyAgentStopEvent(stopping, {
      type: 'cancelled',
      data: { conversation_id: 'conversation-1', status: 'running' },
    }).status,
    'stopping',
  );
  assert.deepEqual(
    applyAgentStopEvent(stopping, {
      type: 'error',
      conversation_id: 'conversation-1',
      data: {
        code: 'STOP_SESSION_FAILED',
        message: 'Failed to stop session',
      },
    }),
    {
      conversationId: 'conversation-1',
      status: 'error',
      errorCode: 'STOP_SESSION_FAILED',
    },
  );
});

test('conversation selection changes discard stale stop state and late events', () => {
  const stopping = beginAgentStopRequest('conversation-1', true);
  assert.deepEqual(
    reconcileAgentStopScope(stopping, 'conversation-2'),
    EMPTY_AGENT_STOP_REQUEST,
  );
  assert.equal(
    applyAgentStopEvent(EMPTY_AGENT_STOP_REQUEST, {
      type: 'ack',
      action: 'stop_session',
      conversation_id: 'conversation-1',
    }),
    EMPTY_AGENT_STOP_REQUEST,
  );
});

test('stop button is disabled while the socket is disconnected and enabled when connected', () => {
  // Disconnected: the button cannot do anything but fail with
  // socket_unavailable, so it must be disabled with the offline hint tooltip.
  assert.equal(
    agentStopResponseButtonDisabled({ socketConnected: false, status: 'idle' }),
    true,
  );
  assert.equal(
    agentStopResponseButtonTitleKey({ socketConnected: false, status: 'idle' }),
    'session.stopResponseDisconnectedHint',
  );
  // The aria label stays the plain action name; the tooltip carries the why.
  assert.equal(
    agentStopResponseButtonLabelKey({ socketConnected: false, status: 'idle' }),
    'session.stopResponse',
  );
  // Connected and not stopping: enabled with the plain label.
  assert.equal(
    agentStopResponseButtonDisabled({ socketConnected: true, status: 'idle' }),
    false,
  );
  assert.equal(
    agentStopResponseButtonTitleKey({ socketConnected: true, status: 'idle' }),
    'session.stopResponse',
  );
  // Stopping in flight stays disabled regardless of connection state.
  for (const socketConnected of [true, false]) {
    assert.equal(
      agentStopResponseButtonDisabled({ socketConnected, status: 'stopping' }),
      true,
    );
    assert.equal(
      agentStopResponseButtonTitleKey({ socketConnected, status: 'stopping' }),
      'session.stoppingResponse',
    );
  }
});

test('ChatPanel wires the composer stop button to the live socket state', () => {
  const chatPanelSource = readFileSync(
    new URL('../src/features/chat/ChatPanel.tsx', import.meta.url),
    'utf8',
  );
  // The composer receives the live socket flag and the stop button derives its
  // disabled state from it instead of staying clickable during an outage.
  assert.match(chatPanelSource, /useAgentSocketConnected\(\)/);
  assert.match(chatPanelSource, /stopResponseSocketConnected/);
  assert.match(
    chatPanelSource,
    /disabled=\{agentStopResponseButtonDisabled\(\{[\s\S]*socketConnected: stopResponseSocketConnected/,
  );
});

const localRunTarget = {
  kind: 'local_run', scopeKey: 'owner-a', conversationId: 'conversation-1',
  runId: 'run-1', revision: 7, messageId: 'message-1',
};

test('cancel_requested receipts remain pending and only the matching request may settle', () => {
  const stopping = beginAgentStopRequest('conversation-1', true, localRunTarget, 1);
  assert.equal(applyAgentStopReceipt(stopping, 1, localRunTarget, { status: 'cancel_requested' }), stopping);
  assert.equal(applyAgentStopReceipt(stopping, 0, localRunTarget, { status: 'cancelled' }), stopping);
  assert.equal(applyAgentStopReceipt(stopping, 1, { ...localRunTarget, scopeKey: 'owner-b' }, { status: 'cancelled' }), stopping);
  assert.equal(applyAgentStopReceipt(stopping, 1, localRunTarget, { status: 'cancelled' }).status, 'stopped');
  assert.equal(applyAgentStopReceipt(stopping, 1, localRunTarget, { status: 'rejected', errorCode: 'STOP_SESSION_FAILED' }).status, 'error');
});

test('same-conversation successor and owner changes discard old asynchronous stop state', () => {
  const stopping = beginAgentStopRequest('conversation-1', true, localRunTarget, 1);
  const successor = { ...localRunTarget, runId: 'run-2', messageId: 'message-2' };
  const reset = reconcileAgentStopScope(stopping, 'conversation-1', successor);
  assert.equal(reset, EMPTY_AGENT_STOP_REQUEST);
  const next = beginAgentStopRequest('conversation-1', true, successor, 2);
  assert.equal(applyAgentStopReceipt(next, 1, localRunTarget, { status: 'cancelled' }), next);
  assert.equal(reconcileAgentStopScope(stopping, 'conversation-1', { ...localRunTarget, scopeKey: 'owner-b' }), EMPTY_AGENT_STOP_REQUEST);
});

test('local run Stop settles only on its own authoritative cancellation event', () => {
  const stopping = beginAgentStopRequest('conversation-1', true, localRunTarget, 1);
  assert.equal(applyAgentStopEvent(stopping, {
    type: 'ack', action: 'stop_session', conversation_id: 'conversation-1',
  }), stopping);
  assert.equal(applyAgentStopEvent(stopping, {
    type: 'cancelled', conversation_id: 'conversation-1', data: { run_id: 'run-2', status: 'cancelled' },
  }), stopping);
  assert.equal(applyAgentStopEvent(stopping, {
    type: 'run_status', conversation_id: 'conversation-1', payload: { execution_id: 'run-1', status: 'running' },
  }), stopping);
  assert.equal(applyAgentStopEvent(stopping, {
    type: 'run_status', conversation_id: 'conversation-1', payload: { execution_id: 'run-1', status: 'cancelled' },
  }).status, 'stopped');
});

test('local planning acknowledgment stays pending and cancellation must match the message', () => {
  const target = { kind: 'local_turn', scopeKey: 'owner-a', conversationId: 'conversation-1', messageId: 'planning-1' };
  const stopping = beginAgentStopRequest('conversation-1', true, target, 1);
  assert.equal(applyAgentStopEvent(stopping, {
    type: 'ack', action: 'stop_session', status: 'cancel_requested',
    conversation_id: 'conversation-1', message_id: 'planning-1',
  }), stopping);
  assert.equal(applyAgentStopEvent(stopping, {
    type: 'cancelled', status: 'cancelled', conversation_id: 'conversation-1', message_id: 'planning-2',
  }), stopping);
  assert.equal(applyAgentStopEvent(stopping, {
    type: 'cancelled', status: 'cancelled', conversation_id: 'conversation-1', message_id: 'planning-1',
  }).status, 'stopped');
  assert.equal(applyAgentStopEvent(stopping, {
    type: 'error', code: 'SESSION_NOT_RUNNING', conversation_id: 'conversation-1', message_id: 'planning-1',
  }).status, 'error');
});

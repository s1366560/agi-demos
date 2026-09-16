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
  assert.equal(
    applyAgentStopEvent(stopping, {
      event_type: 'cancelled',
      data: { conversation_id: 'conversation-1', cancelled: true },
    }).status,
    'stopped',
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

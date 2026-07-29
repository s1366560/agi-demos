import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { appendTerminalLinesBounded, openTerminalSocket, terminalFrame } = require(
  '/tmp/agistack-desktop-test-dist/src/hooks/useTerminalProxy.js'
);

test('terminal WebSocket keeps launch capability and user session in separate subprotocols', () => {
  let openedUrl = '';
  let openedProtocols;
  class FakeWebSocket {
    constructor(url, protocols) {
      openedUrl = String(url);
      openedProtocols = protocols;
    }
  }

  openTerminalSocket(
    'ws://127.0.0.1:54321/api/v1/projects/local/sandbox/terminal/proxy/ws?session_id=1',
    'authenticated-session',
    'launch-capability',
    FakeWebSocket
  );

  assert.equal(
    openedUrl,
    'ws://127.0.0.1:54321/api/v1/projects/local/sandbox/terminal/proxy/ws?session_id=1'
  );
  assert.deepEqual(openedProtocols, [
    'memstack.launch',
    'launch-capability',
    'memstack.auth',
    'authenticated-session',
  ]);
  assert.doesNotMatch(openedUrl, /launch-capability|authenticated-session/);
});

test('TerminalSessionV2 resume authority uses a WebSocket subprotocol instead of the URL', () => {
  let openedUrl = '';
  let openedProtocols;
  class FakeWebSocket {
    constructor(url, protocols) {
      openedUrl = String(url);
      openedProtocols = protocols;
    }
  }
  openTerminalSocket(
    'wss://api.memstack.test/api/v1/projects/p1/sandbox/terminal/sessions/s1/ws',
    'authenticated-session',
    '',
    FakeWebSocket,
    'high-entropy-resume-token',
    41
  );
  assert.deepEqual(openedProtocols, [
    'memstack.auth',
    'authenticated-session',
    'memstack.terminal-v2',
    'high-entropy-resume-token',
  ]);
  assert.equal(
    openedUrl,
    'wss://api.memstack.test/api/v1/projects/p1/sandbox/terminal/sessions/s1/ws?after_sequence=41'
  );
  assert.doesNotMatch(openedUrl, /resume-token|authenticated-session/);
});

test('terminal authority revocation is a structured terminal error', () => {
  assert.deepEqual(
    terminalFrame(
      JSON.stringify({
        type: 'authority_revoked',
        code: 'terminal_authority_revoked',
        message: 'run revision changed',
      })
    ),
    {
      line: '[authority revoked] run revision changed',
      error: 'terminal_authority_revoked',
      disconnect: { kind: 'authority_revoked' },
    }
  );
  assert.deepEqual(
    terminalFrame(JSON.stringify({ type: 'output', sequence: 7, data: 'ready\n' }), true),
    {
      line: 'ready\n',
      error: null,
      sequence: 7,
    }
  );
});

test('legacy terminal output remains compatible while V2 requires monotonic sequences', () => {
  const legacyOutput = JSON.stringify({ type: 'output', data: 'legacy\n' });
  assert.deepEqual(terminalFrame(legacyOutput), {
    line: 'legacy\n',
    error: null,
  });
  assert.deepEqual(terminalFrame(legacyOutput, true), {
    line: null,
    error: 'terminal_output_gap',
    disconnect: { kind: 'output_gap' },
  });
});

test('terminal session loss remains a stable structured reconnect boundary', () => {
  assert.deepEqual(
    terminalFrame(
      JSON.stringify({
        type: 'session_lost',
        message: 'registry no longer owns this PTY',
      })
    ),
    {
      line: '[session lost] registry no longer owns this PTY',
      error: 'terminal_session_lost',
      disconnect: { kind: 'session_lost' },
    }
  );
  assert.deepEqual(
    terminalFrame(JSON.stringify({ type: 'terminal_session_lost', refetch: true })),
    {
      line: '[session lost] ',
      error: 'terminal_session_lost',
      disconnect: { kind: 'session_lost' },
    }
  );
  assert.deepEqual(
    terminalFrame(
      JSON.stringify({
        type: 'error',
        code: 'terminal_session_lost',
        message: 'PTY was lost after restart',
      })
    ),
    {
      line: '[error] PTY was lost after restart',
      error: 'terminal_session_lost',
    }
  );
});

test('terminal output gaps and input overloads stay distinct structured failures', () => {
  assert.deepEqual(
    terminalFrame(
      JSON.stringify({
        type: 'connected',
        contract_version: 2,
        session_id: 'terminal-session-1',
        resumed: true,
      }),
      true
    ),
    { line: null, error: null }
  );
  assert.deepEqual(
    terminalFrame(
      JSON.stringify({
        type: 'terminal_output_gap',
        after_sequence: 4,
        oldest_sequence: 8,
        latest_sequence: 12,
        refetch: true,
      })
    ),
    {
      line: null,
      error: 'terminal_output_gap',
      disconnect: { kind: 'output_gap' },
    }
  );
  assert.deepEqual(
    terminalFrame(JSON.stringify({ type: 'terminal_input_overload', refetch: false })),
    {
      line: null,
      error: 'terminal_input_overload',
      disconnect: { kind: 'input_overload' },
    }
  );
  assert.deepEqual(
    terminalFrame(JSON.stringify({ type: 'ack', after_sequence: 12, latest_sequence: 12 })),
    {
      line: null,
      error: null,
      acknowledged_sequence: 12,
    }
  );
});

test('terminal line aggregation has a byte bound and retains the newest complete lines', () => {
  assert.deepEqual(appendTerminalLinesBounded(['aaaa'], ['bbb', 'cc'], 7), ['bbb', 'cc']);
  assert.deepEqual(appendTerminalLinesBounded([], ['oversized'], 4), []);
});

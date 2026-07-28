import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { openTerminalSocket, terminalFrame } = require(
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
    }
  );
  assert.deepEqual(terminalFrame(JSON.stringify({ type: 'output', data: 'ready\n' })), {
    line: 'ready\n',
    error: null,
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

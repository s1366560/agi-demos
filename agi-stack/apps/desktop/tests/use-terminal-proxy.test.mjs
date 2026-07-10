import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { openTerminalSocket } = require(
  '/tmp/agistack-desktop-test-dist/src/hooks/useTerminalProxy.js'
);

test('terminal WebSocket sends the capability in the authentication subprotocol', () => {
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
    'local-capability',
    FakeWebSocket
  );

  assert.equal(
    openedUrl,
    'ws://127.0.0.1:54321/api/v1/projects/local/sandbox/terminal/proxy/ws?session_id=1'
  );
  assert.deepEqual(openedProtocols, ['memstack.auth', 'local-capability']);
  assert.doesNotMatch(openedUrl, /local-capability/);
});

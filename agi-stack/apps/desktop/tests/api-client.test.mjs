import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { desktopApiCredential, DesktopApiClient } = require(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);
const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');

test('respondToHitl sends the authenticated unified HITL payload', async () => {
  const calls = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (input, init) => {
    calls.push({ input, init });
    return new Response(
      JSON.stringify({ success: true, message: 'Decision response received' }),
      {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }
    );
  };

  try {
    const client = new DesktopApiClient({
      ...DEFAULT_CONFIG,
      apiBaseUrl: 'http://127.0.0.1:8088',
      apiKey: 'stale-cloud-token',
      localApiToken: 'local-session-token',
    });

    await client.respondToHitl({
      requestId: 'request-1',
      hitlType: 'decision',
      responseData: { decision: 'approve' },
    });

    assert.equal(calls.length, 1);
    assert.equal(
      String(calls[0]?.input),
      'http://127.0.0.1:8088/api/v1/agent/hitl/respond'
    );
    assert.equal(
      new Headers(calls[0]?.init?.headers).get('Authorization'),
      'Bearer local-session-token'
    );
    assert.deepEqual(JSON.parse(String(calls[0]?.init?.body)), {
      request_id: 'request-1',
      hitl_type: 'decision',
      response_data: { decision: 'approve' },
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('desktop credential prefers a Tauri capability but preserves manual local API keys', () => {
  assert.equal(
    desktopApiCredential({
      ...DEFAULT_CONFIG,
      apiKey: 'manual-local-key',
      localApiToken: '',
    }),
    'manual-local-key'
  );
  assert.equal(
    desktopApiCredential({
      ...DEFAULT_CONFIG,
      apiKey: 'manual-local-key',
      localApiToken: 'tauri-capability',
    }),
    'tauri-capability'
  );
});

test('agent WebSocket keeps credentials in the authentication subprotocol', () => {
  const client = new DesktopApiClient({
    ...DEFAULT_CONFIG,
    apiBaseUrl: 'http://127.0.0.1:8088',
    localApiToken: 'tauri-capability',
  });

  const url = client.agentWsUrl('session-1');
  assert.equal(url, 'ws://127.0.0.1:8088/api/v1/agent/ws?session_id=session-1');
  assert.doesNotMatch(url, /tauri-capability/);
  assert.deepEqual(client.agentWsProtocols(), ['memstack.auth', 'tauri-capability']);
});

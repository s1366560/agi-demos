import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  IAB_BRIDGE_BACKOFF_STEPS_MS,
  iabBridgeBackoffDelayMs,
  parseIabBridgeRegistry,
  pickIabBridgeTransport,
} = require('/tmp/agistack-desktop-test-dist/electron/main/iab/iabRegistry.js');

const sampleRegistry = {
  schemaVersion: 1,
  wsUrl: 'ws://127.0.0.1:9765/api/v1/browser-bridge/ws',
  token: 'a'.repeat(64),
  extensionIds: ['enbljdpbhdllbbkcjhccmbgpkfmcdkkl'],
  sidecarPath: '/usr/local/bin/agistack-desktop-sidecar',
  updatedAt: '2026-08-07T00:00:00Z',
};

test('iab registry parsing mirrors the sidecar contract', () => {
  const registry = parseIabBridgeRegistry(sampleRegistry);
  assert.equal(registry.schemaVersion, 1);
  assert.equal(registry.wsUrl, sampleRegistry.wsUrl);
  assert.equal(registry.token, sampleRegistry.token);
  assert.equal(registry.socketPath, null);

  const withSocket = parseIabBridgeRegistry({
    ...sampleRegistry,
    socketPath: '/home/dev/.memstack/browser-bridge/bridge.sock',
  });
  assert.equal(withSocket.socketPath, '/home/dev/.memstack/browser-bridge/bridge.sock');
});

test('iab registry validation fails closed on off-contract documents', () => {
  assert.throws(() => parseIabBridgeRegistry(null), /invalid/);
  assert.throws(() => parseIabBridgeRegistry({ ...sampleRegistry, schemaVersion: 2 }), /schema version/);
  assert.throws(
    () => parseIabBridgeRegistry({ ...sampleRegistry, wsUrl: 'ws://192.168.1.10:9765/ws' }),
    /127\.0\.0\.1/,
  );
  assert.throws(
    () => parseIabBridgeRegistry({ ...sampleRegistry, wsUrl: 'http://127.0.0.1:9765/ws' }),
    /127\.0\.0\.1/,
  );
  assert.throws(
    () => parseIabBridgeRegistry({ ...sampleRegistry, token: 'z'.repeat(64) }),
    /token/,
  );
  assert.throws(
    () => parseIabBridgeRegistry({ ...sampleRegistry, token: 'a'.repeat(63) }),
    /token/,
  );
  assert.throws(
    () =>
      parseIabBridgeRegistry({
        ...sampleRegistry,
        socketPath: 'relative/.memstack/browser-bridge/bridge.sock',
      }),
    /absolute/,
  );
  assert.throws(
    () =>
      parseIabBridgeRegistry({
        ...sampleRegistry,
        socketPath: '/home/dev/.memstack/browser-bridge/other.sock',
      }),
    /bridge\.sock/,
  );
  assert.throws(
    () =>
      parseIabBridgeRegistry({
        ...sampleRegistry,
        socketPath: '/home/dev/.memstack/other/bridge.sock',
      }),
    /browser-bridge/,
  );
});

test('iab transport selection prefers the unix socket only when it exists', () => {
  const registry = parseIabBridgeRegistry({
    ...sampleRegistry,
    socketPath: '/home/dev/.memstack/browser-bridge/bridge.sock',
  });
  assert.deepEqual(pickIabBridgeTransport(registry, true), {
    kind: 'unix',
    socketPath: '/home/dev/.memstack/browser-bridge/bridge.sock',
  });
  assert.deepEqual(pickIabBridgeTransport(registry, false), {
    kind: 'tcp',
    wsUrl: sampleRegistry.wsUrl,
  });
  const tcpOnly = parseIabBridgeRegistry(sampleRegistry);
  assert.deepEqual(pickIabBridgeTransport(tcpOnly, true), {
    kind: 'tcp',
    wsUrl: sampleRegistry.wsUrl,
  });
});

test('iab reconnect backoff matches the Rust broker steps', () => {
  assert.deepEqual([...IAB_BRIDGE_BACKOFF_STEPS_MS], [250, 1_000, 4_000, 10_000]);
  assert.equal(iabBridgeBackoffDelayMs(0), 250);
  assert.equal(iabBridgeBackoffDelayMs(1), 1_000);
  assert.equal(iabBridgeBackoffDelayMs(2), 4_000);
  assert.equal(iabBridgeBackoffDelayMs(3), 10_000);
  assert.equal(iabBridgeBackoffDelayMs(7), 10_000);
});

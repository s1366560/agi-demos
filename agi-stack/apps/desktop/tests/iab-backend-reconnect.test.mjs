import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { IabBackend } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/iab/backend.js',
);
const { connectIabBridgeSocket } = require(
  '/tmp/agistack-desktop-test-dist/electron/main/iab/bridgeSocket.js',
);

const TOKEN = 'a'.repeat(64);

/** A registry whose advertised unix socket is a regular file (no listener). */
function makeStaleRegistry() {
  const root = mkdtempSync(join(tmpdir(), 'iab-backend-test-'));
  const dir = join(root, '.memstack', 'browser-bridge');
  mkdirSync(dir, { recursive: true });
  const socketPath = join(dir, 'bridge.sock');
  writeFileSync(socketPath, ''); // exists, but is not a listening socket
  const registryPath = join(dir, 'registry.json');
  writeFileSync(
    registryPath,
    JSON.stringify({
      schemaVersion: 1,
      wsUrl: 'ws://127.0.0.1:1/api/v1/browser-bridge/ws',
      token: TOKEN,
      extensionIds: [],
      sidecarPath: '/nonexistent',
      updatedAt: new Date().toISOString(),
      socketPath,
    }),
  );
  return { root, registryPath, socketPath };
}

function activeHandleCount() {
  return process._getActiveHandles().length;
}

test('reconnect loop keeps cycling against an unreachable bridge', async (t) => {
  const { root, registryPath } = makeStaleRegistry();
  t.after(() => rmSync(root, { recursive: true, force: true }));
  let attempts = 0;
  const backend = new IabBackend({
    pool: {},
    registryPath,
    retryDelaysMs: [5],
    log: () => {},
    onRetry: () => {
      attempts += 1;
    },
  });
  t.after(async () => {
    await backend.stop();
  });
  backend.start();
  // ~5ms per attempt; 250ms must see many iterations or the loop is wedged.
  await new Promise((resolve) => setTimeout(resolve, 250));
  const firstSample = attempts;
  assert.ok(firstSample >= 5, `expected >= 5 attempts after 250ms, got ${firstSample}`);
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.ok(attempts > firstSample, 'loop must keep cycling');
  assert.equal(backend.status, 'connecting');
  await backend.stop();
  assert.equal(backend.status, 'disabled');
  const stoppedAt = attempts;
  await new Promise((resolve) => setTimeout(resolve, 50));
  assert.equal(attempts, stoppedAt, 'no attempts may run after stop()');
});

test('stop() interrupts a long backoff sleep promptly', async () => {
  const { root, registryPath } = makeStaleRegistry();
  const backend = new IabBackend({
    pool: {},
    registryPath,
    retryDelaysMs: [60_000],
    log: () => {},
  });
  backend.start();
  // Wait for the first failed attempt so the loop is inside the 60s sleep.
  await new Promise((resolve) => setTimeout(resolve, 150));
  const started = Date.now();
  await backend.stop();
  assert.ok(Date.now() - started < 2_000, 'stop() must wake the backoff sleep');
  rmSync(root, { recursive: true, force: true });
});

test('offline logging is throttled to the first failure then every 12th', async (t) => {
  const { root, registryPath } = makeStaleRegistry();
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const logs = [];
  let attempts = 0;
  const backend = new IabBackend({
    pool: {},
    registryPath,
    retryDelaysMs: [2],
    log: (message) => logs.push(message),
    onRetry: () => {
      attempts += 1;
    },
  });
  t.after(async () => {
    await backend.stop();
  });
  backend.start();
  while (attempts < 25) {
    // eslint-disable-next-line no-await-in-loop
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  await backend.stop();
  // Attempts 1, 12, 24 are logged out of 25.
  assert.equal(logs.length, 3, `expected 3 throttled log lines, got ${logs.length}`);
  assert.match(logs[0], /iab bridge connect failed/);
});

test('failed connect rejects and never fires onClose (TDZ regression)', async () => {
  const { root, socketPath } = makeStaleRegistry();
  let closed = 0;
  await assert.rejects(
    connectIabBridgeSocket({ kind: 'unix', socketPath }, TOKEN, {
      onMessage: () => {},
      onClose: () => {
        closed += 1;
      },
    }),
    /connect failed|ECONNREFUSED|ENOTSOCK/,
  );
  // Give the socket's 'close' event a chance to fire.
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(closed, 0, 'onClose must not fire for a connection that never opened');
  rmSync(root, { recursive: true, force: true });
});

test('failed connects leave no live handles behind', async () => {
  const { root, socketPath } = makeStaleRegistry();
  const baseline = activeHandleCount();
  for (let index = 0; index < 3; index += 1) {
    // eslint-disable-next-line no-await-in-loop
    await connectIabBridgeSocket({ kind: 'unix', socketPath }, TOKEN, {
      onMessage: () => {},
      onClose: () => {},
    }).catch(() => {});
  }
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(activeHandleCount(), baseline, 'errored sockets must be torn down');
  rmSync(root, { recursive: true, force: true });
});

test('failed TCP connects are torn down the same way', async () => {
  let closed = 0;
  await assert.rejects(
    connectIabBridgeSocket(
      { kind: 'tcp', wsUrl: 'ws://127.0.0.1:1/api/v1/browser-bridge/ws' },
      TOKEN,
      { onMessage: () => {}, onClose: () => (closed += 1) },
    ),
    /connect failed/,
  );
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert.equal(closed, 0);
});

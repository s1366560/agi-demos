import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledModule = '/tmp/agistack-desktop-test-dist/electron/main/cloudSocketBroker.js';

const policy = Object.freeze({
  kind: 'voice',
  url: 'wss://cloud.memstack.test/api/v1/voice/chat?project_id=project-1&conversation_id=conversation-1',
  protocols: Object.freeze(['memstack.auth', 'vault-only-cloud-secret']),
  scope: Object.freeze({
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: 'workspace-1',
    conversation_id: 'conversation-1',
  }),
  binary: Object.freeze({ client_to_server: true, server_to_client: true }),
  limits: Object.freeze({
    max_frame_bytes: 256 * 1024,
    max_aggregate_bytes: 2 * 1024 * 1024,
    connect_timeout_ms: 15_000,
    idle_timeout_ms: 30_000,
  }),
});

test('main socket broker opens with vault protocols but emits only sanitized events', async () => {
  const { DesktopCloudSocketBroker } = require(compiledModule);
  const sockets = [];
  const events = [];
  const broker = new DesktopCloudSocketBroker({
    authorize: async () => policy,
    createSocket(url, protocols) {
      const socket = fakeSocket(url, protocols);
      sockets.push(socket);
      return socket;
    },
    emit: (ownerId, event) => events.push({ ownerId, event }),
  });

  await broker.open(7, {
    socketId: 'cloud-socket-broker-0001',
    request: { kind: 'voice', url: policy.url, scope: policy.scope },
  });
  assert.deepEqual(sockets[0].protocols, policy.protocols);
  sockets[0].open('memstack.auth');

  assert.deepEqual(events, [
    {
      ownerId: 7,
      event: {
        socketId: 'cloud-socket-broker-0001',
        type: 'open',
        protocol: 'memstack.auth',
      },
    },
  ]);
  assert.equal(JSON.stringify(events).includes('vault-only-cloud-secret'), false);
});

test('main socket broker validates both directions and closes on secret reflection', async () => {
  const { DesktopCloudSocketBroker } = require(compiledModule);
  const socket = fakeSocket(policy.url, policy.protocols);
  const events = [];
  const broker = new DesktopCloudSocketBroker({
    authorize: async () => policy,
    createSocket: () => socket,
    emit: (_ownerId, event) => events.push(event),
  });
  await broker.open(9, {
    socketId: 'cloud-socket-broker-0002',
    request: { kind: 'voice', url: policy.url, scope: policy.scope },
  });
  socket.open('memstack.auth');

  await broker.send(9, {
    socketId: 'cloud-socket-broker-0002',
    frame: { binary: false, text: '{"type":"audio_end"}' },
  });
  assert.deepEqual(socket.sent, ['{"type":"audio_end"}']);

  socket.message(new Uint8Array([1, 2, 3]).buffer);
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual([...new Uint8Array(events.at(-1).frame.data)], [1, 2, 3]);

  socket.message(JSON.stringify({ type: 'error', detail: 'vault-only-cloud-secret' }));
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(socket.closeCalls.at(-1).code, 1008);
  assert.equal(events.some((event) => event.type === 'error'), true);
  assert.equal(JSON.stringify(events).includes('vault-only-cloud-secret'), false);
});

test('main socket broker binds send and cleanup to the renderer owner', async () => {
  const { DesktopCloudSocketBroker } = require(compiledModule);
  const socket = fakeSocket(policy.url, policy.protocols);
  const events = [];
  const broker = new DesktopCloudSocketBroker({
    authorize: async () => policy,
    createSocket: () => socket,
    emit: (ownerId, event) => events.push({ ownerId, event }),
  });
  await broker.open(11, {
    socketId: 'cloud-socket-broker-0003',
    request: { kind: 'voice', url: policy.url, scope: policy.scope },
  });
  socket.open('memstack.auth');

  await assert.rejects(
    broker.send(12, {
      socketId: 'cloud-socket-broker-0003',
      frame: { binary: false, text: '{}' },
    }),
    /cloud socket is unavailable/u,
  );
  assert.equal(broker.cancelOwner(11), 1);
  assert.equal(socket.closeCalls.at(-1).code, 1001);
  assert.equal(events.at(-1).ownerId, 11);
  assert.equal(events.at(-1).event.type, 'close');
  assert.equal(broker.activeCount, 0);
});

function fakeSocket(url, protocols) {
  return {
    url,
    protocols,
    protocol: '',
    readyState: 0,
    bufferedAmount: 0,
    binaryType: 'blob',
    onopen: null,
    onmessage: null,
    onerror: null,
    onclose: null,
    sent: [],
    closeCalls: [],
    send(data) {
      this.sent.push(data);
    },
    close(code = 1000, reason = '') {
      this.closeCalls.push({ code, reason });
      this.readyState = 2;
    },
    open(protocol) {
      this.protocol = protocol;
      this.readyState = 1;
      this.onopen?.();
    },
    message(data) {
      this.onmessage?.({ data });
    },
    finish(code = 1000, reason = '', wasClean = true) {
      this.readyState = 3;
      this.onclose?.({ code, reason, wasClean });
    },
  };
}

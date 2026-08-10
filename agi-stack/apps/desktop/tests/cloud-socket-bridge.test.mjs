import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledModule = '/tmp/agistack-desktop-test-dist/src/api/cloudSocketBridge.js';

const request = Object.freeze({
  kind: 'voice',
  url: 'wss://cloud.memstack.test/api/v1/voice/chat?project_id=project-1&conversation_id=conversation-1',
  scope: Object.freeze({
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: 'workspace-1',
    conversation_id: 'conversation-1',
  }),
});

test('renderer adapter exposes WebSocket-like open, message, send, and close behavior', async () => {
  const { createCloudSocketBridge } = require(compiledModule);
  const transport = fakeTransport();
  const socket = createCloudSocketBridge(request, transport, {
    socketId: 'renderer-cloud-socket-0001',
  });
  const opened = [];
  const messages = [];
  const closed = [];
  socket.onopen = (event) => opened.push(event);
  socket.addEventListener('message', (event) => messages.push(event.data));
  socket.onclose = (event) => closed.push(event);

  await transport.opened;
  assert.equal(socket.readyState, 0);
  assert.equal(JSON.stringify(transport.commands).includes('credential'), false);
  assert.deepEqual(transport.commands[0], {
    command: 'open',
    input: {
      socketId: 'renderer-cloud-socket-0001',
      request,
    },
  });

  transport.emit({
    socketId: 'other-socket-id-0000001',
    type: 'open',
    protocol: 'memstack.auth',
  });
  assert.equal(socket.readyState, 0);
  transport.emit({
    socketId: 'renderer-cloud-socket-0001',
    type: 'open',
    protocol: 'memstack.auth',
  });
  assert.equal(socket.readyState, 1);
  assert.equal(socket.protocol, 'memstack.auth');
  assert.equal(opened.length, 1);

  socket.send('hello');
  assert.equal(socket.bufferedAmount, 5);
  await transport.sent;
  await Promise.resolve();
  assert.equal(socket.bufferedAmount, 0);
  assert.deepEqual(transport.commands[1], {
    command: 'send',
    input: {
      socketId: 'renderer-cloud-socket-0001',
      frame: { binary: false, text: 'hello' },
    },
  });

  transport.emit({
    socketId: 'renderer-cloud-socket-0001',
    type: 'message',
    frame: { binary: false, text: '{"type":"tts_start"}' },
  });
  const audio = new Uint8Array([1, 2, 3, 4]);
  transport.emit({
    socketId: 'renderer-cloud-socket-0001',
    type: 'message',
    frame: { binary: true, data: audio.buffer },
  });
  assert.equal(messages[0], '{"type":"tts_start"}');
  assert.deepEqual([...new Uint8Array(messages[1])], [1, 2, 3, 4]);

  socket.close(1000, 'done');
  assert.equal(socket.readyState, 2);
  assert.deepEqual(transport.commands[2], {
    command: 'close',
    input: {
      socketId: 'renderer-cloud-socket-0001',
      code: 1000,
      reason: 'done',
    },
  });
  transport.emit({
    socketId: 'renderer-cloud-socket-0001',
    type: 'close',
    code: 1000,
    reason: 'done',
    wasClean: true,
  });
  assert.equal(socket.readyState, 3);
  assert.equal(closed.length, 1);
  assert.equal(closed[0].wasClean, true);
  assert.equal(transport.listenerCount(), 0);
});

test('renderer adapter rejects sends before open and validates close authority', async () => {
  const { createCloudSocketBridge } = require(compiledModule);
  const transport = fakeTransport();
  const socket = createCloudSocketBridge(request, transport, {
    socketId: 'renderer-cloud-socket-0002',
  });
  await transport.opened;

  assert.throws(() => socket.send('not-open'), { name: 'InvalidStateError' });
  assert.throws(() => socket.close(2000, 'invalid'), {
    name: 'InvalidAccessError',
  });
  assert.throws(() => socket.close(1000, 'x'.repeat(124)), {
    name: 'SyntaxError',
  });
  transport.emit({
    socketId: 'renderer-cloud-socket-0002',
    type: 'open',
    protocol: 'memstack.auth',
  });
  assert.throws(() => socket.send({ unsupported: true }), {
    name: 'TypeError',
  });
});

test('renderer adapter fails closed on malformed native events and transport failures', async () => {
  const { createCloudSocketBridge } = require(compiledModule);
  const transport = fakeTransport();
  const socket = createCloudSocketBridge(request, transport, {
    socketId: 'renderer-cloud-socket-0003',
  });
  const errors = [];
  const closes = [];
  socket.onerror = (event) => errors.push(event);
  socket.onclose = (event) => closes.push(event);
  await transport.opened;
  transport.emit({
    socketId: 'renderer-cloud-socket-0003',
    type: 'open',
    protocol: 'credential-must-not-cross',
  });

  assert.equal(socket.readyState, 3);
  assert.equal(errors.length, 1);
  assert.equal(errors[0].reason, 'cloud_socket_bridge_event_invalid');
  assert.equal(closes.length, 1);
  assert.equal(closes[0].code, 1006);
  assert.equal(transport.commands.at(-1).command, 'close');

  const failedTransport = fakeTransport({
    openError: new Error('native unavailable'),
  });
  const failedSocket = createCloudSocketBridge(request, failedTransport, {
    socketId: 'renderer-cloud-socket-0004',
  });
  const failedErrors = [];
  failedSocket.addEventListener('error', (event) => failedErrors.push(event.reason));
  await failedTransport.opened;
  await Promise.resolve();
  assert.equal(failedSocket.readyState, 3);
  assert.deepEqual(failedErrors, ['cloud_socket_bridge_open_failed']);
});

test('Electron renderer transport exposes only socket commands and sanitized events', async () => {
  const { desktopCloudSocketTransport } = require(compiledModule);
  const commands = [];
  let nativeListener;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: {
        invoke: async (command, args) => commands.push({ command, args }),
      },
      events: {
        onCloudSocketEvent(listener) {
          nativeListener = listener;
          return () => undefined;
        },
      },
    },
  };

  const transport = desktopCloudSocketTransport();
  assert.ok(transport);
  const events = [];
  transport.subscribe((event) => events.push(event));
  await transport.open({ socketId: 'renderer-cloud-socket-0010', request });
  await transport.send({
    socketId: 'renderer-cloud-socket-0010',
    frame: { binary: false, text: '{}' },
  });
  await transport.close({ socketId: 'renderer-cloud-socket-0010', code: 1000, reason: '' });
  nativeListener({
    socketId: 'renderer-cloud-socket-0010',
    type: 'open',
    protocol: 'memstack.auth',
  });

  assert.deepEqual(commands.map(({ command }) => command), [
    'cloud_socket_open',
    'cloud_socket_send',
    'cloud_socket_close',
  ]);
  assert.equal(JSON.stringify(commands).includes('credential'), false);
  assert.equal(events.length, 1);
});

function fakeTransport(options = {}) {
  const listeners = new Set();
  const commands = [];
  let resolveOpened;
  let resolveSent;
  const opened = new Promise((resolve) => {
    resolveOpened = resolve;
  });
  const sent = new Promise((resolve) => {
    resolveSent = resolve;
  });
  return {
    commands,
    opened,
    sent,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    async open(input) {
      commands.push({ command: 'open', input });
      resolveOpened();
      if (options.openError) throw options.openError;
    },
    async send(input) {
      commands.push({ command: 'send', input });
      resolveSent();
    },
    async close(input) {
      commands.push({ command: 'close', input });
    },
    emit(event) {
      for (const listener of [...listeners]) listener(event);
    },
    listenerCount() {
      return listeners.size;
    },
  };
}

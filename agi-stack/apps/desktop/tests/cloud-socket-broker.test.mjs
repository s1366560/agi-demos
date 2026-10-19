import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledModule =
  '/tmp/agistack-desktop-test-dist/apps/desktop/electron/main/cloudSocketBroker.js';

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
  assert.equal(
    events.some((event) => event.type === 'error'),
    true
  );
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
    /cloud socket is unavailable/u
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

test('renderer failure cleanup code closes and releases the native connection', async () => {
  const { DesktopCloudSocketBroker } = require(compiledModule);
  const socket = fakeSocket(policy.url, policy.protocols);
  const broker = new DesktopCloudSocketBroker({
    authorize: async () => policy,
    createSocket: () => socket,
    emit: () => {},
  });
  await broker.open(17, {
    socketId: 'cloud-socket-broker-0099',
    request: { kind: 'voice', url: policy.url, scope: policy.scope },
  });
  socket.open('memstack.auth');
  await broker.close(17, {
    socketId: 'cloud-socket-broker-0099',
    code: 3008,
    reason: 'bridge_failure',
  });
  assert.equal(socket.closeCalls.at(-1).code, 3008);
  assert.equal(broker.activeCount, 0);
});

const tick = () => new Promise((resolve) => setImmediate(resolve));

async function pausedAgentConnection(t, respond) {
  t.mock.timers.enable({ apis: ["setTimeout", "setInterval", "Date"], now: 0 });
  const { DesktopCloudSocketBroker } = require(compiledModule);
  const agentPolicy = {
    ...policy,
    kind: "agent",
    limits: { ...policy.limits, idle_timeout_ms: 75_000 },
  };
  const socket = fakeSocket(agentPolicy.url, agentPolicy.protocols);
  const events = [];
  const nativeClosed = [];
  let sendNative;
  const send = socket.send.bind(socket);
  socket.send = (data) => {
    send(data);
    if (respond && JSON.parse(data).type === "heartbeat") {
      socket.message(JSON.stringify({ type: "pong" }));
    }
  };
  const broker = new DesktopCloudSocketBroker({
    authorize: async () => agentPolicy,
    createSocket: () => socket,
    emit: (_owner, event) => events.push(event),
    computerUse: {
      async opened(_id, _scope, send) {
        sendNative = send;
      },
      receive: () => false,
      closed: (id) => nativeClosed.push(id),
    },
  });
  const socketId = "cloud-paused-agent-001";
  await broker.open(21, {
    socketId,
    request: { kind: "agent", url: agentPolicy.url, scope: agentPolicy.scope },
  });
  socket.open("memstack.auth");
  await tick();
  await sendNative({
    type: "computer_use_result",
    request_id: "paused-request",
    output_json:
      '{"type":"computer_use_control","status":"user_paused","retry_allowed":false}',
    is_error: false,
    media: [],
    control_outcome: "user_paused",
    control_generation: "pause-generation",
  });
  t.after(() => broker.cancelAll());
  return { broker, socket, socketId, events, nativeClosed };
}

test("main keeps a paused native agent connection alive while the renderer sends no frames", async (t) => {
  const { broker, socket, nativeClosed } = await pausedAgentConnection(t, true);
  for (let step = 0; step < 12; step++) {
    t.mock.timers.tick(20_000);
    await tick();
    assert.equal(broker.activeCount, 1);
  }
  assert.equal(
    socket.sent.filter((data) => JSON.parse(data).type === "heartbeat").length,
    12,
  );
  assert.deepEqual(nativeClosed, []);
  assert.deepEqual(socket.closeCalls, []);
  assert.equal(
    socket.sent.filter(
      (data) => JSON.parse(data).type === "computer_use_result",
    ).length,
    1,
    "keepalive must never replay the paused tool result",
  );
});

test("outbound heartbeats cannot keep an unresponsive paused agent connection alive", async (t) => {
  const { broker, socket, events, nativeClosed, socketId } =
    await pausedAgentConnection(t, false);
  for (let step = 0; step < 3; step++) {
    t.mock.timers.tick(20_000);
    await tick();
  }
  assert.equal(broker.activeCount, 0);
  assert.deepEqual(nativeClosed, [socketId]);
  assert.equal(events.at(-1).type, "close");
  assert.equal(events.at(-1).code, 4001);
  assert.equal(events.at(-1).reason, "cloud_socket_idle_timeout");
  const sent = socket.sent.length;
  t.mock.timers.tick(120_000);
  await tick();
  assert.equal(socket.sent.length, sent);
});

test("owner cancellation stops native keepalive even when late pong frames arrive", async (t) => {
  const { broker, socket, nativeClosed, socketId } =
    await pausedAgentConnection(t, true);
  t.mock.timers.tick(20_000);
  await tick();
  assert.equal(broker.cancelOwner(21), 1);
  socket.message(JSON.stringify({ type: "pong" }));
  const sent = socket.sent.length;
  t.mock.timers.tick(120_000);
  await tick();
  assert.equal(socket.sent.length, sent);
  assert.deepEqual(nativeClosed, [socketId]);
  assert.equal(socket.closeCalls.at(-1).code, 1001);
});

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

test('actual renderer receives Open before immediate server frames while native discovery is pending', async () => {
  const { DesktopCloudSocketBroker } = require(compiledModule);
  const {
    createCloudSocketBridge,
  } = require('/tmp/agistack-desktop-test-dist/apps/desktop/src/api/cloudSocketBridge.js');
  const discovery = deferred();
  const socket = fakeSocket(policy.url, policy.protocols);
  const order = [];
  let receive;
  const broker = new DesktopCloudSocketBroker({
    authorize: async () => ({ ...policy, kind: 'agent' }),
    createSocket: () => socket,
    emit: (_owner, event) => {
      order.push(event.type);
      receive?.(event);
    },
    computerUse: {
      async opened(_id, _scope, send) {
        await discovery.promise;
        await send({
          type: 'computer_use_device',
          device_id: 'fixture-device',
          tool_definitions: [],
        });
      },
      receive: () => false,
      closed() {},
    },
  });
  const renderer = createCloudSocketBridge(
    { kind: 'agent', url: policy.url, scope: policy.scope },
    {
      subscribe(callback) {
        receive = callback;
        return () => {
          receive = undefined;
        };
      },
      open: (input) => broker.open(31, input),
      send: (input) => broker.send(31, input),
      close: (input) => broker.close(31, input),
    },
    { socketId: 'cloud-native-order-0001' }
  );
  const messages = [];
  renderer.onmessage = (event) => messages.push(event.data);
  renderer.onopen = () => renderer.send('{"type":"send_message"}');
  await tick();
  socket.open('memstack.auth');
  socket.message('{"type":"connected"}');
  socket.message('{"type":"ready"}');
  await tick();
  assert.equal(renderer.readyState, 0);
  assert.deepEqual(order, []);
  discovery.resolve();
  await tick();
  assert.equal(renderer.readyState, 1);
  assert.deepEqual(order, ['open', 'message', 'message']);
  assert.deepEqual(messages, ['{"type":"connected"}', '{"type":"ready"}']);
  assert.deepEqual(
    socket.sent.map((value) => JSON.parse(value).type),
    ['computer_use_device', 'send_message']
  );
  assert.deepEqual(socket.closeCalls, []);
  renderer.close();
});

test('failed optional discovery still opens ordinary chat before queued messages', async () => {
  const { DesktopCloudSocketBroker } = require(compiledModule);
  const discovery = deferred();
  const socket = fakeSocket(policy.url, policy.protocols);
  const events = [];
  const broker = new DesktopCloudSocketBroker({
    authorize: async () => ({ ...policy, kind: 'agent' }),
    createSocket: () => socket,
    emit: (_owner, event) => events.push(event.type),
    computerUse: {
      opened: () => discovery.promise,
      receive: () => false,
      closed() {},
    },
  });
  await broker.open(32, {
    socketId: 'cloud-native-fail-0001',
    request: { kind: 'agent', url: policy.url, scope: policy.scope },
  });
  socket.open('memstack.auth');
  socket.message('{"type":"connected"}');
  discovery.reject(new Error('native unavailable'));
  await tick();
  assert.deepEqual(events, ['open', 'message']);
  broker.cancelOwner(32);
});

test('closing during discovery discards queued frames and suppresses late Open', async () => {
  const { DesktopCloudSocketBroker } = require(compiledModule);
  const discovery = deferred();
  const socket = fakeSocket(policy.url, policy.protocols);
  const events = [];
  let closed = 0;
  const broker = new DesktopCloudSocketBroker({
    authorize: async () => ({ ...policy, kind: 'agent' }),
    createSocket: () => socket,
    emit: (_owner, event) => events.push(event.type),
    computerUse: {
      opened: () => discovery.promise,
      receive: () => false,
      closed() {
        closed++;
      },
    },
  });
  await broker.open(33, {
    socketId: 'cloud-native-close-0001',
    request: { kind: 'agent', url: policy.url, scope: policy.scope },
  });
  socket.open('memstack.auth');
  socket.message('{"type":"connected"}');
  await tick();
  broker.cancelOwner(33);
  discovery.resolve();
  await tick();
  assert.deepEqual(events, ['close']);
  assert.equal(closed, 1);
  assert.equal(broker.activeCount, 0);
});

test('frames buffered during discovery retain frame and aggregate limits', async () => {
  const { DesktopCloudSocketBroker } = require(compiledModule);
  for (const payloads of [['{"a":"x"}'], ['{"a":1}', '{"a":2}', '{"a":3}']]) {
    const discovery = deferred();
    const socket = fakeSocket(policy.url, policy.protocols);
    const events = [];
    const broker = new DesktopCloudSocketBroker({
      authorize: async () => ({
        ...policy,
        kind: 'agent',
        limits: {
          ...policy.limits,
          max_frame_bytes: 8,
          max_aggregate_bytes: 16,
        },
      }),
      createSocket: () => socket,
      emit: (_owner, event) => events.push(event.type),
      computerUse: {
        opened: () => discovery.promise,
        receive: () => false,
        closed() {},
      },
    });
    await broker.open(34, {
      socketId: 'cloud-native-limit-0001',
      request: { kind: 'agent', url: policy.url, scope: policy.scope },
    });
    socket.open('memstack.auth');
    for (const payload of payloads) socket.message(payload);
    assert.equal(socket.closeCalls.at(-1).code, 1009);
    assert.equal(broker.activeCount, 0);
    discovery.resolve();
    await tick();
    assert.deepEqual(events, ['error', 'close']);
  }
});

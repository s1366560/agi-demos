import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const kernel = require('@agistack/plugin-runtime');
const {
  createDesktopVoiceSessionOperationsV2: createOps,
  desktopVoiceSessionAuthorityDefinitionV2: definition,
} = require(`${ROOT}/src/plugins/desktopVoiceSessionAuthorityModuleV2.js`);
const { acquireDesktopRendererServiceOperationLeaseV2: admit } = require(
  `${ROOT}/src/plugins/desktopRendererServiceOperationLeaseV2.js`,
);
const previousWindow = globalThis.window;
const previousDocument = globalThis.document;
const previousSocket = globalThis.WebSocket;
afterEach(() => {
  globalThis.window = previousWindow;
  globalThis.document = previousDocument;
  globalThis.WebSocket = previousSocket;
});
const config = () => ({
  mode: 'cloud',
  apiBaseUrl: 'https://example.invalid',
  apiKey: 'test-credential',
  localApiToken: '',
  deviceAuthorizationBaseUrl: '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  workspaceRoot: '',
});
const connection = () => ({
  availability: 'available',
  transport: 'web',
  url: 'wss://example.invalid/api/v1/voice/chat?project_id=project-1&conversation_id=conversation-1',
  protocols: ['memstack.auth', 'test-credential'],
  scopeKey: [
    'https://example.invalid',
    'tenant-1',
    'project-1',
    'workspace-1',
    'conversation-1',
  ].join('\u0000'),
  scope: {
    tenant_id: 'tenant-1',
    project_id: 'project-1',
    workspace_id: 'workspace-1',
    conversation_id: 'conversation-1',
  },
});
const input = () => ({
  config: config(),
  connection: connection(),
  signal: new AbortController().signal,
});
function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function fakeRuntime() {
  const counts = {
    permission: 0,
    capture: 0,
    socket: 0,
    context: 0,
    close: 0,
    stop: 0,
    disconnect: 0,
    send: 0,
  };
  const sockets = [];
  const track = Object.freeze({
    stop() {
      counts.stop++;
    },
  });
  const stream = Object.freeze({ getTracks: () => [track] });
  const context = () => ({
    sampleRate: 48000,
    state: 'running',
    currentTime: 0,
    destination: {},
    audioWorklet: { addModule: async () => undefined },
    createMediaStreamSource: () => ({
      connect() {},
      disconnect() {
        counts.disconnect++;
      },
    }),
    resume: async () => undefined,
    decodeAudioData: async () => ({ duration: 1 }),
    createBufferSource: () => ({
      buffer: null,
      onended: null,
      connect() {},
      start() {},
      stop() {
        counts.stop++;
      },
      disconnect() {
        counts.disconnect++;
      },
    }),
    close: async () => {
      counts.close++;
    },
  });
  const runtime = {
    requestMicrophoneAccess: async () => {
      counts.permission++;
      return true;
    },
    getUserMedia: async () => {
      counts.capture++;
      return stream;
    },
    createSocket() {
      counts.socket++;
      const socket = {
        readyState: 1,
        onopen: null,
        onmessage: null,
        onerror: null,
        onclose: null,
        send() {
          counts.send++;
        },
        close() {
          counts.close++;
        },
      };
      sockets.push(socket);
      return socket;
    },
    createAudioContext() {
      counts.context++;
      return context();
    },
    createCaptureContext() {
      counts.context++;
      return context();
    },
    createPlaybackContext() {
      counts.context++;
      return context();
    },
    createWorkletNode: () => ({
      port: { onmessage: null, postMessage() {} },
      disconnect() {
        counts.disconnect++;
      },
    }),
    workletModuleUrl: 'https://example.invalid/audio-processor.js',
    socketOpenState: 1,
  };
  return { runtime, counts, stream, sockets };
}
function fixture(custom) {
  const f = fakeRuntime();
  const state = { acquire: 0, release: 0, create: 0 };
  const service = custom ?? {
    createRuntime(prepared, kind) {
      state.create++;
      state.prepared = prepared;
      state.kind = kind;
      return f.runtime;
    },
  };
  const lease = {
    status: 'accepted',
    digest: 'sha256:fixture',
    useService: (callback) => callback(service),
    release: async () => {
      state.release++;
    },
  };
  const actions = {
    acquireOperationLease() {
      throw new Error('fallback');
    },
    acquireServiceOperationLease: async (request) => {
      state.acquire++;
      state.request = request;
      return lease;
    },
  };
  return { ...f, state, lease, actions, service, ops: createOps(() => actions) };
}
test('voice acquires exact session before any resource and retains lease until both runtime modes stop', async () => {
  for (const method of ['acquireTranscription', 'acquireCall']) {
    const f = fixture();
    const session = await f.ops[method](input());
    assert.deepEqual(f.state.request.scope, {
      kind: 'session',
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      session_id: 'conversation-1',
    });
    assert.equal(f.state.release, 0);
    assert.equal(f.counts.permission, 0);
    assert.equal(f.counts.socket, 0);
    await session.runtime.requestMicrophoneAccess();
    const stream = await session.runtime.getUserMedia();
    session.runtime.createSocket(connection().url, connection().protocols);
    const ctx =
      method === 'acquireCall'
        ? session.runtime.createPlaybackContext()
        : session.runtime.createAudioContext();
    void ctx.close();
    stream.getTracks()[0].stop();
    await session.release();
    await session.release();
    assert.equal(f.state.release, 1);
    assert.equal(f.counts.stop, 1);
    assert.equal(f.counts.close, 2);
    assert.throws(() => session.runtime.createSocket(connection().url, connection().protocols));
  }
});
test('voice freezes connection config and protocols before delayed admission', async () => {
  const f = fixture();
  const gate = deferred();
  f.actions.acquireServiceOperationLease = async () => {
    await gate.promise;
    return f.lease;
  };
  const request = input();
  const pending = f.ops.acquireCall(request);
  request.config.tenantId = 'other';
  request.connection.scope.conversation_id = 'other';
  request.connection.protocols[1] = 'changed';
  gate.resolve();
  const session = await pending;
  assert.equal(f.state.prepared.config.tenantId, 'tenant-1');
  assert.ok(Object.isFrozen(f.state.prepared.connection.scope));
  session.runtime.createSocket(connection().url, connection().protocols);
  assert.throws(() =>
    session.runtime.createSocket(request.connection.url, request.connection.protocols),
  );
  await session.release();
});
test('voice rejects crossed scope URL protocol and preabort before acquiring', async () => {
  for (const mutate of [
    (r) => (r.connection.scope.project_id = 'other'),
    (r) => (r.connection.scope.workspace_id = 'other'),
    (r) => (r.connection.url += '&extra=1'),
    (r) => (r.connection.protocols[1] = 'other'),
    (r) => (r.config.tenantId = ''),
    (r) => {
      const c = new AbortController();
      c.abort();
      r.signal = c.signal;
    },
  ]) {
    const f = fixture();
    const request = input();
    mutate(request);
    await assert.rejects(f.ops.acquireCall(request));
    assert.equal(f.state.acquire, 0);
  }
});
test('Local unavailable is decided inside admitted service without resource creation', async () => {
  const f = fixture();
  const request = input();
  request.config.mode = 'local';
  request.connection = { availability: 'local_runtime' };
  await assert.rejects(
    f.ops.acquireCall(request),
    (e) => e.code === 'desktop_voice_session_unavailable',
  );
  assert.equal(f.state.acquire, 1);
  assert.equal(f.state.release, 1);
  assert.equal(f.state.create, 0);
});
test('native transport cannot be spoofed as web to bypass the vault socket bridge', async () => {
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: { invoke: async () => undefined },
      events: { onCloudSocketEvent: () => () => {} },
    },
  };
  const f = fixture();
  await assert.rejects(
    f.ops.acquireCall(input()),
    (e) => e.code === 'desktop_voice_session_transport_mismatch',
  );
  assert.equal(f.state.acquire, 0);
});
test('frozen runtime and resources work through the retained boundary', async () => {
  const f = fixture();
  Object.freeze(f.runtime);
  const session = await f.ops.acquireCall(input());
  assert.equal(await session.runtime.requestMicrophoneAccess(), true);
  (await session.runtime.getUserMedia()).getTracks()[0].stop();
  await session.release();
  assert.equal(f.counts.stop, 1);
});
test('release drains a late permission prompt and allows no following resources', async () => {
  const f = fixture();
  const gate = deferred();
  f.runtime.requestMicrophoneAccess = () => gate.promise;
  const session = await f.ops.acquireCall(input());
  const request = session.runtime.requestMicrophoneAccess();
  const rejected = assert.rejects(request);
  const releasing = session.release();
  await Promise.resolve();
  assert.equal(f.state.release, 0);
  assert.throws(() => session.runtime.createCaptureContext());
  gate.resolve(true);
  await rejected;
  await releasing;
  assert.equal(f.state.release, 1);
});
test('late getUserMedia tracks are stopped before the generation lease releases', async () => {
  const f = fixture();
  const gate = deferred();
  f.runtime.getUserMedia = () => gate.promise;
  const session = await f.ops.acquireCall(input());
  const capture = session.runtime.getUserMedia();
  const rejected = assert.rejects(capture);
  const releasing = session.release();
  await Promise.resolve();
  assert.equal(f.state.release, 0);
  gate.resolve(f.stream);
  await rejected;
  await releasing;
  assert.equal(f.counts.stop, 1);
  assert.equal(f.state.release, 1);
});
test('controller fire-and-forget context close is drained and its failure remains observable', async () => {
  const f = fixture();
  const gate = deferred();
  const failure = new Error('context close failed');
  f.runtime.createAudioContext = () => ({
    close: () =>
      gate.promise.then(() => {
        throw failure;
      }),
  });
  const session = await f.ops.acquireTranscription(input());
  const ctx = session.runtime.createAudioContext();
  void ctx.close().catch(() => undefined);
  const release = session.release();
  const rejected = assert.rejects(release, (e) => e === failure);
  await Promise.resolve();
  assert.equal(f.state.release, 0);
  gate.resolve();
  await rejected;
  assert.equal(f.state.release, 1);
});
test('abort disposes socket callbacks and denies escaped audio or socket calls', async () => {
  const f = fixture();
  const c = new AbortController();
  const session = await f.ops.acquireCall({ ...input(), signal: c.signal });
  const socket = session.runtime.createSocket(connection().url, connection().protocols);
  let events = 0;
  socket.onmessage = () => {
    events++;
  };
  const saved = f.sockets[0].onmessage;
  c.abort();
  saved({ data: 'late' });
  await session.release();
  assert.equal(events, 0);
  assert.equal(f.state.release, 1);
  assert.throws(() => socket.send('late'));
  assert.throws(() => session.runtime.createPlaybackContext());
});
test('callback reuse and escaped callback cannot create a second session', async () => {
  const f = fixture();
  let callback;
  f.lease.useService = (cb) => {
    callback = cb;
    cb(f.service);
  };
  const session = await f.ops.acquireCall(input());
  assert.throws(() => callback(f.service));
  await session.release();
  assert.throws(() => callback(f.service));
  assert.equal(f.state.create, 1);
});
test('abort during admission releases accepted lease without creating runtime', async () => {
  const f = fixture();
  const gate = deferred();
  const c = new AbortController();
  f.actions.acquireServiceOperationLease = async () => {
    await gate.promise;
    return f.lease;
  };
  const request = f.ops.acquireCall({ ...input(), signal: c.signal });
  c.abort();
  gate.resolve();
  await assert.rejects(request);
  assert.equal(f.state.create, 0);
  assert.equal(f.state.release, 1);
});
test('provider primary error survives release failure and malformed services do not fall back', async () => {
  const primary = new Error('provider failed');
  const f = fixture({
    createRuntime() {
      throw primary;
    },
  });
  f.lease.release = async () => {
    throw new Error('secondary');
  };
  await assert.rejects(f.ops.acquireCall(input()), (e) => e === primary);
  const invalid = fixture({});
  await assert.rejects(invalid.ops.acquireCall(input()));
  assert.equal(invalid.state.release, 1);
  assert.equal(invalid.counts.socket, 0);
});
function definitions() {
  return [
    ...kernel.createDesktopRendererDefinitionsV2(),
    ...readdirSync(`${ROOT}/src/plugins`)
      .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
      .flatMap((name) =>
        Object.values(require(`${ROOT}/src/plugins/${name}`)).filter(
          (value) => value?.moduleRef && typeof value.apply === 'function',
        ),
      ),
  ];
}
function profile() {
  return JSON.parse(
    readFileSync(
      new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
      'utf8',
    ),
  );
}
test('real Loader disable forbids voice resources while admitted old HMR session drains independently', async () => {
  const manager = new kernel.GenerationManagerV2();
  const loader = new kernel.LoaderV2(definitions(), 'desktop-renderer');
  globalThis.document = { baseURI: 'https://example.invalid/' };
  let sockets = 0;
  let closes = 0;
  globalThis.WebSocket = class {
    readyState = 1;
    close() {
      closes++;
    }
    constructor() {
      sockets++;
    }
  };
  const actions = {
    acquireOperationLease() {
      throw new Error('fallback');
    },
    acquireServiceOperationLease: (request) =>
      admit(manager.current, request, (g) => manager.acquire(g)),
  };
  try {
    const old = await loader.stage(profile());
    await manager.publish(old);
    const ops = createOps(() => actions);
    const session = await ops.acquireCall(input());
    session.runtime.createSocket(connection().url, connection().protocols);
    const disabled = profile();
    disabled.entries.find((entry) => entry.module_ref === definition.moduleRef).enabled = false;
    await manager.publish(await loader.stage(disabled));
    assert.equal(old.disposed, false);
    await assert.rejects(ops.acquireTranscription(input()));
    assert.equal(sockets, 1);
    await session.release();
    assert.equal(closes, 1);
    assert.equal(old.disposed, true);
    assert.equal(manager.current.leaseCount, 0);
  } finally {
    await manager.close();
  }
});

test('real native bridge release waits for late open then close IPC without web fallback', async () => {
  const open = deferred();
  const close = deferred();
  let closes = 0;
  let unsubscribed = 0;
  globalThis.document = { baseURI: 'https://example.invalid/' };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      runtime: 'electron',
      core: {
        invoke: async (command) => {
          if (command === 'cloud_socket_open') await open.promise;
          if (command === 'cloud_socket_close') {
            closes++;
            await close.promise;
          }
        },
      },
      events: {
        onCloudSocketEvent: () => () => {
          unsubscribed++;
        },
      },
    },
  };
  globalThis.WebSocket = class {
    constructor() {
      throw new Error('forbidden web fallback');
    }
  };
  const { createVoiceSessionRuntimeProjectionV2: createRuntime } = require(
    `${ROOT}/src/plugins/desktopVoiceSessionRuntimeProjectionV2.js`,
  );
  const f = fixture({ createRuntime });
  const request = input();
  request.connection.transport = 'electron';
  request.connection.protocols = [];
  const session = await f.ops.acquireCall(request);
  session.runtime.createSocket(request.connection.url, []);
  const releasing = session.release();
  await Promise.resolve();
  assert.equal(f.state.release, 0);
  assert.equal(closes, 0);
  open.resolve();
  await new Promise((done) => setImmediate(done));
  assert.equal(closes, 1);
  assert.equal(f.state.release, 0);
  close.resolve();
  await releasing;
  assert.equal(f.state.release, 1);
  assert.equal(unsubscribed, 1);
});

test('late playback decoding cannot create sources and release drains its completion', async () => {
  const f = fixture();
  const gate = deferred();
  let sources = 0;
  f.runtime.createPlaybackContext = () => ({
    decodeAudioData: () => gate.promise,
    createBufferSource: () => {
      sources++;
      return {};
    },
    close: async () => undefined,
  });
  const session = await f.ops.acquireCall(input());
  const ctx = session.runtime.createPlaybackContext();
  const decoded = ctx.decodeAudioData(new ArrayBuffer(1));
  const rejected = assert.rejects(decoded);
  const release = session.release();
  await Promise.resolve();
  assert.equal(f.state.release, 0);
  gate.resolve({ duration: 1 });
  await rejected;
  await release;
  assert.throws(() => ctx.createBufferSource());
  assert.equal(sources, 0);
});

test('cleanup failure does not skip other resources or mask itself with lease release failure', async () => {
  const failure = new Error('close failed');
  const f = fixture();
  f.runtime.createCaptureContext = () => ({
    close() {
      throw failure;
    },
  });
  f.lease.release = async () => {
    f.state.release++;
    throw new Error('lease release failed');
  };
  const session = await f.ops.acquireCall(input());
  session.runtime.createCaptureContext();
  await session.runtime.getUserMedia();
  session.runtime.createSocket(connection().url, connection().protocols);
  await assert.rejects(session.release(), (error) => error === failure);
  assert.equal(f.counts.stop, 1);
  assert.equal(f.counts.close, 1);
  assert.equal(f.state.release, 1);
});

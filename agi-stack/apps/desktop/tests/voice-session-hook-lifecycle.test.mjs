import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url),
  ts = require('typescript');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
};
const tick = () => new Promise(setImmediate);
function harness(kind = 'transcription') {
  let cursor = 0,
    effects = [];
  const slots = [];
  const writes = [];
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    useRef(value) {
      return (slots[cursor++] ??= { current: value });
    },
    useState(initial) {
      const i = cursor++;
      slots[i] ??= { value: typeof initial === 'function' ? initial() : initial };
      return [
        slots[i].value,
        (v) => {
          writes.push(i);
          slots[i].value = typeof v === 'function' ? v(slots[i].value) : v;
        },
      ];
    },
    useMemo(fn, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps)) slots[i] = { deps, value: fn() };
      return slots[i].value;
    },
    useCallback(fn, deps) {
      return react.useMemo(() => fn, deps);
    },
    useLayoutEffect(effect, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps))
        effects.push(() => {
          slots[i]?.cleanup?.();
          slots[i] = { deps, effect, cleanup: effect() };
        });
    },
  };
  const cache = new Map();
  function load(name) {
    if (cache.has(name)) return cache.get(name);
    const module = { exports: {} };
    cache.set(name, module.exports);
    const url = new URL(`../src/features/chat/${name}.ts`, import.meta.url);
    const code = ts.transpileModule(readFileSync(url, 'utf8'), {
      fileName: url.pathname,
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText;
    new Function('require', 'module', 'exports', code)(
      (name) =>
        name === 'react'
          ? react
          : name.startsWith('./useVoice')
            ? load(name.slice(2))
            : require(`/tmp/agistack-desktop-test-dist/src/features/chat/${name.slice(2)}.js`),
      module,
      module.exports,
    );
    return module.exports;
  }
  const events = [],
    sockets = [];
  const stream = {
    getTracks: () => [
      {
        stop() {
          events.push('track-stop');
        },
      },
    ],
  };
  const audio = () => ({
    sampleRate: 48000,
    state: 'running',
    audioWorklet: { async addModule() {} },
    createMediaStreamSource: () => ({
      connect() {},
      disconnect() {
        events.push('source-disconnect');
      },
    }),
    async close() {
      events.push('audio-close');
    },
  });
  const runtime = {
    async requestMicrophoneAccess() {
      events.push('permission');
      return true;
    },
    createSocket() {
      events.push('socket');
      const socket = {
        readyState: 0,
        onopen: null,
        onmessage: null,
        onerror: null,
        onclose: null,
        send() {},
        close() {
          events.push('socket-close');
          this.readyState = 3;
        },
      };
      sockets.push(socket);
      queueMicrotask(() => {
        socket.readyState = 1;
        socket.onopen?.();
      });
      return socket;
    },
    createAudioContext: audio,
    createCaptureContext: audio,
    createPlaybackContext: audio,
    createWorkletNode: () => ({
      port: { postMessage() {}, onmessage: null },
      disconnect() {
        events.push('worklet-disconnect');
      },
    }),
    async getUserMedia() {
      events.push('media');
      return stream;
    },
    workletModuleUrl: 'https://qa.test/audio.js',
    socketOpenState: 1,
  };
  const release = async () => {
    events.push('release');
  };
  const acquisitions = [];
  const operations = {
    async acquireTranscription(input) {
      acquisitions.push(input);
      return { runtime, release };
    },
    async acquireCall(input) {
      acquisitions.push(input);
      return { runtime, release };
    },
  };
  const params = {
    config: {
      mode: 'cloud',
      apiBaseUrl: 'https://qa.test',
      apiKey: '',
      tenantId: 't',
      projectId: 'p',
      workspaceId: 'w',
    },
    operations,
    connection: {
      availability: 'available',
      scopeKey: 't/p/w/c',
      url: 'wss://qa.test/api/v1/voice/chat',
      protocols: [],
    },
    onInterim: (text) => events.push('interim:' + text),
    onFinal: (text) => events.push('final:' + text),
  };
  const fn =
    kind === 'manager'
      ? () =>
          load('useVoiceSessionLeaseV2').useVoiceSessionLeaseV2(
            params.config,
            params.connection,
            params.operations,
            () => {},
          )
      : load(kind === 'call' ? 'useVoiceCall' : 'useVoiceTranscription')[
          kind === 'call' ? 'useVoiceCall' : 'useVoiceTranscription'
        ];
  let hook;
  function render(patch = {}) {
    Object.assign(params, patch);
    cursor = 0;
    hook = fn({ ...params });
    for (const effect of effects.splice(0)) effect();
    return hook;
  }
  function unmount() {
    for (const slot of slots) slot?.cleanup?.();
  }
  function strict() {
    unmount();
    for (const slot of slots) if (slot?.effect) slot.cleanup = slot.effect();
  }
  render();
  return {
    params,
    runtime,
    stream,
    operations,
    events,
    sockets,
    acquisitions,
    render,
    unmount,
    strict,
    writes,
    get hook() {
      return hook;
    },
  };
}
for (const kind of ['transcription', 'call']) {
  const start = (h) => (kind === 'call' ? h.hook.start() : h.hook.toggle());
  const stop = (h) => (kind === 'call' ? h.hook.end() : h.hook.stop());
  for (const transition of ['config', 'connection', 'operations', 'unmount', 'strict'])
    test(`${kind} pending lease after ${transition} releases without device access`, async () => {
      const h = harness(kind),
        pending = deferred();
      let signal;
      h.operations[kind === 'call' ? 'acquireCall' : 'acquireTranscription'] = (input) => {
        signal = input.signal;
        return pending.promise;
      };
      const started = start(h);
      await tick();
      assert.deepEqual(h.events, []);
      if (transition === 'config') h.render({ config: { ...h.params.config, projectId: 'other' } });
      if (transition === 'connection')
        h.render({ connection: { ...h.params.connection, scopeKey: 'other' } });
      if (transition === 'operations') h.render({ operations: { ...h.operations } });
      if (transition === 'unmount') h.unmount();
      if (transition === 'strict') h.strict();
      const before = h.writes.length;
      pending.resolve({ runtime: h.runtime, release: async () => h.events.push('release') });
      assert.equal(await started, false);
      assert.deepEqual(h.events, ['release']);
      assert.equal(signal.aborted, true);
      assert.equal(h.writes.length, before);
    });
  test(`${kind} acquires before microphone, streams with the real controller, stops before lease release`, async () => {
    const h = harness(kind);
    assert.equal(await start(h), true);
    h.render();
    assert.equal(h.acquisitions.length, 1);
    assert.ok(h.events.includes('media'));
    const socket = h.sockets[0];
    socket.onmessage({ data: JSON.stringify({ type: 'asr_final', text: 'hello' }) });
    h.render();
    if (kind === 'transcription') assert.ok(h.events.includes('final:hello'));
    else assert.equal(h.hook.transcript.asrFinal, 'hello');
    stop(h);
    await tick();
    assert.ok(h.events.indexOf('socket-close') < h.events.indexOf('release'));
    assert.equal(h.events.filter((x) => x === 'release').length, 1);
    assert.equal(h.acquisitions[0].signal.aborted, true);
  });
  test(`${kind} server failure after connection releases its lease and preserves error`, async () => {
    const h = harness(kind);
    await start(h);
    h.sockets[0].onmessage({ data: JSON.stringify({ type: 'error', message: 'failed' }) });
    await tick();
    h.render();
    assert.equal(h.hook.errorCode, 'service_error');
    assert.equal(h.events.filter((x) => x === 'release').length, 1);
  });
  test(`${kind} unavailable authority never opens a microphone`, async () => {
    const h = harness(kind);
    h.operations[kind === 'call' ? 'acquireCall' : 'acquireTranscription'] = async () => {
      throw Error('module_disabled');
    };
    assert.equal(await start(h), false);
    h.render();
    assert.equal(h.hook.errorCode, 'connection_failed');
    assert.deepEqual(h.events, []);
  });
}
test('late unmute cannot update the replacement call', async () => {
  const h = harness('call');
  await h.hook.start();
  h.render();
  await h.hook.toggleMute();
  h.render();
  assert.equal(h.hook.isMuted, true);
  const pending = deferred();
  h.runtime.getUserMedia = () => pending.promise;
  const toggled = h.hook.toggleMute();
  await tick();
  h.render({ connection: { ...h.params.connection, scopeKey: 'next' } });
  const before = h.writes.length;
  pending.resolve(h.stream);
  assert.equal(await toggled, false);
  assert.equal(h.writes.length, before);
});
test('controller stop exception still aborts and releases lease', async () => {
  const h = harness('manager');
  const input = [];
  await h.hook.start(
    async (signal) => {
      input.push(signal);
      return { runtime: {}, release: async () => h.events.push('release') };
    },
    () => ({
      stop() {
        throw Error('stop');
      },
    }),
    async () => true,
  );
  const warn = console.warn;
  console.warn = () => {};
  try {
    await h.hook.stop();
  } finally {
    console.warn = warn;
  }
  assert.equal(input[0].aborted, true);
  assert.deepEqual(h.events, ['release']);
});
test('old start failure waiting for cleanup cannot reject into a newer same-context start', async () => {
  const h = harness('manager'),
    pending = deferred();
  const one = h.hook.start(
    async () => ({ runtime: {}, release: () => pending.promise }),
    () => ({ stop() {} }),
    async () => {
      throw Error('old-failure');
    },
  );
  await tick();
  const two = h.hook.start(
    async () => ({ runtime: {}, release: async () => {} }),
    () => ({ stop() {} }),
    async () => true,
  );
  pending.resolve();
  assert.equal(await one, false);
  assert.equal(await two, true);
  await h.hook.stop();
});

for (const kind of ['transcription', 'call']) {
  test(`${kind} revoked permission wait cannot open a socket after scope changed`, async () => {
    const h = harness(kind),
      permission = deferred();
    h.runtime.requestMicrophoneAccess = () => permission.promise;
    const started = kind === 'call' ? h.hook.start() : h.hook.toggle();
    await tick();
    h.render({ config: { ...h.params.config, tenantId: 'other' } });
    const before = h.writes.length;
    permission.resolve(true);
    assert.equal(await started, false);
    assert.ok(!h.events.includes('socket'));
    assert.ok(!h.events.includes('media'));
    assert.equal(h.events.filter((value) => value === 'release').length, 1);
    assert.equal(h.writes.length, before);
  });
}

test('controller uses the connection captured before awaiting its lease', async () => {
  const h = harness('call'),
    pending = deferred();
  let requestedUrl;
  const createSocket = h.runtime.createSocket;
  h.runtime.createSocket = (url, ...args) => {
    requestedUrl = url;
    return createSocket(url, ...args);
  };
  h.operations.acquireCall = () => pending.promise;
  const started = h.hook.start();
  await tick();
  const original = h.params.connection.url;
  h.params.connection.url = 'wss://mutated.invalid/voice';
  pending.resolve({ runtime: h.runtime, release: async () => {} });
  assert.equal(await started, true);
  assert.equal(requestedUrl, original);
  h.unmount();
});

test('lease release failure is handled and does not leave a rejecting cleanup promise', async () => {
  const h = harness('manager');
  await h.hook.start(
    async () => ({
      runtime: {},
      release: async () => {
        throw Error('cleanup');
      },
    }),
    () => ({
      stop() {
        h.events.push('stop');
      },
    }),
    async () => true,
  );
  const warnings = [];
  const warn = console.warn;
  console.warn = (...args) => warnings.push(args);
  try {
    await h.hook.stop();
  } finally {
    console.warn = warn;
  }
  assert.deepEqual(h.events, ['stop']);
  assert.deepEqual(warnings, [['Voice session lease cleanup failed']]);
});

test('production voice hooks require generation operations and contain no default device transport', () => {
  const read = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8');
  const panel = read('features/chat/ChatPanel.tsx');
  assert.match(panel, /voiceSessionOperations: DesktopVoiceSessionOperationsV2/u);
  assert.match(panel, /operations: voiceSessionOperations/u);
  assert.doesNotMatch(panel, /voiceCallRuntime\??:|voiceTranscriptionRuntime\??:/u);
  for (const name of ['useVoiceCall', 'useVoiceTranscription']) {
    const source = read(`features/chat/${name}.ts`);
    assert.match(source, /operations: DesktopVoiceSessionOperationsV2/u);
    assert.match(source, /config: DesktopRuntimeConfig \| null/u);
    assert.doesNotMatch(
      source,
      /new WebSocket|navigator\.mediaDevices|new AudioContext|createCloudSocketBridge|runtime\s*\?\?/u,
    );
  }
  const app = read('App.tsx');
  assert.match(app, /voiceSessionOperations: desktopVoiceSessionOperationsV2/u);
});

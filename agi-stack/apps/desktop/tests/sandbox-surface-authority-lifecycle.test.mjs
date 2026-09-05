import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
function harness(client) {
  const slots = [];
  let cursor = 0;
  let effects = [];
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    useState(value) {
      const i = cursor++;
      slots[i] ??= { value };
      return [
        slots[i].value,
        (v) => {
          slots[i].value = typeof v === 'function' ? v(slots[i].value) : v;
        },
      ];
    },
    useRef(value) {
      return (slots[cursor++] ??= { current: value });
    },
    useMemo(fn, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps)) slots[i] = { deps, value: fn() };
      return slots[i].value;
    },
    useCallback(fn, deps) {
      return react.useMemo(() => fn, deps);
    },
    useEffect(effect, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps))
        effects.push(() => {
          slots[i]?.cleanup?.();
          slots[i] = { deps, effect, cleanup: effect() };
        });
    },
  };
  const cache = new Map();
  function load(url) {
    if (cache.has(url.href)) return cache.get(url.href);
    const module = { exports: {} };
    cache.set(url.href, module.exports);
    const code = ts.transpileModule(readFileSync(url, 'utf8'), {
      fileName: url.pathname,
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
      },
    }).outputText;
    new Function('require', 'module', 'exports', code)(
      (name) => {
        if (name === 'react') return react;
        if (name === '../../i18n')
          return { useI18n: () => ({ t: (key, args) => `${key}:${JSON.stringify(args)}` }) };
        return load(new URL(`${name}.ts`, url));
      },
      module,
      module.exports,
    );
    return module.exports;
  }
  const { useSandboxRuntimeSurface } = load(
    new URL('../src/features/sandbox/useSandboxRuntimeSurface.ts', import.meta.url),
  );
  let props = { config: { projectId: 'p1' }, enabled: true, client };
  function render(next = {}) {
    props = { ...props, ...next };
    cursor = 0;
    effects = [];
    const result = useSandboxRuntimeSurface(props.config, props.enabled, props.client);
    for (const effect of effects) effect();
    return result;
  }
  return {
    render,
    unmount() {
      for (const slot of slots) slot?.cleanup?.();
    },
    replay() {
      for (const slot of slots)
        if (slot?.effect) {
          slot.cleanup?.();
          slot.cleanup = slot.effect();
        }
    },
  };
}

const capabilities = {
  files: { availability: 'available' },
  kasm_vnc: { availability: 'available' },
};
const tick = async () => {
  await Promise.resolve();
  await Promise.resolve();
};
function fixture(overrides = {}) {
  return { loadCapabilities: async () => capabilities, ...overrides };
}
function session() {
  let releases = 0;
  return {
    value: {
      descriptor: {},
      frame_url: 'https://example.invalid/frame',
      release: async () => {
        releases++;
      },
    },
    releases: () => releases,
  };
}
for (const interruption of ['context', 'client', 'unmount', 'disabled']) {
  test(`${interruption} aborts remote start and releases its late descriptor`, async () => {
    const pending = deferred();
    let signal;
    const client = fixture({
      openRemoteDesktop: (_caps, _request, value) => {
        signal = value;
        return pending.promise;
      },
    });
    const h = harness(client);
    h.render();
    await tick();
    const operation = h.render().startRemoteDesktop();
    if (interruption === 'context') h.render({ config: { projectId: 'p2' } });
    else if (interruption === 'client') h.render({ client: fixture() });
    else if (interruption === 'disabled') h.render({ enabled: false });
    else h.unmount();
    assert.equal(signal.aborted, true);
    const ready = session();
    pending.resolve({ status: 'ready', value: ready.value });
    await operation;
    assert.equal(ready.releases(), 1);
    if (interruption !== 'unmount') assert.equal(h.render().remoteDesktopSession, null);
  });
}
test('repeated remote starts abort the older operation; replacement and unmount release retained leases once', async () => {
  const waits = [deferred(), deferred(), deferred()];
  const signals = [];
  let count = 0;
  const h = harness(
    fixture({
      openRemoteDesktop: (_caps, _request, signal) => {
        signals.push(signal);
        return waits[count++].promise;
      },
    }),
  );
  h.render();
  await tick();
  const api = h.render();
  const first = api.startRemoteDesktop();
  const second = api.startRemoteDesktop();
  assert.equal(signals[0].aborted, true);
  const old = session();
  waits[0].resolve({ status: 'ready', value: old.value });
  await first;
  assert.equal(old.releases(), 1);
  const active = session();
  waits[1].resolve({ status: 'ready', value: active.value });
  await second;
  assert.equal(h.render().remoteDesktopSession, active.value);
  const third = h.render().startRemoteDesktop();
  await tick();
  assert.equal(active.releases(), 1);
  const next = session();
  waits[2].resolve({ status: 'ready', value: next.value });
  await third;
  h.unmount();
  assert.equal(next.releases(), 1);
});
for (const method of ['listFiles', 'readFile', 'downloadFile']) {
  test(`${method} forwards scope/cancellation and rejects late file results`, async () => {
    const pending = deferred();
    let signal;
    let calls = 0;
    const h = harness(
      fixture({
        [method]: (caps, request, value) => {
          assert.equal(caps, capabilities);
          assert.equal(request.path, '/workspace');
          signal = value;
          calls++;
          return pending.promise;
        },
      }),
    );
    h.render();
    await tick();
    const client = h.render().fileClient;
    const op = client[method]({ path: '/workspace' });
    h.render({ config: { projectId: 'p2' } });
    assert.equal(signal.aborted, true);
    pending.resolve({ status: 'ready', value: {} });
    await assert.rejects(op, { name: 'AbortError' });
    await assert.rejects(client[method]({ path: '/workspace' }), { name: 'AbortError' });
    assert.equal(calls, 1);
  });
}
test('StrictMode setup replay uses a fresh capability request and ignores old success', async () => {
  const waits = [deferred(), deferred()];
  const signals = [];
  let count = 0;
  const h = harness(
    fixture({
      loadCapabilities: (signal) => {
        signals.push(signal);
        return waits[count++].promise;
      },
    }),
  );
  h.render();
  h.replay();
  assert.equal(signals[0].aborted, true);
  assert.equal(signals[1].aborted, false);
  waits[0].resolve({ obsolete: true });
  await tick();
  assert.equal(h.render().capabilities, null);
  waits[1].resolve(capabilities);
  await tick();
  assert.equal(h.render().capabilities, capabilities);
  h.unmount();
  assert.equal(signals[1].aborted, true);
});

test('file requests honor caller abort and preserve same-context successful results', async () => {
  const pending = deferred();
  let signal;
  const result = { status: 'ready', value: { path: '/workspace' } };
  const h = harness(
    fixture({
      listFiles: (_caps, _request, linked) => {
        signal = linked;
        return pending.promise;
      },
      readFile: async () => result,
    }),
  );
  h.render();
  await tick();
  const api = h.render();
  assert.equal(await api.fileClient.readFile({ path: '/workspace' }), result);
  const controller = new AbortController();
  const operation = api.fileClient.listFiles({ path: '/workspace' }, controller.signal);
  controller.abort();
  assert.equal(signal.aborted, true);
  pending.resolve(result);
  await assert.rejects(operation, { name: 'AbortError' });
  h.unmount();
});

test('remote unavailable and failures retain their existing visible states', async () => {
  let fail = false;
  const h = harness(
    fixture({
      openRemoteDesktop: async () => {
        if (fail) throw new Error('request failed');
        return { status: 'unavailable', reason_code: 'remote_desktop_unavailable' };
      },
    }),
  );
  h.render();
  await tick();
  await h.render().startRemoteDesktop();
  assert.equal(h.render().remoteDesktopStatus, 'unavailable');
  assert.equal(h.render().remoteDesktopReason, 'remote_desktop_unavailable');
  fail = true;
  await h.render().startRemoteDesktop();
  assert.equal(h.render().remoteDesktopStatus, 'error');
  assert.equal(h.render().remoteDesktopReason, 'kasm_remote_desktop_request_failed');
  h.unmount();
});

test('replacement lease release rejection produces an error and does not open a new session', async () => {
  let calls = 0;
  let releases = 0;
  const h = harness(
    fixture({
      openRemoteDesktop: async () => {
        calls++;
        return {
          status: 'ready',
          value: {
            descriptor: {},
            frame_url: 'https://example.invalid/frame',
            release: async () => {
              releases++;
              throw new Error('release failed');
            },
          },
        };
      },
    }),
  );
  h.render();
  await tick();
  await h.render().startRemoteDesktop();
  await h.render().startRemoteDesktop();
  assert.equal(h.render().remoteDesktopStatus, 'error');
  assert.equal(h.render().remoteDesktopReason, 'sandbox_remote_desktop_lease_release_failed');
  assert.equal(h.render().remoteDesktopSession, null);
  assert.equal(calls, 1);
  assert.equal(releases, 1);
  h.unmount();
});

test('cleanup handles rejected lease release without an unhandled promise or stale UI callback', async () => {
  let releases = 0;
  const warnings = [];
  const warn = console.warn;
  const h = harness(
    fixture({
      openRemoteDesktop: async () => ({
        status: 'ready',
        value: {
          descriptor: {},
          frame_url: 'https://example.invalid/frame',
          release: async () => {
            releases++;
            throw new Error('release failed');
          },
        },
      }),
    }),
  );
  h.render();
  await tick();
  await h.render().startRemoteDesktop();
  try {
    console.warn = (message) => warnings.push(message);
    h.unmount();
    await tick();
    assert.equal(releases, 1);
    assert.deepEqual(warnings, ['sandbox_remote_desktop_lease_release_failed']);
  } finally {
    console.warn = warn;
  }
});

for (const [mode, rootPath] of [
  ['local', '/workspace'],
  ['cloud', '/'],
]) {
  test(`${mode} runtime passes its real file root through SessionSandboxTools to the browser`, async () => {
    const h = harness(fixture());
    h.render({ config: { mode, projectId: 'p1' } });
    await tick();
    const runtime = h.render();
    assert.equal(runtime.fileRootPath, rootPath);
    const module = { exports: {} };
    const Browser = () => null;
    const source = readFileSync(
      new URL('../src/features/sandbox/SessionSandboxTools.tsx', import.meta.url),
      'utf8',
    );
    const code = ts.transpileModule(source, {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
      },
    }).outputText;
    let state = 0;
    new Function('require', 'module', 'exports', code)(
      (name) => {
        if (name === 'react')
          return {
            useState: () => [state++ === 0 ? 'files' : null, () => {}],
            useLayoutEffect: () => {},
          };
        if (name === 'react/jsx-runtime')
          return {
            jsx: (type, props) => ({ type, props }),
            jsxs: (type, props) => ({ type, props }),
          };
        if (name === '../../i18n') return { useI18n: () => ({ t: (key) => key }) };
        if (name === './SandboxFileBrowser') return { SandboxFileBrowser: Browser };
        return {};
      },
      module,
      module.exports,
    );
    const tree = module.exports.SessionSandboxTools({ runtime });
    function find(node) {
      if (!node || typeof node !== 'object') return null;
      if (node.type === Browser) return node;
      const children = node.props?.children;
      for (const child of Array.isArray(children) ? children : [children]) {
        const found = find(child);
        if (found) return found;
      }
      return null;
    }
    const browser = find(tree);
    assert.ok(browser);
    assert.equal(browser.props.rootPath, rootPath);
    assert.equal(browser.props.client, runtime.fileClient);
    h.unmount();
  });
}

test('surface stop is stable, aborts pending starts, and releases late descriptors', async () => {
  const wait = deferred();
  let signal;
  const h = harness(
    fixture({
      openRemoteDesktop: (_caps, _request, linked) => {
        signal = linked;
        return wait.promise;
      },
    }),
  );
  h.render();
  await tick();
  const api = h.render();
  assert.equal(h.render().stopRemoteDesktop, api.stopRemoteDesktop);
  const start = api.startRemoteDesktop();
  await api.stopRemoteDesktop();
  assert.equal(signal.aborted, true);
  assert.equal(h.render().remoteDesktopStatus, 'idle');
  const late = session();
  wait.resolve({ status: 'ready', value: late.value });
  await start;
  assert.equal(late.releases(), 1);
  assert.equal(h.render().remoteDesktopSession, null);
  h.unmount();
});

test('stop releases an active descriptor once; an old context stop cannot clear a new session', async () => {
  const values = [session(), session()];
  let calls = 0;
  const h = harness(
    fixture({ openRemoteDesktop: async () => ({ status: 'ready', value: values[calls++].value }) }),
  );
  h.render();
  await tick();
  const first = h.render();
  await first.startRemoteDesktop();
  await first.stopRemoteDesktop();
  await first.stopRemoteDesktop();
  assert.equal(values[0].releases(), 1);
  h.render({ config: { projectId: 'new' } });
  await tick();
  await h.render().startRemoteDesktop();
  await first.stopRemoteDesktop();
  assert.equal(h.render().remoteDesktopSession, values[1].value);
  assert.equal(values[1].releases(), 0);
  h.unmount();
  assert.equal(values[1].releases(), 1);
});

test('remote component cleanup invokes the required stop callback when its pane unmounts', async () => {
  const callbacks = [];
  let stops = 0;
  const module = { exports: {} };
  const code = ts.transpileModule(
    readFileSync(
      new URL('../src/features/sandbox/RemoteDesktopSurface.tsx', import.meta.url),
      'utf8',
    ),
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
      },
    },
  ).outputText;
  new Function('require', 'module', 'exports', code)(
    (name) => {
      if (name === 'react')
        return {
          useEffect: (fn) => callbacks.push(fn),
          useRef: (value) => ({ current: value }),
          useState: (value) => [value, () => {}],
          useCallback: (fn) => fn,
        };
      if (name === 'react/jsx-runtime')
        return {
          jsx: (type, props) => ({ type, props }),
          jsxs: (type, props) => ({ type, props }),
        };
      if (name === '../../i18n') return { useI18n: () => ({ t: (key) => key }) };
      return {};
    },
    module,
    module.exports,
  );
  module.exports.RemoteDesktopSurface({
    capability: { availability: 'unavailable' },
    session: null,
    status: 'idle',
    onStop: async () => {
      stops++;
    },
  });
  // This is the actual component's onStop effect; other effects require the browser DOM.
  const cleanup = callbacks[0]();
  assert.equal(stops, 0);
  cleanup();
  await tick();
  assert.equal(stops, 1);
});

test('SessionSandboxTools forwards stop to the desktop child and removes that child when switching to files', () => {
  let surface = 'desktop';
  let state = 0;
  const Remote = () => null;
  const Browser = () => null;
  const stop = async () => {};
  const module = { exports: {} };
  const code = ts.transpileModule(
    readFileSync(
      new URL('../src/features/sandbox/SessionSandboxTools.tsx', import.meta.url),
      'utf8',
    ),
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.ReactJSX,
      },
    },
  ).outputText;
  new Function('require', 'module', 'exports', code)(
    (name) => {
      if (name === 'react')
        return {
          useState: () =>
            state++ === 0
              ? [
                  surface,
                  (value) => {
                    surface = value;
                  },
                ]
              : [null, () => {}],
          useLayoutEffect: () => {},
        };
      if (name === 'react/jsx-runtime')
        return {
          jsx: (type, props) => ({ type, props }),
          jsxs: (type, props) => ({ type, props }),
        };
      if (name === '../../i18n') return { useI18n: () => ({ t: (key) => key }) };
      if (name === './RemoteDesktopSurface') return { RemoteDesktopSurface: Remote };
      if (name === './SandboxFileBrowser') return { SandboxFileBrowser: Browser };
      return {};
    },
    module,
    module.exports,
  );
  const runtime = {
    capabilityStatus: 'ready',
    remoteDesktopCapability: capabilities.kasm_vnc,
    filesCapability: capabilities.files,
    fileClient: {},
    fileRootPath: '/workspace',
    stopRemoteDesktop: stop,
  };
  function walk(node, match) {
    if (!node || typeof node !== 'object') return null;
    if (match(node)) return node;
    for (const child of [].concat(node.props?.children ?? [])) {
      const result = walk(child, match);
      if (result) return result;
    }
    return null;
  }
  const initial = module.exports.SessionSandboxTools({ runtime });
  assert.equal(walk(initial, (node) => node.type === Remote).props.onStop, stop);
  const filesButton = walk(
    initial,
    (node) => node.props?.role === 'tab' && node.props?.children?.includes('sandbox.filesTitle'),
  );
  assert.ok(filesButton);
  filesButton.props.onClick();
  state = 0;
  const files = module.exports.SessionSandboxTools({ runtime });
  assert.equal(
    walk(files, (node) => node.type === Remote),
    null,
  );
  assert.ok(walk(files, (node) => node.type === Browser));
});

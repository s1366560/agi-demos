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
const snapshot = (enabled) => ({
  runtimeStatus: { config: { browser_bridge: { enabled } } },
  bridgeStatus: { enabled, brokerConnected: false },
});
function harness() {
  let cursor = 0,
    effects = [];
  const slots = [],
    writes = [],
    timers = new Map();
  let nextTimer = 0;
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    useRef: (value) => (slots[cursor++] ??= { current: value }),
    useState(initial) {
      const i = cursor++;
      slots[i] ??= { value: typeof initial === 'function' ? initial() : initial };
      return [
        slots[i].value,
        (value) => {
          writes.push(i);
          slots[i].value = typeof value === 'function' ? value(slots[i].value) : value;
        },
      ];
    },
    useMemo(make, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps)) slots[i] = { deps, value: make() };
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
          slots[i] = { deps, cleanup: effect() };
        });
    },
  };
  const source = readFileSync(
    new URL('../src/features/settings/useBrowserBridgeManagementV2.ts', import.meta.url),
    'utf8',
  );
  const module = { exports: {} };
  new Function(
    'require',
    'module',
    'exports',
    'setTimeout',
    'clearTimeout',
    ts.transpileModule(source, {
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    }).outputText,
  )(
    (name) => {
      assert.equal(name, 'react');
      return react;
    },
    module,
    module.exports,
    (fn) => {
      timers.set(++nextTimer, fn);
      return nextTimer;
    },
    (id) => timers.delete(id),
  );
  const hook = module.exports.useBrowserBridgeManagementV2;
  return {
    writes,
    timers,
    render(client, config) {
      cursor = 0;
      const result = hook(client, config);
      const pending = effects;
      effects = [];
      pending.forEach((fn) => fn());
      return result;
    },
    unmount() {
      slots.forEach((slot) => slot?.cleanup?.());
    },
    poll() {
      const pending = [...timers.values()];
      timers.clear();
      pending.forEach((fn) => fn());
    },
  };
}
function client() {
  const calls = [];
  return {
    calls,
    loadSnapshot: async (signal) => {
      calls.push(['load', signal]);
      return snapshot(false);
    },
    setEnabled: async (value, signal) => {
      calls.push(['enabled', signal, value]);
      return snapshot(value).runtimeStatus;
    },
    setFullCdpEnabled: async (value, signal) => {
      calls.push(['full', signal, value]);
      return { config: { browser_bridge: { full_cdp_access_enabled: value } } };
    },
    install: async (signal) => {
      calls.push(['install', signal]);
      return { installed: true };
    },
    uninstall: async (signal) => {
      calls.push(['uninstall', signal]);
      return { removed: true };
    },
  };
}
test('poll waits for snapshot completion and never overlaps pending loads', async () => {
  const h = harness(),
    c = client(),
    gate = deferred();
  let loads = 0;
  c.loadSnapshot = async () => {
    loads++;
    return gate.promise;
  };
  h.render(c);
  await tick();
  assert.equal(loads, 1);
  assert.equal(h.timers.size, 0);
  h.poll();
  assert.equal(loads, 1);
  gate.resolve(snapshot(false));
  await tick();
  assert.equal(h.timers.size, 1);
  h.poll();
  await tick();
  assert.equal(loads, 2);
  h.unmount();
});
test('client generation replacement aborts old signal at layout cleanup and ignores late snapshot', async () => {
  const h = harness(),
    old = client(),
    next = client(),
    gate = deferred();
  let signal;
  old.loadSnapshot = async (s) => {
    signal = s;
    return gate.promise;
  };
  h.render(old);
  await tick();
  h.render(next);
  assert.equal(signal.aborted, true);
  await tick();
  const writes = h.writes.length;
  gate.resolve(snapshot(true));
  await tick();
  assert.equal(h.writes.length, writes);
  assert.equal(h.render(next).enabled, false);
  h.unmount();
});
test('config replacement clears visible old state and aborts pending install without stale refresh', async () => {
  const h = harness(),
    c = client(),
    gate = deferred();
  const first = { projectId: 'first' },
    second = { projectId: 'second' };
  h.render(c, first);
  await tick();
  c.install = async (signal) => {
    c.calls.push(['install', signal]);
    return gate.promise;
  };
  const installing = h.render(c, first).runRegistration('install');
  await tick();
  const signal = c.calls.find((v) => v[0] === 'install')[1];
  assert.equal(h.render(c, second).installResult, null);
  assert.equal(signal.aborted, true);
  await tick();
  const writes = h.writes.length,
    loads = c.calls.filter((v) => v[0] === 'load').length;
  gate.resolve({ installed: true });
  await installing;
  await tick();
  assert.equal(h.writes.length, writes);
  assert.equal(c.calls.filter((v) => v[0] === 'load').length, loads);
  h.unmount();
});
test('queued toggle behind status load cannot execute after unmount', async () => {
  const h = harness(),
    c = client(),
    gate = deferred();
  c.loadSnapshot = () => gate.promise;
  h.render(c);
  await tick();
  const toggle = h.render(c).toggleBridge(true);
  h.unmount();
  gate.resolve(snapshot(false));
  await toggle;
  assert.equal(c.calls.filter((v) => v[0] === 'enabled').length, 0);
});
test('toggle and installation work share a lane with polling and reject duplicate pending mutations', async () => {
  const h = harness(),
    c = client(),
    gate = deferred();
  h.render(c);
  await tick();
  c.setEnabled = async (_, signal) => {
    c.calls.push(['enabled', signal]);
    return gate.promise;
  };
  const action = h.render(c).toggleBridge(true);
  await tick();
  await h.render(c).runRegistration('install');
  h.poll();
  await tick();
  assert.equal(c.calls.filter((v) => v[0] === 'install').length, 0);
  assert.equal(c.calls.filter((v) => v[0] === 'load').length, 1);
  gate.resolve(snapshot(true).runtimeStatus);
  await action;
  assert.equal(h.render(c).toggleBusy, false);
  h.unmount();
});
test('current mutation failures clear optimistic status and expose errors', async () => {
  const h = harness(),
    c = client();
  h.render(c);
  await tick();
  c.setFullCdpEnabled = async () => {
    throw new Error('unavailable');
  };
  await h.render(c).toggleFullCdp(true);
  const state = h.render(c);
  assert.equal(state.fullCdpEnabled, false);
  assert.equal(state.fullCdpToggleBusy, false);
  assert.equal(state.fullCdpToggleError, 'unavailable');
  h.unmount();
});
test('page requires V2 bridge management and has no direct command dispatch', () => {
  const page = readFileSync(
    new URL('../src/features/settings/BrowserIntegrationSettingsPage.tsx', import.meta.url),
    'utf8',
  );
  assert.match(page, /browserBridgeManagementClientV2: DesktopBrowserBridgeManagementClientV2/);
  assert.match(page, /useBrowserBridgeManagementV2\(browserBridgeManagementClientV2, config\)/);
  assert.doesNotMatch(
    page,
    /core\?\.invoke|\binvoke\s*<?|local_runtime_configure|browser_bridge_install|setInterval/,
  );
  assert.match(page, /useBrowserIntegrationManagementV2\(browserIntegrationClientV2, config\)/);
});

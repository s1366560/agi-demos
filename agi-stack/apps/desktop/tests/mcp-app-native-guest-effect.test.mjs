import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
import { pathToFileURL } from 'node:url';
import ts from 'typescript';

const require = createRequire(import.meta.url);
const webRequire = createRequire(new URL('../../../../web/package.json', import.meta.url));
const { Window } = await import(pathToFileURL(webRequire.resolve('happy-dom')).href);
const window = new Window({ url: 'http://localhost/' });
for (const key of [
  'window',
  'document',
  'navigator',
  'HTMLElement',
  'Element',
  'Node',
  'MutationObserver',
]) {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value: key === 'window' ? window : window[key],
  });
}
globalThis.getComputedStyle = window.getComputedStyle.bind(window);
globalThis.innerWidth = 1000;
globalThis.innerHeight = 800;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react');
const { act } = React;
const { createRoot } = require('react-dom/client');
const cache = new Map();
function load(url) {
  if (cache.has(url.href)) return cache.get(url.href);
  const module = { exports: {} };
  cache.set(url.href, module.exports);
  const code = ts.transpileModule(readFileSync(url, 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  new Function('exports', 'module', 'require', code)(module.exports, module, (name) =>
    name.startsWith('.') ? load(new URL(`${name}.ts`, url)) : require(name),
  );
  return module.exports;
}
const { useMcpAppNativeGuest, readMcpAppGuestBounds } = load(
  new URL('../src/features/chat/useMcpAppNativeGuest.ts', import.meta.url),
);
const tabId = 'mcpapp-12345678-1234-1234-1234-123456789012';
const config = {
  toolName: 'test-app',
  html: '<button>Owned</button>',
  sandbox: { url: 'http://localhost/sandbox' },
};
function rect(element, value) {
  element.getBoundingClientRect = () => ({
    ...value,
    left: value.x,
    top: value.y,
    right: value.x + value.width,
    bottom: value.y + value.height,
  });
  element.getClientRects = () => [element.getBoundingClientRect()];
  return element;
}

async function fixture(t, overrides = {}) {
  const calls = [];
  const listeners = new Set();
  const timers = new Map();
  const frames = new Map();
  const mounts = [];
  const errors = [];
  let counter = 0;
  let props = { appKey: 'one', authority: {}, handlers: {}, ...overrides };
  globalThis.requestAnimationFrame = (callback) => {
    frames.set(++counter, callback);
    return counter;
  };
  globalThis.cancelAnimationFrame = (id) => frames.delete(id);
  t.mock.method(window, 'setInterval', (callback) => {
    timers.set(++counter, callback);
    return counter;
  });
  t.mock.method(window, 'clearInterval', (id) => timers.delete(id));
  window.__MEMSTACK_DESKTOP__ = {
    runtime: 'electron',
    events: {
      onMcpAppGuest(listener) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    },
    core: {
      async invoke(command, input) {
        calls.push({ command, input });
        if (command === 'mcp_app_guest_open')
          return {
            guestId: `guest-${input.key}`,
            frameName: input.frameName,
            tabId: input.tabId,
          };
        if (command === 'mcp_app_frame_register') return { pending: false };
        return undefined;
      },
    },
  };
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  function Probe({ appKey, authority, handlers: callbackHandlers }) {
    const container = React.useRef(null);
    const handlers = React.useRef(callbackHandlers);
    handlers.current = callbackHandlers;
    const mount = useMcpAppNativeGuest({
      enabled: true,
      key: appKey,
      tabId,
      keys: appKey ? [appKey] : [],
      config,
      container,
      handlers,
      authority,
      onError: (error) => errors.push(error),
    });
    React.useEffect(() => {
      mounts.push(mount);
    }, [mount]);
    return React.createElement('div', { ref: container });
  }
  const render = async (next) => {
    props = { ...props, ...next };
    await act(async () =>
      root.render(
        props.strict
          ? React.createElement(React.StrictMode, null, React.createElement(Probe, props))
          : React.createElement(Probe, props),
      ),
    );
  };
  let mounted = true;
  const unmount = async () => {
    if (mounted) {
      mounted = false;
      await act(async () => root.unmount());
    }
  };
  t.after(async () => {
    await unmount();
    host.remove();
    delete window.__MEMSTACK_DESKTOP__;
  });
  await render({});
  return {
    calls,
    timers,
    frames,
    mounts,
    errors,
    render,
    unmount,
    identity() {
      return calls.filter((call) => call.command === 'mcp_app_guest_start').at(-1).input;
    },
    emit: (event) =>
      act(async () => {
        for (const listener of listeners) listener(event);
      }),
  };
}

test('native guest effect registers the returned guest owner and keeps the mount stable on ordinary rerenders', async (t) => {
  const f = await fixture(t);
  assert.equal(f.calls.filter((call) => call.command === 'mcp_app_guest_open').length, 1);
  assert.equal(f.mounts.at(-1).mountNonce, f.identity().frameName);
  assert.deepEqual(
    f.calls.find((call) => call.command === 'mcp_app_frame_register').input,
    f.identity(),
  );
  const mount = f.mounts.at(-1);
  await f.render({ unrelated: 1 });
  assert.equal(f.mounts.at(-1), mount);
  assert.equal(f.mounts.length, 2, 'no referential churn in the host request lifetime');
  await f.unmount();
  assert.equal(mount.signal.aborted, true);
  assert.ok(
    f.calls.some(
      (call) =>
        call.command === 'mcp_app_guest_release' && call.input.frameName === mount.mountNonce,
    ),
  );
  assert.equal(f.timers.size, 0);
  assert.equal(f.frames.size, 0);
});

test('StrictMode setup replay retires its first nonce and starts only the live replacement', async (t) => {
  const f = await fixture(t, { strict: true });
  const opens = f.calls.filter((call) => call.command === 'mcp_app_guest_open');
  assert.equal(opens.length, 2);
  assert.notEqual(opens[0].input.frameName, opens[1].input.frameName);
  assert.equal(f.identity().frameName, opens[1].input.frameName);
  assert.ok(
    f.calls.some(
      (call) =>
        call.command === 'mcp_app_guest_release' &&
        call.input.frameName === opens[0].input.frameName,
    ),
  );
  assert.deepEqual(f.errors, []);
});

test('SDK cancellation aborts only the matching callback and drops its late response', async (t) => {
  const pending = new Map();
  const f = await fixture(t, {
    handlers: {
      callTool(params, extra) {
        return new Promise((resolve) =>
          pending.set(params.name, { resolve, signal: extra.signal }),
        );
      },
    },
  });
  const identity = f.identity();
  await f.emit({
    ...identity,
    kind: 'request',
    requestId: 'one',
    method: 'callTool',
    params: { name: 'one' },
  });
  await f.emit({
    ...identity,
    kind: 'request',
    requestId: 'two',
    method: 'callTool',
    params: { name: 'two' },
  });
  await f.emit({ ...identity, kind: 'cancel', requestId: 'one' });
  assert.equal(pending.get('one').signal.aborted, true);
  assert.equal(pending.get('two').signal.aborted, false);
  await act(async () => {
    pending.get('one').resolve('late');
    pending.get('two').resolve('live');
  });
  const responses = f.calls.filter((call) => call.command === 'mcp_app_guest_respond');
  assert.equal(responses.length, 1);
  assert.equal(responses[0].input.requestId, 'two');
  assert.equal(responses[0].input.result, 'live');
});

test('project authority replacement aborts old callbacks and rejects forged or old guest events', async (t) => {
  let calls = 0;
  let finish;
  let signal;
  const f = await fixture(t, {
    handlers: {
      callTool(_params, extra) {
        calls++;
        signal = extra.signal;
        return new Promise((resolve) => {
          finish = resolve;
        });
      },
    },
  });
  const first = f.identity();
  await f.emit({
    ...first,
    guestId: 'forged',
    kind: 'request',
    requestId: 'forged',
    method: 'callTool',
  });
  assert.equal(calls, 0);
  await f.emit({ ...first, kind: 'request', requestId: 'old', method: 'callTool' });
  await f.render({ authority: {} });
  assert.equal(signal.aborted, true);
  assert.notEqual(f.identity().frameName, first.frameName);
  await act(async () => finish('late'));
  await f.emit({ ...first, kind: 'request', requestId: 'old-again', method: 'callTool' });
  assert.equal(calls, 1);
  assert.equal(f.calls.filter((call) => call.command === 'mcp_app_guest_respond').length, 0);
});

test('explicit safety controls and normal dialogs cannot be covered by the native guest', () => {
  for (const element of [document.body, document.documentElement]) {
    element.style.overflowX = 'visible';
    element.style.overflowY = 'visible';
  }
  const slot = rect(document.createElement('article'), { x: 100, y: 100, width: 800, height: 600 });
  slot.style.padding = '0px';
  const safety = rect(document.createElement('aside'), { x: 600, y: 100, width: 300, height: 200 });
  safety.setAttribute('data-native-view-occluder', '');
  document.body.append(slot, safety);
  try {
    assert.deepEqual(readMcpAppGuestBounds(slot), { x: 100, y: 308, width: 800, height: 392 });
    const dialog = rect(document.createElement('div'), { x: 300, y: 250, width: 300, height: 200 });
    dialog.setAttribute('aria-modal', 'true');
    document.body.append(dialog);
    assert.equal(readMcpAppGuestBounds(slot), null);
    dialog.remove();
    slot.setAttribute('inert', '');
    assert.equal(readMcpAppGuestBounds(slot), null);
    slot.removeAttribute('inert');
    safety.setAttribute('role', 'menu');
    safety.removeAttribute('data-native-view-occluder');
    assert.deepEqual(readMcpAppGuestBounds(slot), { x: 100, y: 308, width: 800, height: 392 });
  } finally {
    slot.remove();
    safety.remove();
  }
});

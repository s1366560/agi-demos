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
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node', 'MutationObserver']) {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value: key === 'window' ? window : window[key],
  });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react');
const { act } = React;
const { createRoot } = require('react-dom/client');
const source = readFileSync(new URL('../src/features/chat/mcpAppAutomation.ts', import.meta.url), 'utf8');
const module = { exports: {} };
new Function('exports', 'module', 'require', ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
}).outputText)(module.exports, module, require);
const { invokeMcpApp, useMcpAppAutomation } = module.exports;
const tabId = 'mcpapp-12345678-1234-1234-1234-123456789012';

function Probe({ onMount }) {
  const container = React.useRef(null);
  const mount = useMcpAppAutomation(tabId, container);
  React.useEffect(() => onMount?.(mount), [mount, onMount]);
  return React.createElement('div', { ref: container }, React.createElement('iframe'));
}

async function fixture(t, invoke, strict = false, onMount) {
  const timers = new Map();
  let timerId = 0;
  t.mock.method(window, 'setInterval', (callback) => {
    timers.set(++timerId, callback);
    return timerId;
  });
  t.mock.method(window, 'clearInterval', (id) => timers.delete(id));
  window.__MEMSTACK_DESKTOP__ = { core: { invoke } };
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  let mounted = true;
  const unmount = async () => {
    if (!mounted) return;
    mounted = false;
    await act(async () => root.unmount());
  };
  t.after(async () => {
    await unmount();
    host.remove();
    delete window.__MEMSTACK_DESKTOP__;
  });
  await act(async () => root.render(strict
    ? React.createElement(React.StrictMode, null, React.createElement(Probe, { onMount }))
    : React.createElement(Probe, { onMount })));
  return {
    host, timers, unmount,
    tick: () => act(async () => { for (const timer of [...timers.values()]) timer(); }),
  };
}

test('pending host registration retries until an attached response and cancels its exact mount', async (t) => {
  const calls = [];
  let pending = true;
  const f = await fixture(t, async (command, args) => {
    calls.push({ command, args });
    return { tabId, pending };
  });
  const first = calls[0].args;
  await f.tick();
  assert.equal(calls.filter(call => call.command === 'mcp_app_frame_register').length, 2);
  pending = false;
  await f.tick();
  await f.tick();
  assert.equal(calls.filter(call => call.command === 'mcp_app_frame_register').length, 3);
  assert.ok(calls.every(call => call.args.frameName === first.frameName));
  await f.unmount();
  assert.deepEqual(calls.at(-1), { command: 'mcp_app_frame_unregister', args: first });
  assert.equal(f.timers.size, 0);
});

test('unmount before registration completes sends cancellation immediately and after late completion', async (t) => {
  const calls = [];
  let complete;
  const f = await fixture(t, (command, args) => {
    calls.push({ command, args });
    return command === 'mcp_app_frame_register'
      ? new Promise(resolve => { complete = resolve; })
      : Promise.resolve({ tabId });
  });
  const first = calls[0].args;
  await f.unmount();
  assert.deepEqual(calls.at(-1), { command: 'mcp_app_frame_unregister', args: first });
  await act(async () => complete({ tabId, pending: false }));
  assert.equal(calls.filter(call => call.command === 'mcp_app_frame_unregister').length, 2);
  assert.ok(calls.every(call => call.args.frameName === first.frameName));
  assert.equal(f.timers.size, 0);
});

test('real StrictMode setup replay keeps the new mount when the old registration completes late', async (t) => {
  const calls = [];
  const cancelled = new Set();
  const completions = new Map();
  let active;
  const f = await fixture(t, (command, args) => {
    calls.push({ command, args });
    if (command === 'mcp_app_frame_unregister') {
      cancelled.add(args.frameName);
      if (active === args.frameName) active = undefined;
      return Promise.resolve({ tabId });
    }
    return new Promise(resolve => completions.set(args.frameName, (pending = false) => {
      if (!cancelled.has(args.frameName) && !pending) active = args.frameName;
      resolve({ tabId, pending });
    }));
  }, true);
  const registrations = calls.filter(call => call.command === 'mcp_app_frame_register');
  assert.equal(registrations.length, 2, 'React StrictMode must execute two actual effect setups');
  const [oldMount, newMount] = registrations.map(call => call.args.frameName);
  assert.notEqual(oldMount, newMount);
  assert.equal(f.host.querySelector('iframe').name, newMount);
  assert.ok(cancelled.has(oldMount), 'the first setup must cancel before its register resolves');
  await act(async () => completions.get(newMount)());
  assert.equal(active, newMount);
  await act(async () => completions.get(oldMount)());
  assert.equal(active, newMount);
  assert.deepEqual(calls.at(-1), {
    command: 'mcp_app_frame_unregister', args: { tabId, frameName: oldMount },
  });
  await f.tick();
  assert.equal(calls.filter(call => call.command === 'mcp_app_frame_register').length, 2);
  await f.unmount();
  assert.equal(active, undefined);
  assert.equal(f.timers.size, 0);
});

test('callbacks capture the actual effect nonce and cannot substitute a replacement mount', async (t) => {
  const calls = [];
  let oldMount;
  let newMount;
  let complete;
  let entered;
  const started = new Promise(resolve => { entered = resolve; });
  const invoke = async (command, args) => {
    calls.push({ command, args });
    if (command === 'mcp_app_operation_prepare') return { operationId: 'host-operation' };
    if (command === 'mcp_app_operation' && args.operation === 'tools/call') {
      return new Promise(resolve => { complete = resolve; entered(); });
    }
    return { tabId, pending: false };
  };
  const first = await fixture(t, invoke, false, mount => { oldMount = mount; });
  assert.equal(typeof oldMount?.mountNonce, 'string');
  assert.equal(oldMount.mountNonce, first.host.querySelector('iframe').name);
  assert.equal(Object.isFrozen(oldMount), true);
  const pending = invokeMcpApp(oldMount, 'tools/call', { name: 'original' });
  const rejected = assert.rejects(pending, { name: 'AbortError' });
  await started;
  const captured = calls.at(-1).args;
  await first.unmount();
  assert.equal(oldMount.signal.aborted, true);
  const second = await fixture(t, invoke, true, mount => { newMount = mount; });
  assert.notEqual(newMount.mountNonce, oldMount.mountNonce);
  assert.equal(newMount.mountNonce, second.host.querySelector('iframe').name);
  complete({ content: [] });
  await rejected;
  assert.equal(captured.mountNonce, oldMount.mountNonce);
  const before = calls.length;
  await assert.rejects(invokeMcpApp(oldMount, 'prompts/list'), { name: 'AbortError' });
  assert.equal(calls.length, before, 'retired callbacks must fail before IPC');
  await invokeMcpApp(newMount, 'prompts/get', { name: 'owned', mountNonce: oldMount.mountNonce });
  assert.equal(calls.at(-1).args.mountNonce, newMount.mountNonce);
  assert.equal(calls.at(-1).args.arguments.mountNonce, oldMount.mountNonce);
});

test('SDK signal aborted before preparation produces no IPC', async t => {
  const calls = [];
  window.__MEMSTACK_DESKTOP__ = { core: { invoke: async (...args) => { calls.push(args); } } };
  t.after(() => delete window.__MEMSTACK_DESKTOP__);
  const sdk = new AbortController(); sdk.abort();
  const mount = { tabId, mountNonce: 'owned', signal: new AbortController().signal };
  await assert.rejects(invokeMcpApp(mount, 'tools/call', { name: 'owned' }, sdk.signal), { name: 'AbortError' });
  assert.deepEqual(calls, []);
});

test('SDK cancellation while host prepares cancels its returned ID without dispatching', async t => {
  const calls = []; let release;
  window.__MEMSTACK_DESKTOP__ = { core: { invoke: async (command, args) => {
    calls.push({ command, args });
    if (command === 'mcp_app_operation_prepare') return new Promise(resolve => { release = resolve; });
    return { cancelled: true };
  } } };
  t.after(() => delete window.__MEMSTACK_DESKTOP__);
  const sdk = new AbortController();
  const mount = { tabId, mountNonce: 'owned', signal: new AbortController().signal };
  const callback = invokeMcpApp(mount, 'tools/call', { name: 'owned' }, sdk.signal);
  const rejected = assert.rejects(callback, { name: 'AbortError' });
  sdk.abort(); release({ operationId: 'host-only-operation' }); await rejected;
  assert.deepEqual(calls.map(call => call.command), ['mcp_app_operation_prepare', 'mcp_app_operation_cancel']);
  assert.deepEqual(calls[1].args, { tabId, mountNonce: 'owned', operationId: 'host-only-operation' });
});

test('SDK signal cancels only its active operation and removes listeners on completion', async t => {
  const calls = []; let finish;
  window.__MEMSTACK_DESKTOP__ = { core: { invoke: async (command, args) => {
    calls.push({ command, args });
    if (command === 'mcp_app_operation_prepare') return { operationId: 'host-only-operation' };
    if (command === 'mcp_app_operation') return new Promise(resolve => { finish = resolve; });
    finish({ content: [] }); return { cancelled: true };
  } } };
  t.after(() => delete window.__MEMSTACK_DESKTOP__);
  const sdk = new AbortController(), owner = new AbortController();
  const mount = { tabId, mountNonce: 'owned', signal: owner.signal };
  const callback = invokeMcpApp(mount, 'tools/call', { name: 'owned' }, sdk.signal);
  const rejected = assert.rejects(callback, { name: 'AbortError' });
  await Promise.resolve(); sdk.abort(); await rejected;
  assert.deepEqual(calls.at(-1), { command: 'mcp_app_operation_cancel', args: { tabId, mountNonce: 'owned', operationId: 'host-only-operation' } });
  const before = calls.length; owner.abort(); assert.equal(calls.length, before);
});

test('execute IPC failure clears the exact prepared operation without dispatch', async t => {
  const calls = []; let prepared = false;
  window.__MEMSTACK_DESKTOP__ = { core: { invoke: async (command, args) => {
    calls.push({ command, args });
    if (command === 'mcp_app_operation_prepare') { prepared = true; return { operationId: 'host-only-operation' }; }
    if (command === 'mcp_app_operation') throw Error('fixture IPC transport failed before delivery');
    assert.equal(args.operationId, 'host-only-operation'); prepared = false; return { cancelled: true };
  } } };
  t.after(() => delete window.__MEMSTACK_DESKTOP__);
  const mount = { tabId, mountNonce: 'owned', signal: new AbortController().signal };
  await assert.rejects(invokeMcpApp(mount, 'tools/call', { name: 'owned' }), /transport failed/);
  assert.equal(prepared, false);
  assert.deepEqual(calls.map(call => call.command), ['mcp_app_operation_prepare', 'mcp_app_operation', 'mcp_app_operation_cancel']);
  assert.deepEqual(calls.at(-1).args, { tabId, mountNonce: 'owned', operationId: 'host-only-operation' });
});

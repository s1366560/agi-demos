import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import test from 'node:test';
const require = createRequire(import.meta.url);
const webRequire = createRequire(new URL('../../../../web/package.json', import.meta.url));
const { Window } = await import(pathToFileURL(webRequire.resolve('happy-dom')).href);
const window = new Window({ url: 'http://localhost/' });
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'HTMLInputElement', 'Element', 'Node', 'DOMParser', 'MutationObserver', 'ResizeObserver', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame']) {
  const value = key === 'window' ? window : window[key];
  Object.defineProperty(globalThis, key, { configurable: true, value: ['getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame'].includes(key) ? value.bind(window) : value });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react'), { act } = React, { createRoot } = require('react-dom/client');
const esbuild = createRequire(require.resolve('vite'))('esbuild');
const compiled = await esbuild.build({
  stdin: { contents: "export {BrowserPanel} from './src/features/browser/BrowserPanel'; export {BrowserAuthRequests} from './src/features/chat/BrowserAuthRequests';", resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts' },
  write: false, bundle: true, platform: 'node', format: 'cjs', packages: 'external', loader: { '.css': 'empty' },
  plugins: [{ name: 'i18n-test', setup(build) {
    build.onResolve({ filter: /i18n$/ }, () => ({ path: 'i18n', namespace: 'mock' }));
    build.onLoad({ filter: /.*/, namespace: 'mock' }, () => ({ contents: 'exports.useI18n = () => ({ t: (key, fields) => fields ? key + JSON.stringify(fields) : key });' }));
  } }],
});
let timerId = 0;
const timers = new Map(), intervals = new Map();
window.setInterval = (callback, delay) => { const id = ++timerId; intervals.set(id, { callback, delay }); return id; };
window.clearInterval = id => intervals.delete(id);
const module = { exports: {} };
new Function('require', 'module', 'exports', 'setTimeout', 'clearTimeout', compiled.outputFiles[0].text)(require, module, module.exports,
  (callback, delay) => { const id = ++timerId; timers.set(id, { callback, delay }); return id; }, id => timers.delete(id));
const { BrowserPanel, BrowserAuthRequests } = module.exports;
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const tickTimer = async (map, delay, remove = false) => {
  const entry = [...map].find(([, value]) => value.delay === delay);
  assert.ok(entry, `a ${delay}ms timer is pending`);
  if (remove) map.delete(entry[0]);
  await act(async () => { entry[1].callback(); });
};
async function render(Component, props) {
  const container = document.createElement('div'); document.body.append(container);
  const root = createRoot(container);
  await act(async () => root.render(React.createElement(Component, props)));
  return { container, update: next => act(async () => root.render(React.createElement(Component, next))),
    close: async () => { await act(async () => root.unmount()); container.remove(); timers.clear(); intervals.clear(); } };
}
const click = element => act(async () => { assert.ok(element); element.click(); });
const input = (element, value) => act(async () => {
  Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(element, value);
  element.dispatchEvent(new window.Event('input', { bubbles: true }));
});
function browserFixture() {
  let listener, status = { status: 'connected', contextReady: true };
  let tabs = [
    { tabId: 1, windowId: 1, title: 'Current page', url: 'https://one.example/', active: true, canGoBack: true, canGoForward: true,
      ownership: { sessionId: 'current', origin: 'agent', controller: 'agent', callerId: 'agent1', mark: 'deliverable' } },
    { tabId: 2, windowId: 1, title: 'Other page', url: 'https://two.example/', active: false, canGoBack: false, canGoForward: false,
      ownership: { sessionId: 'other', origin: 'user', controller: 'user', callerId: null, mark: null } },
  ];
  const calls = [];
  const bridge = {
    listTabs: async () => ({ tabs }), status: async () => status,
    onTabsChanged: callback => { listener = callback; return () => { listener = undefined; }; },
    showPane: async () => {}, setBounds: async () => {}, hidePane: async () => {},
    createTab: async () => { calls.push(['create']); }, closeTab: async id => calls.push(['close', id]),
    navigateTab: async (id, url) => calls.push(['navigate', id, url]),
    navigateHistory: async (id, direction) => calls.push(['history', id, direction]),
    focusTab: async id => { calls.push(['focus', id]); tabs = tabs.map(tab => ({ ...tab, active: tab.tabId === id })); listener?.({ tabs }); },
    takeOver: async id => { calls.push(['takeOver', id]); tabs = tabs.map(tab => tab.tabId === id ? { ...tab, ownership: { ...tab.ownership, controller: 'user', mark: null } } : tab); listener?.({ tabs }); },
  };
  window.__MEMSTACK_DESKTOP__ = { iab: bridge };
  return { bridge, calls, setStatus: value => { status = value; } };
}

test('rendered browser navigation and takeover dispatch the active tab and reflect ownership', async () => {
  const f = browserFixture(); const view = await render(BrowserPanel, { conversationId: 'current' }); const c = view.container;
  try {
    assert.ok(c.textContent.includes('browserPanel.agentControl')); assert.ok(c.textContent.includes('browserPanel.deliverable'));
    for (const direction of ['back', 'forward', 'reload']) await click(c.querySelector(`[aria-label="browserPanel.${direction}"]`));
    await input(c.querySelector('[aria-label="browserPanel.address"]'), 'new.example/path');
    await act(async () => c.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })));
    await click([...c.querySelectorAll('button')].find(button => button.textContent === 'browserPanel.takeOver'));
    assert.deepEqual(f.calls, [['history', 1, 'back'], ['history', 1, 'forward'], ['history', 1, 'reload'], ['navigate', 1, 'https://new.example/path'], ['takeOver', 1]]);
    assert.ok(c.textContent.includes('browserPanel.userControl')); assert.equal(c.textContent.includes('browserPanel.takeOver'), false);
  } finally { await view.close(); }
});

test('rendered session selector filters tabs, focuses the chosen session, and disables unavailable history', async () => {
  const f = browserFixture(); const view = await render(BrowserPanel, { conversationId: 'current' }); const c = view.container;
  try {
    const select = c.querySelector('select');
    assert.equal(select.querySelector('[value="current"]').textContent, 'browserPanel.currentSession');
    await act(async () => { select.value = 'other'; select.dispatchEvent(new window.Event('change', { bubbles: true })); });
    assert.deepEqual([...c.querySelectorAll('[role="tab"]')].map(tab => tab.textContent), ['Other page']);
    assert.equal(c.querySelector('[aria-label="browserPanel.address"]').value, 'https://two.example/');
    for (const direction of ['back', 'forward']) { const button = c.querySelector(`[aria-label="browserPanel.${direction}"]`); assert.equal(button.disabled, true); await click(button); }
    assert.deepEqual(f.calls, [['focus', 2]]);
    await act(async () => { select.value = 'all'; select.dispatchEvent(new window.Event('change', { bubbles: true })); });
    assert.equal(c.querySelectorAll('[role="tab"]').length, 2); assert.deepEqual(f.calls.at(-1), ['focus', 1]);
  } finally { await view.close(); }
});

test('new tabs wait for authenticated context, then reconnect polling restores controls and clears only load failures', async () => {
  const f = browserFixture(); const first = deferred(); f.bridge.status = () => first.promise;
  const view = await render(BrowserPanel, { conversationId: 'current' }); const c = view.container;
  try {
    const add = c.querySelector('.browser-panel-new-tab'); assert.equal(add.disabled, true);
    await click(add); assert.equal(f.calls.length, 0);
    await act(async () => first.resolve({ status: 'connected', contextReady: false }));
    assert.ok(c.textContent.includes('browserPanel.contextPending'));
    f.bridge.status = async () => { throw new Error('private connection error'); };
    await tickTimer(intervals, 3000); assert.ok(c.querySelector('[role="alert"]')); assert.equal(c.textContent.includes('private connection error'), false);
    f.bridge.status = async () => ({ status: 'connected', contextReady: true });
    await tickTimer(intervals, 3000); assert.equal(c.querySelector('[role="alert"]'), null); assert.equal(add.disabled, false);
    await click(add); assert.deepEqual(f.calls, [['create']]);
    f.bridge.navigateHistory = async () => { throw new Error('action failed'); };
    await click(c.querySelector('[aria-label="browserPanel.reload"]'));
    await tickTimer(intervals, 3000); assert.ok(c.querySelector('[role="alert"]')?.textContent.includes('browserPanel.actionFailed'));
  } finally { await view.close(); }
});

const config = { mode: 'local', apiBaseUrl: 'http://localhost/', apiKey: 'session-fixture', localApiToken: 'launch-fixture' };
const prompt = id => ({ request_id: id, origin: 'login.example', expires_at: new Date(Date.now() + 60000).toISOString(), account_identifier: 'Fixture account', fields: [{ id: 'code', label: 'Verification code', type: 'password', required: true }], options: [] });

test('rendered authentication prompt and entered values survive polling failure; retry reconnects without resubmitting', async () => {
  let response = { requests: [prompt('request')] }, failing = false; const calls = [];
  window.__MEMSTACK_DESKTOP__ = { core: { invoke: async (command, args) => { calls.push({ command, args }); if (failing) throw new Error('private transport details'); return response; } } };
  const view = await render(BrowserAuthRequests, { config, conversationId: 'chat' }); const c = view.container;
  try {
    const field = c.querySelector('input[name="code"]'); assert.ok(field);
    await input(field, 'fixture-code'); failing = true;
    await tickTimer(timers, 1000, true);
    assert.equal(c.querySelector('input[name="code"]'), field); assert.equal(field.value, 'fixture-code');
    assert.ok(c.querySelector('[role="alert"]')?.textContent.includes('chat.browserAuth.pollFailed')); assert.equal(c.textContent.includes('private transport details'), false);
    failing = false; await click(c.querySelector('[role="alert"] button'));
    assert.equal(c.querySelector('[role="alert"]'), null); assert.equal(c.querySelector('input').value, 'fixture-code');
    assert.equal(calls.length, 3); assert.ok(calls.every(call => call.command === 'browser_auth_pending' && call.args.conversation_id === 'chat'));
    response = { requests: [] }; await tickTimer(timers, 1000, true); assert.equal(c.querySelector('form'), null);
  } finally { await view.close(); }
});

test('late authentication response cannot replace the prompt for a newly selected conversation', async () => {
  const old = deferred();
  window.__MEMSTACK_DESKTOP__ = { core: { invoke: async (_command, args) => args.conversation_id === 'old' ? old.promise : { requests: [prompt('new-request')] } } };
  const view = await render(BrowserAuthRequests, { config, conversationId: 'old' });
  try {
    await view.update({ config, conversationId: 'new' });
    const field = view.container.querySelector('input'); await input(field, 'new-code');
    await act(async () => old.resolve({ requests: [prompt('old-request')] }));
    assert.equal(view.container.querySelector('input'), field); assert.equal(field.value, 'new-code'); assert.equal(view.container.querySelectorAll('form').length, 1);
  } finally { await view.close(); }
});

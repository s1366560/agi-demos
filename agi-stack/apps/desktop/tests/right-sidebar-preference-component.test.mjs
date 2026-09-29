import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const webRequire = createRequire(new URL('../../../../web/package.json', import.meta.url));
const { Window } = await import(pathToFileURL(webRequire.resolve('happy-dom')).href);
const window = new Window({ url: 'http://localhost/' });
for (const key of [
  'window',
  'document',
  'navigator',
  'HTMLElement',
  'HTMLInputElement',
  'HTMLTextAreaElement',
  'CustomEvent',
  'Event',
  'NodeFilter',
  'Element',
  'Node',
  'DOMParser',
  'MutationObserver',
  'ResizeObserver',
  'getComputedStyle',
  'requestAnimationFrame',
  'cancelAnimationFrame',
]) {
  const value = key === 'window' ? window : window[key];
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value:
      typeof value === 'function' &&
      ['getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame'].includes(key)
        ? value.bind(window)
        : value,
  });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react'),
  { act } = React,
  { createRoot } = require('react-dom/client');

const ts = require('typescript');
const modules = new Map();
function load(name) {
  if (modules.has(name)) return modules.get(name);
  const source = readFileSync(new URL(`../src/features/chrome/${name}.ts`, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS },
  }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', code)(
    (id) => id.startsWith('./') ? load(id.slice(2)) : require(id), module, module.exports,
  );
  modules.set(name, module.exports);
  return module.exports;
}
const { useWorkPanels } = load('useWorkPanels');
const { EMPTY_WORK_PANEL, workPanelGeometry } = load('workPanelState');

async function mount(initialScope = 'session-a') {
  let current;
  function Harness({ scope }) {
    current = useWorkPanels();
    current.scopeRef.current = scope;
    return null;
  }
  const element = document.createElement('div');
  document.body.append(element);
  const root = createRoot(element);
  await act(async () => root.render(React.createElement(Harness, { scope: initialScope })));
  return {
    get state() { return current.sessions[current.scopeRef.current] ?? EMPTY_WORK_PANEL; },
    get open() { return current.open; },
    async scope(scope) {
      await act(async () => root.render(React.createElement(Harness, { scope })));
    },
    async invoke(name, ...args) { await act(async () => current[name](...args)); },
    async close() {
      await act(async () => root.unmount());
      element.remove();
    },
  };
}

test('work panels keep ordered deduplicated tabs separately for each session', async () => {
  const view = await mount();
  try {
    assert.deepEqual(view.state, EMPTY_WORK_PANEL);
    await view.invoke('open', 'plan');
    await view.invoke('open', 'changes');
    await view.invoke('open', 'plan');
    assert.deepEqual(view.state, { tabs: ['plan', 'changes'], active: 'plan', open: true });
    await view.scope('session-b');
    assert.deepEqual(view.state, EMPTY_WORK_PANEL);
    await view.invoke('open', 'browser');
    await view.scope('session-a');
    assert.deepEqual(view.state, { tabs: ['plan', 'changes'], active: 'plan', open: true });
    await view.scope('session-b');
    assert.deepEqual(view.state.tabs, ['browser']);
  } finally { await view.close(); }
});

test('stable open callbacks dispatch into the latest session scope without cross-session leakage', async () => {
  const view = await mount('tenant-a/session-1');
  try {
    const open = view.open;
    await act(async () => { open('plan'); open('checks'); });
    await view.scope('tenant-b/session-1');
    await act(async () => open('artifacts'));
    assert.deepEqual(view.state, { tabs: ['artifacts'], active: 'artifacts', open: true });
    await view.scope('tenant-a/session-1');
    assert.deepEqual(view.state, { tabs: ['plan', 'checks'], active: 'checks', open: true });
    await view.scope('tenant-b/session-1');
    assert.deepEqual(view.state.tabs, ['artifacts']);
  } finally { await view.close(); }
});

test('closing tabs selects the adjacent tab and closing the last hides the panel', async () => {
  const view = await mount();
  try {
    for (const tab of ['plan', 'changes', 'checks']) await view.invoke('open', tab);
    await view.invoke('dispatch', { type: 'select', tab: 'changes' });
    await view.invoke('dispatch', { type: 'close', tab: 'changes' });
    assert.deepEqual(view.state, { tabs: ['plan', 'checks'], active: 'checks', open: true });
    await view.invoke('dispatch', { type: 'close', tab: 'checks' });
    assert.equal(view.state.active, 'plan');
    await view.invoke('dispatch', { type: 'close', tab: 'plan' });
    assert.deepEqual(view.state, EMPTY_WORK_PANEL);
  } finally { await view.close(); }
});

test('hide/show restores tabs and focus returns to the opening control', async () => {
  const trigger = document.createElement('button');
  document.body.append(trigger);
  const frame = window.requestAnimationFrame;
  window.requestAnimationFrame = (callback) => { callback(0); return 0; };
  const view = await mount();
  try {
    trigger.focus();
    await view.invoke('open', 'plan');
    await view.invoke('open', 'checks');
    trigger.blur();
    await view.invoke('hide');
    assert.deepEqual(view.state, { tabs: ['plan', 'checks'], active: 'checks', open: false });
    assert.ok(document.activeElement === trigger, 'focus returns to the opening control');
    await view.invoke('dispatch', { type: 'show', fallback: 'run-details' });
    assert.deepEqual(view.state, { tabs: ['plan', 'checks'], active: 'checks', open: true });
  } finally {
    await view.close();
    window.requestAnimationFrame = frame;
    trigger.remove();
  }
});

test('restoring focus uses the opening control belonging to the current session', async () => {
  const triggers = [document.createElement('button'), document.createElement('button')];
  for (const trigger of triggers) document.body.append(trigger);
  const frame = window.requestAnimationFrame;
  window.requestAnimationFrame = (callback) => { callback(0); return 0; };
  const view = await mount('session-a');
  try {
    triggers[0].focus();
    await view.invoke('open', 'plan');
    await view.scope('session-b');
    triggers[1].focus();
    await view.invoke('open', 'checks');
    await view.scope('session-a');
    await view.invoke('hide');
    assert.ok(document.activeElement === triggers[0], 'session A restores its own trigger');
  } finally {
    await view.close();
    window.requestAnimationFrame = frame;
    for (const trigger of triggers) trigger.remove();
  }
});

test('legacy persisted visibility is ignored and tabs reset on application remount', async () => {
  window.localStorage.setItem('agistack.desktop.rightSidebarOpen', 'true');
  let view = await mount();
  try {
    assert.deepEqual(view.state, EMPTY_WORK_PANEL);
    await view.invoke('open', 'plan');
    await view.close();
    view = await mount();
    assert.deepEqual(view.state, EMPTY_WORK_PANEL);
  } finally {
    await view.close();
    window.localStorage.clear();
  }
});

test('unavailable storage does not affect in-memory panel state', async () => {
  const descriptor = Object.getOwnPropertyDescriptor(window, 'localStorage');
  Object.defineProperty(window, 'localStorage', {
    configurable: true, get() { throw new Error('Storage unavailable'); },
  });
  const view = await mount();
  try {
    await view.invoke('dispatch', { type: 'show', fallback: 'run-details' });
    assert.equal(view.state.active, 'run-details');
    await view.invoke('hide');
    assert.equal(view.state.open, false);
  } finally {
    await view.close();
    if (descriptor) Object.defineProperty(window, 'localStorage', descriptor);
    else delete window.localStorage;
  }
});

test('geometry preserves readable conversation and panel widths at target desktop sizes', () => {
  for (const available of [1024, 1280, 1440, 1920]) {
    const geometry = workPanelGeometry(available, null, false);
    assert.equal(geometry.fullWidth, false);
    assert.equal(geometry.width, available * 0.4);
    assert.ok(geometry.width >= 360);
    const maximum = workPanelGeometry(available, 9999, false).width;
    assert.ok(maximum <= available * 0.6);
    assert.ok(available - maximum >= 480);
    assert.equal(workPanelGeometry(available, 1, false).width, 360);
  }
});

test('geometry uses full width below the split minimum and restores preferred width after expansion', () => {
  for (const available of [0, 500, 804, 839]) {
    assert.equal(workPanelGeometry(available, 400, false).fullWidth, true);
    assert.equal(workPanelGeometry(available, 400, false).width, available);
  }
  assert.equal(workPanelGeometry(840, null, false).width, 360);
  assert.equal(workPanelGeometry(1440, 520, true).width, 1440);
  assert.equal(workPanelGeometry(1440, 520, false).width, 520);
  assert.equal(workPanelGeometry(-10, null, false).width, 0);
});

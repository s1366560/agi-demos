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
const menuContext = React.createContext(null);
const DropdownMenu = {
  Root({ children }) {
    const [open, setOpen] = React.useState(false);
    return React.createElement(menuContext.Provider, { value: { open, setOpen } }, children);
  },
  Trigger({ children }) {
    const { setOpen } = React.useContext(menuContext);
    return React.cloneElement(children, { onClick: () => setOpen((value) => !value) });
  },
  Content({ children }) {
    return React.useContext(menuContext).open ? React.createElement('div', { role: 'menu' }, children) : null;
  },
  Group: ({ children }) => React.createElement('div', null, children),
  Label: ({ children }) => React.createElement('span', null, children),
  Item({ children, disabled, onSelect }) {
    const { setOpen } = React.useContext(menuContext);
    return React.createElement('button', { role: 'menuitem', disabled, onClick: () => {
      onSelect(); setOpen(false);
    } }, children);
  },
};
const loaded = new Map();
function load(name) {
  if (loaded.has(name)) return loaded.get(name);
  const suffix = name === 'DesktopRightSidebar' ? 'tsx' : 'ts';
  const source = readFileSync(new URL(`../src/features/chrome/${name}.${suffix}`, import.meta.url), 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX,
  } }).outputText;
  const module = { exports: {} };
  new Function('require', 'module', 'exports', code)((id) => {
    if (id === '@radix-ui/themes') return { DropdownMenu };
    if (id.endsWith('.css')) return {};
    if (id === './workPanelState') return load('workPanelState');
    if (id === '../../i18n') return { useI18n: () => ({ t: (key) => key }) };
    if (id.endsWith('/ResizeHandle')) return { ResizeHandle: () => React.createElement('div', { role: 'separator' }) };
    if (id.endsWith('/TimelineInspectionContext')) return { useTimelineInspection: () => ({ dismiss() {} }) };
    if (id.endsWith('/sessionWorkPanelOptions')) return { getSessionWorkPanelOptions: (state) => state.options };
    if (id.endsWith('/BrowserPanel')) return { BrowserPanel: () => React.createElement('div', null, 'browser content') };
    if (id.endsWith('/SessionContextRail')) return { SessionContextRail: () => React.createElement('div', null, 'run details') };
    if (id.endsWith('/DesktopRendererSessionCanvasV2')) return {
      DesktopRendererSessionCanvasV2: ({ controls }) => React.createElement('div', {
        'data-embedded': String(controls.embedded),
      }, 'canvas content'),
    };
    return require(id);
  }, module, module.exports);
  loaded.set(name, module.exports);
  return module.exports;
}
const { DesktopRightSidebar } = load('DesktopRightSidebar');
const { useWorkPanels } = load('useWorkPanels');
const { EMPTY_WORK_PANEL } = load('workPanelState');
const baseOptions = ['plan', 'checks', 'changes'].map((id) => ({
  id, labelKey: id, available: true, group: 'work',
}));

async function mount(width = 1440) {
  let current;
  let options = baseOptions;
  const shell = document.createElement('div');
  shell.className = 'app-shell';
  shell.style.gridTemplateColumns = '220px 1fr auto';
  Object.defineProperty(shell, 'clientWidth', { value: width });
  document.body.append(shell);
  const main = document.createElement('main');
  main.className = 'workbench';
  main.inert = false;
  shell.append(main);
  const trigger = document.createElement('button');
  trigger.dataset.workPanelToggle = '';
  main.append(trigger);
  trigger.focus();
  const host = document.createElement('div');
  shell.append(host);
  const root = createRoot(host);
  function Harness() {
    current = useWorkPanels();
    current.scopeRef.current = 'session';
    const state = current.sessions.session ?? EMPTY_WORK_PANEL;
    return state.open ? React.createElement(DesktopRightSidebar, {
      state, canvas: { kind: 'available', input: { state: { options } } },
      viewModel: {}, runActionPending: null, onRunAction() {},
      onOpenCanvas: current.open, onSelectPanel: current.open,
      onCloseTab: (tab) => {
        current.dispatch({ type: 'close', tab });
        if (state.tabs.length === 1) current.restoreFocus();
      },
      onClose: current.hide, onCloseCanvas: current.hide,
    }) : null;
  }
  await act(async () => root.render(React.createElement(Harness)));
  await act(async () => current.open('plan'));
  const flushFrames = () => new Promise((resolve) => window.requestAnimationFrame(resolve));
  return {
    shell, main, trigger,
    query: (selector) => shell.querySelector(selector),
    async click(selector) {
      const target = shell.querySelector(selector);
      assert.ok(target, selector);
      await act(async () => { target.click(); await flushFrames(); });
    },
    async key(selector, key) {
      const target = shell.querySelector(selector);
      target.focus();
      await act(async () => {
        target.dispatchEvent(new window.KeyboardEvent('keydown', { key, bubbles: true }));
      });
      await act(flushFrames);
    },
    async options(value) {
      options = value;
      await act(async () => root.render(React.createElement(Harness)));
    },
    async close() { await act(async () => root.unmount()); shell.remove(); },
  };
}

test('work panel menu opens actual content in one tab header and keyboard closing restores focus', async () => {
  const view = await mount();
  try {
    assert.equal(view.shell.querySelectorAll('header').length, 1);
    assert.equal(view.query('[data-embedded]').dataset.embedded, 'true');
    await view.click('[aria-label="rightbar.addView"]');
    const menuItem = [...view.shell.querySelectorAll('[role="menuitem"]')].find((item) => item.textContent === 'checks');
    await act(async () => menuItem.click());
    assert.equal(view.shell.querySelectorAll('[role="tab"]').length, 2);
    assert.equal(view.query('[aria-selected="true"]').textContent, 'checks');
    await view.key('#work-panel-tab-checks', 'ArrowLeft');
    assert.equal(document.activeElement.id, 'work-panel-tab-plan');
    await view.key('#work-panel-tab-plan', 'Delete');
    assert.equal(document.activeElement.id, 'work-panel-tab-checks');
    await view.key('#work-panel-tab-checks', 'Delete');
    assert.equal(view.query('aside'), null);
    assert.ok(document.activeElement === view.trigger, 'focus returns after the last tab closes');
  } finally { await view.close(); }
});

test('capability loss keeps the active tab and explains its unavailable state', async () => {
  const view = await mount();
  try {
    await view.options(baseOptions.map((option) => option.id === 'plan'
      ? { ...option, available: false, reasonKey: 'plan-authority-unavailable' } : option));
    assert.equal(view.query('[aria-selected="true"]').textContent, 'plan');
    assert.equal(view.query('[role="status"]').textContent, 'plan-authority-unavailable');
    await view.click('[aria-label="rightbar.addView"]');
    const unavailable = [...view.shell.querySelectorAll('[role="menuitem"]')].find((item) => item.textContent.startsWith('plan'));
    assert.equal(unavailable.disabled, true);
    assert.match(unavailable.textContent, /plan-authority-unavailable/);
  } finally { await view.close(); }
});

test('expanded and narrow work panels make the covered conversation inert and restore it on close', async () => {
  const view = await mount();
  try {
    assert.equal(view.main.inert, false);
    await view.click('[aria-label="session.focusCanvas"]');
    assert.equal(view.main.inert, true);
    assert.ok(view.query('.desktop-right-sidebar-full'));
    await view.click('[aria-label="session.splitView"]');
    assert.equal(view.main.inert, false);
    await view.click('[aria-label="rightbar.hide"]');
    assert.equal(view.main.inert, false);
  } finally { await view.close(); }
  const narrow = await mount(1024);
  try {
    assert.equal(narrow.main.inert, true);
    assert.ok(narrow.query('.desktop-right-sidebar-full'));
    assert.equal(narrow.query('[aria-label="session.focusCanvas"]'), null);
    assert.equal(narrow.query('[aria-label="session.splitView"]'), null);
    await narrow.click('[aria-label="rightbar.hide"]');
    assert.equal(narrow.main.inert, false);
  } finally { await narrow.close(); }
});

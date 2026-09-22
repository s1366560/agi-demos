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
const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const ast = ts.createSourceFile('App.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const app = ast.statements.find(
  (node) => ts.isFunctionDeclaration(node) && node.name?.text === 'App',
);
assert.ok(app?.body, 'App component is available');

// Execute the production hook/callback declarations, rather than reproducing their logic.
// This isolates the layout preference state from App's unrelated network/plugin initialization.
const names = new Set([
  'rightSidebarOpen',
  'rightSidebarPreferenceRef',
  'rememberRightSidebar',
  'activeRightPanel',
  'rightSidebarOpenedForCanvas',
  'openRightCanvasPanel',
  'closeRightCanvasPanel',
  'handleCloseCanvas',
  'handleSelectRightPanel',
]);
const found = new Set();
const statements = app.body.statements.filter((statement) => {
  if (!ts.isVariableStatement(statement)) return false;
  return statement.declarationList.declarations.some((declaration) => {
    const name = ts.isArrayBindingPattern(declaration.name)
      ? declaration.name.elements[0].name?.getText(ast)
      : declaration.name.getText(ast);
    if (!names.has(name)) return false;
    found.add(name);
    return true;
  });
});
assert.deepEqual(
  [...found].sort(),
  [...names].sort(),
  'all production preference declarations are covered',
);
const compiled = ts.transpileModule(
  `
  const { useState, useRef, useCallback } = React;
  function PreferenceHarness() {
    ${statements.map((statement) => statement.getText(ast)).join('\n')}
    expose({ rightSidebarOpen, activeRightPanel, rightSidebarOpenedForCanvas,
      rememberRightSidebar, openRightCanvasPanel, handleCloseCanvas, handleSelectRightPanel });
    return null;
  }
`,
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } },
).outputText;
const createHarness = new Function(
  'React',
  'localStorage',
  'expose',
  `${compiled}; return PreferenceHarness;`,
);
const key = 'agistack.desktop.rightSidebarOpen';

function memoryStorage(initial) {
  const values = new Map(initial === undefined ? [] : [[key, initial]]);
  const writes = [];
  return {
    values,
    writes,
    getItem(name) {
      return values.get(name) ?? null;
    },
    setItem(name, value) {
      values.set(name, value);
      writes.push([name, value]);
    },
  };
}

async function mount(storage) {
  let current;
  const Harness = createHarness(React, storage, (value) => {
    current = value;
  });
  const element = document.createElement('div');
  document.body.append(element);
  const root = createRoot(element);
  await act(async () => root.render(React.createElement(Harness)));
  return {
    get state() {
      return current;
    },
    async invoke(name, ...args) {
      await act(async () => current[name](...args));
    },
    async close() {
      await act(async () => root.unmount());
      element.remove();
    },
  };
}

test('first launch closes the panel and explicit visibility survives remounts', async () => {
  const storage = memoryStorage();
  let view = await mount(storage);
  try {
    assert.equal(view.state.rightSidebarOpen, false);
    await view.invoke('rememberRightSidebar', true);
    assert.equal(view.state.rightSidebarOpen, true);
    assert.equal(storage.getItem(key), 'true');
    await view.close();
    view = await mount(storage);
    assert.equal(view.state.rightSidebarOpen, true);
    await view.invoke('rememberRightSidebar', false);
    assert.equal(storage.getItem(key), 'false');
    await view.close();
    view = await mount(storage);
    assert.equal(view.state.rightSidebarOpen, false);
  } finally {
    await view.close();
  }
});

test('opening a canvas temporarily restores a closed panel without overwriting the saved preference', async () => {
  const storage = memoryStorage('false');
  const view = await mount(storage);
  try {
    await view.invoke('openRightCanvasPanel');
    assert.equal(view.state.rightSidebarOpen, true);
    assert.equal(view.state.activeRightPanel, 'canvas');
    assert.equal(view.state.rightSidebarOpenedForCanvas, true);
    await view.invoke('handleCloseCanvas');
    assert.equal(view.state.rightSidebarOpen, false);
    assert.equal(view.state.activeRightPanel, 'context');
    assert.equal(view.state.rightSidebarOpenedForCanvas, false);
    assert.equal(storage.writes.length, 0);
  } finally {
    await view.close();
  }
});

test('stable canvas callback reads the latest manual preference and keeps manually opened context visible', async () => {
  const storage = memoryStorage('false');
  const view = await mount(storage);
  try {
    const openCanvas = view.state.openRightCanvasPanel;
    await view.invoke('rememberRightSidebar', true);
    await act(async () => openCanvas());
    assert.equal(view.state.rightSidebarOpenedForCanvas, false);
    await view.invoke('handleCloseCanvas');
    assert.equal(view.state.rightSidebarOpen, true);
    await view.invoke('rememberRightSidebar', false);
    await act(async () => openCanvas());
    assert.equal(view.state.rightSidebarOpenedForCanvas, true);
    await view.invoke('handleCloseCanvas');
    assert.equal(view.state.rightSidebarOpen, false);
    assert.deepEqual(storage.writes, [
      [key, 'true'],
      [key, 'false'],
    ]);
  } finally {
    await view.close();
  }
});

test('explicit close cancels transient canvas state; storage failures do not prevent visibility changes', async () => {
  const storage = {
    getItem() {
      throw new Error('Storage unavailable');
    },
    setItem() {
      throw new Error('Storage unavailable');
    },
  };
  const view = await mount(storage);
  try {
    assert.equal(view.state.rightSidebarOpen, false);
    await view.invoke('openRightCanvasPanel');
    await view.invoke('rememberRightSidebar', false);
    assert.equal(view.state.rightSidebarOpen, false);
    assert.equal(view.state.rightSidebarOpenedForCanvas, false);
    await view.invoke('rememberRightSidebar', true);
    await view.invoke('openRightCanvasPanel');
    await view.invoke('handleCloseCanvas');
    assert.equal(view.state.rightSidebarOpen, true);
  } finally {
    await view.close();
  }
});

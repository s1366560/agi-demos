import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const webRequire = createRequire(new URL('../../../../web/package.json', import.meta.url));
const { Window } = webRequire('happy-dom');
const window = new Window({ url: 'http://localhost/' });
for (const key of ['window', 'document', 'navigator', 'HTMLElement', 'Element', 'Node']) {
  Object.defineProperty(globalThis, key, {
    configurable: true,
    value: key === 'window' ? window : window[key],
  });
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const React = require('react');
const { act } = React;
const { createRoot } = require('react-dom/client');
const ts = require('typescript');
const source = readFileSync(
  new URL('../src/features/sandbox/InteractiveTerminal.tsx', import.meta.url),
  'utf8'
);
const code = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.CommonJS,
    jsx: ts.JsxEmit.ReactJSX,
  },
}).outputText;

test('terminal fitting leaves the observer delivery, coalesces resize work and cancels on unmount', async () => {
  const frames = new Map();
  const observers = [];
  const terminals = [];
  let nextFrame = 0;
  let fits = 0;
  globalThis.requestAnimationFrame = (callback) => {
    frames.set(++nextFrame, callback);
    return nextFrame;
  };
  globalThis.cancelAnimationFrame = (id) => frames.delete(id);
  globalThis.ResizeObserver = class {
    constructor(callback) {
      this.callback = callback;
      observers.push(this);
    }
    observe() {}
    disconnect() {
      this.disconnected = true;
    }
  };
  class Terminal {
    cols = 80;
    rows = 24;
    constructor() {
      terminals.push(this);
    }
    loadAddon(addon) {
      addon.activate?.(this);
    }
    open() {}
    onData() {
      return { dispose() {} };
    }
    write() {}
    dispose() {
      this.disposed = true;
    }
  }
  class FitAddon {
    activate(terminal) {
      this.terminal = terminal;
    }
    fit() {
      fits += 1;
      this.terminal.cols = 90;
    }
  }
  const module = { exports: {} };
  new Function('require', 'module', 'exports', code)(
    (id) => {
      if (id.endsWith('.css')) return {};
      if (id === '@xterm/xterm') return { Terminal };
      if (id === '@xterm/addon-fit') return { FitAddon };
      if (id === '@xterm/addon-web-links') return { WebLinksAddon: class {} };
      if (id === './terminalLinkPolicy') return { isSafeTerminalLink: () => false };
      return require(id);
    },
    module,
    module.exports
  );
  const host = document.createElement('div');
  document.body.append(host);
  const root = createRoot(host);
  const sizes = [];
  await act(async () =>
    root.render(
      React.createElement(module.exports.InteractiveTerminal, {
        ariaLabel: 'terminal',
        connected: true,
        outputChunks: [],
        onInput() {},
        onResize: (...size) => sizes.push(size),
      })
    )
  );
  try {
    const observer = observers[0];
    observer.callback([]);
    observer.callback([]);
    assert.equal(fits, 0, 'observer delivery must not synchronously mutate terminal layout');
    assert.equal(frames.size, 1, 'initial and resize requests share one pending frame');
    const flushFrame = () => {
      const pending = [...frames.values()];
      frames.clear();
      for (const callback of pending) callback();
    };
    flushFrame();
    assert.equal(fits, 1);
    assert.deepEqual(sizes, [[90, 24]]);
    observer.callback([]);
    observer.callback([]);
    assert.equal(frames.size, 1);
    flushFrame();
    assert.equal(fits, 2);
    assert.equal(sizes.length, 1, 'unchanged terminal size is not resent');
    observer.callback([]);
    await act(async () => root.unmount());
    assert.equal(frames.size, 0, 'unmount cancels the latest pending fit');
    assert.equal(observer.disconnected, true);
    assert.equal(terminals[0].disposed, true);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

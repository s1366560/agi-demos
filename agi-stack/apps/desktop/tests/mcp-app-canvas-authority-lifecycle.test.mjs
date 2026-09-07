import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { webcrypto } from 'node:crypto';
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

function harness(overrides = {}) {
  const slots = [];
  let cursor = 0;
  let effects = [];
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    Component: class {},
    Suspense: 'Suspense',
    lazy: () => 'AppRenderer',
    createElement(type, props, ...children) {
      return { type, props: { ...props, children } };
    },
    useState(value) {
      const index = cursor++;
      slots[index] ??= { value };
      return [
        slots[index].value,
        (next) => {
          slots[index].value = next;
        },
      ];
    },
    useRef(value) {
      const index = cursor++;
      return (slots[index] ??= { current: value });
    },
    useMemo(factory, deps) {
      const index = cursor++;
      if (!equal(slots[index]?.deps, deps)) slots[index] = { value: factory(), deps };
      return slots[index].value;
    },
    useCallback(callback, deps) {
      return react.useMemo(() => callback, deps);
    },
    useEffect(effect, deps) {
      const index = cursor++;
      if (!equal(slots[index]?.deps, deps))
        effects.push(() => {
          slots[index]?.cleanup?.();
          slots[index] = { deps, effect, cleanup: effect() };
        });
    },
  };
  const cache = new Map();
  function load(url) {
    if (cache.has(url.href)) return cache.get(url.href);
    const module = { exports: {} };
    cache.set(url.href, module.exports);
    const code = ts.transpileModule(readFileSync(url, 'utf8'), {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
        jsx: ts.JsxEmit.React,
        esModuleInterop: true,
      },
    }).outputText;
    const localRequire = (name) => {
      if (name === 'react') return react;
      if (name === '../../i18n') return { useI18n: () => ({ t: (key) => key }) };
      if (name.endsWith('.css')) return {};
      if (name.startsWith('.')) return load(new URL(`${name}.ts`, url));
      return new Proxy({}, { get: (_, property) => property });
    };
    new Function('require', 'module', 'exports', 'crypto', code)(
      localRequire,
      module,
      module.exports,
      webcrypto,
    );
    return module.exports;
  }
  const bridge = load(new URL('../src/features/chat/mcpAppHostBridge.ts', import.meta.url));
  const { DesktopMCPAppCanvas } = load(
    new URL('../src/features/chat/DesktopMCPAppCanvas.tsx', import.meta.url),
  );
  const calls = { tools: [], direct: [], list: [], read: [], resources: [], messages: [] };
  const api = {
    async listMCPApps(...args) {
      calls.list.push(args);
      return [];
    },
    async callMCPAppTool(...args) {
      calls.tools.push(args);
      return { content: [], is_error: false };
    },
    async callMCPAppToolDirect(...args) {
      calls.direct.push(args);
      return { content: [], is_error: false };
    },
    async readMCPAppResource(...args) {
      calls.read.push(args);
      return { contents: [] };
    },
    async listMCPAppResources(...args) {
      calls.resources.push(args);
      return { resources: [] };
    },
    ...overrides,
  };
  const tab = {
    id: 'tab-one',
    appId: 'app-one',
    toolName: 'tool-one',
    serverName: 'server-one',
    resourceHtml: '<p>app</p>',
  };
  let props = {
    api,
    projectId: 'project-one',
    state: { tabs: [tab], activeTabId: tab.id },
    sandboxProxyUrl: 'https://sandbox.example/',
    onSendMessage: (value) => calls.messages.push(value),
    onSelect() {},
    onClose() {},
  };
  function find(node) {
    if (!node || typeof node !== 'object') return null;
    if (node.type === 'AppRenderer') return node.props;
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) {
        for (const child of value) {
          const result = find(child);
          if (result) return result;
        }
      } else {
        const result = find(value);
        if (result) return result;
      }
    }
    return null;
  }
  function render(next = {}) {
    props = { ...props, ...next };
    cursor = 0;
    effects = [];
    const tree = DesktopMCPAppCanvas(props);
    for (const effect of effects) effect();
    return find(tree);
  }
  return {
    render,
    calls,
    bridge,
    api,
    tab,
    unmount() {
      for (const slot of slots) slot?.cleanup?.();
    },
    replayEffects() {
      for (const slot of slots)
        if (slot?.effect) {
          slot.cleanup?.();
          slot.cleanup = slot.effect();
        }
    },
  };
}

for (const interruption of ['project', 'unmount']) {
  test(`Canvas cancels resource work and rejects old iframe callbacks after ${interruption}`, async () => {
    const wait = deferred();
    let observedSignal;
    const h = harness({
      async readMCPAppResource(...args) {
        observedSignal = args.at(-1);
        return wait.promise;
      },
    });
    const old = h.render();
    const pending = old.onReadResource({ uri: 'ui://server-one/view' });
    if (interruption === 'project') h.render({ projectId: 'project-two' });
    else h.unmount();
    assert.equal(observedSignal.aborted, true);
    wait.resolve({ contents: [] });
    await assert.rejects(pending, { name: 'AbortError' });
    await assert.rejects(old.onMessage({ content: [{ type: 'text', text: 'late message' }] }), {
      name: 'AbortError',
    });
    await assert.rejects(old.onCallTool({ name: 'late-tool' }), { name: 'AbortError' });
    assert.deepEqual(h.calls.messages, []);
    assert.deepEqual(h.calls.tools, []);
  });
}

test('Canvas aborts synthetic app discovery before it can issue a tool mutation', async () => {
  const wait = deferred();
  const entered = deferred();
  let signal;
  const h = harness({
    async listMCPApps(...args) {
      signal = args.at(-1);
      entered.resolve();
      return wait.promise;
    },
  });
  const old = h.render({
    state: { tabs: [{ ...h.tab, appId: '_synthetic_one' }], activeTabId: h.tab.id },
  });
  const pending = old.onCallTool({ name: 'tool-one', arguments: {} });
  await entered.promise;
  h.render({ projectId: 'project-two' });
  assert.equal(signal.aborted, true);
  wait.resolve([]);
  await assert.rejects(pending, { name: 'AbortError' });
  assert.deepEqual(h.calls.tools, []);
  assert.deepEqual(h.calls.direct, []);
});

test('Canvas forwards live signals and survives StrictMode effect replay', async () => {
  const h = harness();
  const current = h.render();
  h.replayEffects();
  await current.onCallTool({ name: 'tool-one', arguments: { count: 1 } });
  await current.onReadResource({ uri: 'ui://server-one/view' });
  await current.onListResources();
  for (const key of ['tools', 'read', 'resources']) {
    const signal = h.calls[key][0].at(-1);
    assert.ok(signal instanceof AbortSignal);
    assert.equal(signal.aborted, false);
  }
  await current.onMessage({ content: [{ type: 'text', text: 'continue' }] });
  assert.deepEqual(h.calls.messages, ['continue']);
});

test('Cloud in-band errors retain the exact persisted tool key; success retires it', async () => {
  const h = harness();
  const storage = new Map();
  let sequence = 0;
  const store = h.bridge.createMCPToolCallKeyStore(
    {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: (key) => storage.delete(key),
    },
    () => `attempt-${++sequence}`,
  );
  const context = {
    projectId: 'project-one',
    appId: 'app-one',
    serverName: 'server-one',
    originalToolName: 'tool-one',
  };
  const keys = [];
  let failed = true;
  const client = {
    ...h.api,
    async callMCPAppTool(...args) {
      keys.push(args[3]);
      return {
        content: [],
        is_error: failed,
        error_message: failed ? 'cloud_mcp_tool_idempotency_unavailable' : null,
        error_code: failed ? -32000 : null,
      };
    },
  };
  const params = { name: 'tool-one', arguments: { b: 2, a: 1 } };
  assert.equal((await h.bridge.callMCPAppTool(client, context, params, store)).isError, true);
  assert.equal(storage.size, 1);
  assert.equal((await h.bridge.callMCPAppTool(client, context, params, store)).isError, true);
  assert.equal(keys[0], keys[1]);
  failed = false;
  assert.equal((await h.bridge.callMCPAppTool(client, context, params, store)).isError, false);
  assert.equal(keys[1], keys[2]);
  assert.equal(storage.size, 0);
  await h.bridge.callMCPAppTool(client, context, params, store);
  assert.notEqual(keys[2], keys[3]);
});

test('cancellation while acquiring a retry key cannot start an app tool call', async () => {
  const h = harness();
  const key = deferred();
  const controller = new AbortController();
  let completed = 0;
  const pending = h.bridge.callMCPAppTool(
    h.api,
    {
      projectId: 'project-one',
      appId: 'app-one',
      serverName: 'server-one',
      originalToolName: 'tool-one',
    },
    { name: 'tool-one' },
    { acquire: () => key.promise, complete: () => completed++ },
    controller.signal,
  );
  controller.abort();
  key.resolve({ storageKey: 'key-storage', idempotencyKey: 'key-one' });
  await assert.rejects(pending, { name: 'AbortError' });
  assert.deepEqual(h.calls.tools, []);
  assert.equal(completed, 0);
});

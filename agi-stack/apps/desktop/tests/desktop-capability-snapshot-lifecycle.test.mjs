import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
const path = 'agi-stack/apps/desktop/src/features/runtime/useDesktopCapabilitySnapshot.ts';
const source = process.env.CORDIS_SNAPSHOT_PRECHANGE === '1'
  ? execFileSync('git', ['show', `HEAD:${path}`], { encoding: 'utf8' })
  : readFileSync(new URL('../src/features/runtime/useDesktopCapabilitySnapshot.ts', import.meta.url), 'utf8');
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}
function harness(client, enabled = true) {
  const slots = [];
  let cursor = 0;
  let pending = [];
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    useState(initial) {
      const i = cursor++;
      slots[i] ??= { value: initial };
      return [slots[i].value, (value) => { slots[i].value = typeof value === 'function' ? value(slots[i].value) : value; }];
    },
    useCallback(fn, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps)) slots[i] = { value: fn, deps };
      return slots[i].value;
    },
    useEffect(effect, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps)) pending.push(() => {
        slots[i]?.cleanup?.();
        slots[i] = { deps, cleanup: effect() };
      });
    },
  };
  const module = { exports: {} };
  new Function('require', 'module', 'exports', ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText)((name) => { assert.equal(name, 'react'); return react; }, module, module.exports);
  const render = (nextClient = client, nextEnabled = enabled) => {
    client = nextClient; enabled = nextEnabled; cursor = 0; pending = [];
    const value = module.exports.useDesktopCapabilitySnapshot(client, enabled);
    const effects = pending; pending = []; effects.forEach((effect) => effect());
    return value;
  };
  return { render, unmount() { for (const slot of slots) slot?.cleanup?.(); } };
}
const flush = async () => { for (let i = 0; i < 6; i++) await Promise.resolve(); };
test('client replacement ignores late old success and retains the new snapshot', async () => {
  const old = deferred(); const next = deferred(); const signals = [];
  const a = { loadSnapshot(signal) { signals.push(signal); return old.promise; } };
  const b = { loadSnapshot(signal) { signals.push(signal); return next.promise; } };
  const h = harness(a); h.render(); h.render(b);
  assert.equal(signals[0].aborted, true);
  next.resolve({ id: 'new' }); await flush();
  old.resolve({ id: 'old' }); await flush();
  assert.deepEqual(h.render().snapshot, { id: 'new' });
  assert.equal(h.render().loading, false);
});
test('disabled view performs no authority read and ignores a late enabled request', async () => {
  const pending = deferred(); let calls = 0; let signal;
  const client = { loadSnapshot(value) { calls++; signal = value; return pending.promise; } };
  const h = harness(client, false); h.render(); assert.equal(calls, 0);
  h.render(client, true); assert.equal(calls, 1);
  h.render(client, false); assert.equal(signal.aborted, true);
  pending.resolve({ id: 'late' }); await flush();
  assert.equal(h.render().snapshot, null); assert.equal(h.render().loading, false);
  assert.equal(calls, 1);
});
test('reload cancels the prior attempt and late failure cannot clear the current result', async () => {
  const first = deferred(); const second = deferred(); const signals = [];
  const client = { loadSnapshot(signal) { signals.push(signal); return signals.length === 1 ? first.promise : second.promise; } };
  const h = harness(client); h.render().reload(); h.render();
  assert.equal(signals[0].aborted, true);
  second.resolve({ id: 'fresh' }); await flush(); first.reject(new Error('old failure')); await flush();
  assert.deepEqual(h.render().snapshot, { id: 'fresh' }); assert.equal(signals.length, 2);
});
test('unmount aborts the request and a late success never writes a snapshot', async () => {
  const pending = deferred(); let signal;
  const h = harness({ loadSnapshot(value) { signal = value; return pending.promise; } });
  h.render(); h.unmount(); assert.equal(signal.aborted, true);
  pending.resolve({ id: 'late' }); await flush(); assert.equal(h.render().snapshot, null);
});

function appPublication() {
  const app = ts.createSourceFile('App.tsx', readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let initializer;
  const visit = (node) => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.name.text === 'desktopWorkbenchCapabilityClientV2') initializer = node.initializer;
    ts.forEachChild(node, visit);
  };
  visit(app);
  assert.ok(initializer, 'actual App snapshot publication must exist');
  const expression = ts.createPrinter().printNode(ts.EmitHint.Expression, initializer, app);
  const publish = new Function('useMemo', 'config', 'desktopWorkbenchSnapshotOperationsV2', 'desktopWorkbenchCapabilityClientProviderV2', 'desktopRendererGenerationV2', `return ${expression};`);
  const config = Object.freeze({ mode: 'local', projectId: 'project-1' });
  let actions;
  const operations = { loadSnapshot: (input) => actions.loadSnapshot(input) };
  const provider = { publish: (input) => ({ client: { loadSnapshot: (signal) => input.snapshotOperationsV2.loadSnapshot({ config: input.config, signal }) } }) };
  let cached;
  const useMemo = (fn, deps) => {
    if (!cached || deps.some((value, i) => value !== cached.deps[i])) cached = { deps, value: fn() };
    return cached.value;
  };
  return (nextActions) => {
    actions = nextActions;
    return publish(useMemo, config, operations, provider, { actions }).client;
  };
}
test('actual App publication retries a rejected empty generation when the host becomes ready', async () => {
  const publish = appPublication();
  let readyCalls = 0;
  const empty = { loadSnapshot: async () => { throw new Error('generation_unavailable'); } };
  const ready = { loadSnapshot: async () => { readyCalls++; return { id: 'ready' }; } };
  const first = publish(empty); const h = harness(first); h.render(); await flush();
  assert.equal(h.render().snapshot, null);
  h.render(publish(ready)); await flush();
  assert.equal(readyCalls, 1);
  assert.deepEqual(h.render().snapshot, { id: 'ready' });
  assert.equal(publish(ready), publish(ready), 'same generation rerender must retain client identity');
});
test('actual App HMR publication aborts old generation before its late snapshot completion', async () => {
  const publish = appPublication(); const pending = deferred(); let oldSignal;
  const old = { loadSnapshot: ({ signal }) => { oldSignal = signal; return pending.promise; } };
  const next = { loadSnapshot: async () => ({ id: 'new-generation' }) };
  const h = harness(publish(old)); h.render(); h.render(publish(next)); await flush();
  assert.equal(oldSignal.aborted, true);
  pending.resolve({ id: 'old-generation' }); await flush();
  assert.deepEqual(h.render().snapshot, { id: 'new-generation' });
});

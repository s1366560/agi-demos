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
  const render = (nextClient = client, nextEnabled = enabled, generation) => {
    client = nextClient; enabled = nextEnabled; cursor = 0; pending = [];
    const value = generation === undefined
      ? module.exports.useDesktopCapabilitySnapshot(client, enabled)
      : module.exports.useDesktopCapabilitySnapshot(
        client, enabled, generation.status, generation.digest, generation.error,
      );
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
  const first = publish(empty);
  const h = harness(first);
  h.render(first, true, { status: 'ready', digest: 'digest-a' });
  await flush();
  assert.equal(h.render().snapshot, null);
  const same = publish(ready);
  assert.equal(same, first, 'generation action identity must keep the capability client');
  h.render(same, true, { status: 'ready', digest: 'digest-b' });
  await flush();
  assert.equal(readyCalls, 1);
  assert.deepEqual(h.render().snapshot, { id: 'ready' });
});
test('actual App HMR publication aborts old generation before its late snapshot completion', async () => {
  const publish = appPublication();
  const pending = deferred();
  let oldSignal;
  const old = { loadSnapshot: ({ signal }) => { oldSignal = signal; return pending.promise; } };
  const next = { loadSnapshot: async () => ({ id: 'new-generation' }) };
  const first = publish(old);
  const h = harness(first);
  h.render(first, true, { status: 'ready', digest: 'digest-old' });
  const same = publish(next);
  assert.equal(same, first);
  h.render(same, true, { status: 'ready', digest: 'digest-new' });
  await flush();
  assert.equal(oldSignal.aborted, true);
  pending.resolve({ id: 'old-generation' });
  await flush();
  assert.deepEqual(h.render().snapshot, { id: 'new-generation' });
});

test('capability client publication ignores generation action identity', () => {
  const source = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
  const start = source.indexOf('const desktopWorkbenchCapabilityClientV2 = useMemo(');
  assert.notEqual(start, -1);
  const end = source.indexOf('const sandboxRuntime = useSandboxRuntimeSurface(', start);
  const block = source.slice(start, end);
  assert.equal(block.includes('desktopRendererGenerationV2.actions'), false);
  assert.equal(block.includes('snapshotOperationsV2'), true);
});
test('a slow remaining branch does not delay the entity observation', async () => {
  let release;
  const slow = new Promise((resolve) => { release = resolve; });
  const entity = Object.freeze({
    id: 'entities',
    capabilities: { 'project-project-entities': { availability: 'degraded' } },
  });
  const full = Object.freeze({ id: 'full' });
  const client = {
    loadSnapshot(_signal, observe) {
      observe(entity);
      return slow.then(() => full);
    },
  };
  const h = harness(client);
  h.render(client, true, { status: 'ready', digest: 'digest-1' });
  const published = h.render(client, true, { status: 'ready', digest: 'digest-1' });
  assert.equal(published.snapshot, entity);
  assert.equal(published.loading, false);
  let finished = false;
  release();
  const pending = slow.then(() => { finished = true; });
  await pending;
  await flush();
  assert.equal(finished, true);
  assert.equal(h.render(client, true, { status: 'ready', digest: 'digest-1' }).snapshot, full);
});
test('loading generation does not lease a capability snapshot', () => {
  let calls = 0;
  const client = { loadSnapshot() { calls++; return Promise.resolve({ id: 'early' }); } };
  const h = harness(client);
  const waiting = { status: 'loading', digest: '' };
  h.render(client, true, waiting);
  const state = h.render(client, true, waiting);
  assert.equal(calls, 0);
  assert.equal(state.snapshot, null);
  assert.equal(state.loading, true);
});
test('delayed generation and a route switch drop the previous snapshot', async () => {
  const first = deferred();
  const second = deferred();
  const signals = [];
  let calls = 0;
  const client = {
    loadSnapshot(signal) {
      signals.push(signal);
      calls += 1;
      return calls === 1 ? first.promise : second.promise;
    },
  };
  const h = harness(client);
  h.render(client, true, { status: 'loading', digest: '' });
  assert.equal(calls, 0);
  h.render(client, true, { status: 'ready', digest: 'digest-a' });
  assert.equal(calls, 1);
  h.render(client, true, { status: 'loading', digest: '' });
  assert.equal(signals[0].aborted, true);
  first.resolve({ id: 'old-route' });
  await flush();
  assert.equal(h.render(client, true, { status: 'loading', digest: '' }).snapshot, null);
  h.render(client, true, { status: 'ready', digest: 'digest-b' });
  second.resolve({ id: 'new-route' });
  await flush();
  assert.equal(calls, 2);
  assert.deepEqual(h.render(client, true, { status: 'ready', digest: 'digest-b' }).snapshot, { id: 'new-route' });
});
test('a ready generation loads once and an empty generation fails closed', async () => {
  const original = console.warn;
  const observations = [];
  console.warn = (...args) => observations.push(args);
  try {
    let calls = 0;
    const client = { loadSnapshot() { calls++; return Promise.resolve({ id: 'ready' }); } };
    const h = harness(client);
    const ready = { status: 'ready', digest: 'digest-1' };
    h.render(client, true, { status: 'loading', digest: '' });
    h.render(client, true, ready);
    await flush();
    assert.equal(calls, 1);
    assert.deepEqual(h.render(client, true, ready).snapshot, { id: 'ready' });
    h.render(client, true, { status: 'empty', digest: '' });
    assert.equal(calls, 1);
    assert.equal(h.render(client, true, { status: 'empty', digest: '' }).snapshot, null);
    assert.deepEqual(observations, [['[desktop-capability-snapshot]', 'desktop_renderer_generation_empty']]);
  } finally { console.warn = original; }
});
test('snapshot diagnostics log only protocol codes and retain fail-closed state', async () => {
  const original = console.warn;
  const observations = [];
  console.warn = (...args) => observations.push(args);
  try {
    const h = harness({ async loadSnapshot() {
      throw Object.assign(new Error('sensitive transport body'), { code: 'desktop_capability_snapshot_invalid:workspace_collaboration' });
    } });
    h.render(); await flush();
    assert.equal(h.render().snapshot, null);
    assert.deepEqual(observations, [['[desktop-capability-snapshot]', 'desktop_capability_snapshot_invalid:workspace_collaboration']]);
    h.unmount();
    observations.length = 0;
    const unsafe = harness({ async loadSnapshot() {
      throw Object.assign(new Error('sensitive raw message'), { code: 'https://example.test?token=private' });
    } });
    unsafe.render(); await flush();
    assert.deepEqual(observations, [['[desktop-capability-snapshot]', 'snapshot_load_failed']]);
    unsafe.unmount();
  } finally { console.warn = original; }
});

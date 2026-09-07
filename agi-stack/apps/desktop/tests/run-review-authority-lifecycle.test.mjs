import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const ts = require('typescript');
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, resolve, reject };
}
function harness(overrides = {}) {
  const slots = [];
  let cursor = 0;
  let effects = [];
  const equal = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
  const react = {
    useState(value) {
      const i = cursor++;
      slots[i] ??= { value };
      return [
        slots[i].value,
        (v) => {
          slots[i].value = typeof v === 'function' ? v(slots[i].value) : v;
        },
      ];
    },
    useRef(value) {
      return (slots[cursor++] ??= { current: value });
    },
    useMemo(fn, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps)) slots[i] = { deps, value: fn() };
      return slots[i].value;
    },
    useCallback(fn, deps) {
      return react.useMemo(() => fn, deps);
    },
    useEffect(effect, deps) {
      const i = cursor++;
      if (!equal(slots[i]?.deps, deps))
        effects.push(() => {
          slots[i]?.cleanup?.();
          slots[i] = { deps, effect, cleanup: effect() };
        });
    },
  };
  const cache = new Map();
  function load(url) {
    if (cache.has(url.href)) return cache.get(url.href);
    const module = { exports: {} };
    cache.set(url.href, module.exports);
    const code = ts.transpileModule(readFileSync(url, 'utf8'), {
      fileName: url.pathname,
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
      },
    }).outputText;
    new Function('require', 'module', 'exports', code)(
      (name) => {
        if (name === 'react') return react;
        if (name === '../../i18n')
          return { useI18n: () => ({ t: (key, args) => `${key}:${JSON.stringify(args)}` }) };
        return load(new URL(`${name}.ts`, url));
      },
      module,
      module.exports,
    );
    return module.exports;
  }
  const { useRunReviewAuthorityV2 } = load(
    new URL('../src/features/session/useRunReviewAuthorityV2.ts', import.meta.url),
  );
  const state = { summary: null, snapshot: null, loading: false, error: null, references: [] };
  const setter = (key) => (value) => {
    state[key] = typeof value === 'function' ? value(state[key]) : value;
  };
  let props = {
    config: { mode: 'cloud', projectId: 'p1', apiBaseUrl: 'https://cloud.invalid' },
    conversation: { id: 'c1', project_id: 'p1' },
    run: { id: 'r1', conversation_id: 'c1', project_id: 'p1', revision: 3, message_id: 'turn1' },
    scope: 'run',
    projectionOperations: { getRunSummary: async () => ({ run_id: 'r1' }) },
    changesOperations: { getRunChanges: async () => ({ id: 's1', environment_id: 'e1' }) },
    setSummary: setter('summary'),
    setSnapshot: setter('snapshot'),
    setLoading: setter('loading'),
    setError: setter('error'),
    setReferences: setter('references'),
    ...overrides,
  };
  function render(next = {}) {
    props = { ...props, ...next };
    cursor = 0;
    effects = [];
    const result = useRunReviewAuthorityV2(props);
    for (const effect of effects) effect();
    return result;
  }
  return {
    render,
    state,
    unmount() {
      for (const slot of slots) slot?.cleanup?.();
    },
    replay() {
      for (const slot of slots)
        if (slot?.effect) {
          slot.cleanup?.();
          slot.cleanup = slot.effect();
        }
    },
  };
}

const tick = async () => {
  for (let i = 0; i < 6; i++) await Promise.resolve();
};
for (const change of ['config', 'conversation', 'run', 'operations', 'unmount']) {
  test(`${change} aborts summary and changes and blocks late results/loading/error updates`, async () => {
    const summary = deferred();
    const changes = deferred();
    let summarySignal;
    let changeSignal;
    const h = harness({
      projectionOperations: {
        getRunSummary: (input) => {
          summarySignal = input.signal;
          return summary.promise;
        },
      },
      changesOperations: {
        getRunChanges: (input) => {
          changeSignal = input.signal;
          return changes.promise;
        },
      },
    });
    const oldReload = h.render();
    const oldSummarySignal = summarySignal;
    const oldChangeSignal = changeSignal;
    if (change === 'unmount') h.unmount();
    else
      h.render({
        ...{
          config: {
            config: { mode: 'local', projectId: 'p2', apiBaseUrl: 'http://local.invalid' },
          },
          conversation: { conversation: { id: 'c2', project_id: 'p1' } },
          run: { run: null },
          operations: {
            projectionOperations: { getRunSummary: async () => ({ fresh: true }) },
            changesOperations: {
              getRunChanges: async () => ({ id: 'fresh', environment_id: 'e1' }),
            },
          },
        }[change],
      });
    assert.equal(oldSummarySignal.aborted, true);
    assert.equal(oldChangeSignal.aborted, true);
    await tick();
    const expected = { ...h.state };
    await oldReload();
    summary.resolve({ stale: true });
    changes.reject(new Error('old failure'));
    await tick();
    assert.deepEqual(h.state, expected);
    if (change !== 'unmount') h.unmount();
  });
}
test('manual refresh cancels its predecessor without clearing the newer loading flag', async () => {
  const waits = [deferred(), deferred()];
  const inputs = [];
  const h = harness({
    changesOperations: {
      getRunChanges: (input) => {
        inputs.push(input);
        return waits[inputs.length - 1].promise;
      },
    },
  });
  const reload = h.render();
  const second = reload();
  assert.equal(inputs[0].signal.aborted, true);
  waits[0].reject(new Error('old'));
  await tick();
  assert.equal(h.state.loading, true);
  assert.equal(h.state.error, null);
  h.state.references = [
    { snapshot_id: 'new', environment_id: 'e1' },
    { snapshot_id: 'old', environment_id: 'e1' },
  ];
  waits[1].resolve({ id: 'new', environment_id: 'e1' });
  await second;
  assert.equal(h.state.snapshot.id, 'new');
  assert.equal(h.state.loading, false);
  assert.equal(h.state.references.length, 1);
  h.unmount();
});
test('scope changes cancel the preceding request and forward exact turn/run/session options', async () => {
  const inputs = [];
  const waits = [];
  const h = harness({
    changesOperations: {
      getRunChanges: (input) => {
        inputs.push(input);
        const wait = deferred();
        waits.push(wait);
        return wait.promise;
      },
    },
  });
  h.render({ scope: 'turn' });
  assert.equal(inputs[0].turnId, 'turn1');
  assert.equal(inputs[0].scope, 'turn');
  assert.equal(inputs[0].expectedRevision, 3);
  h.render({ scope: 'session' });
  assert.equal(inputs[0].signal.aborted, true);
  assert.equal(inputs[1].scope, 'session');
  assert.equal(inputs[1].turnId, undefined);
  waits[0].resolve({ id: 'old' });
  await tick();
  assert.equal(h.state.snapshot, null);
  assert.equal(h.state.loading, true);
  waits[1].resolve({ id: 'session' });
  await tick();
  assert.equal(h.state.snapshot.id, 'session');
  h.unmount();
});
test('Local retains run-only changes and does not request unavailable summary', async () => {
  let summaries = 0;
  let changes = 0;
  const h = harness({
    config: { mode: 'local', projectId: 'p1', apiBaseUrl: 'http://local.invalid' },
    projectionOperations: {
      getRunSummary: async () => {
        summaries++;
        return {};
      },
    },
    changesOperations: {
      getRunChanges: async () => {
        changes++;
        return { id: 'local' };
      },
    },
  });
  h.render();
  await tick();
  assert.equal(summaries, 0);
  assert.equal(changes, 1);
  assert.equal(h.state.snapshot.id, 'local');
  h.render({ scope: 'turn' });
  await tick();
  assert.equal(changes, 1);
  assert.match(h.state.error, /local_run_changes_scope_unavailable/);
  h.unmount();
});
test('StrictMode replay acquires fresh requests while missing/mismatched conversations do not fetch', async () => {
  const inputs = [];
  const h = harness({
    projectionOperations: {
      getRunSummary: async (input) => {
        inputs.push(input);
        return {};
      },
    },
  });
  h.render();
  h.replay();
  assert.equal(inputs.length, 2);
  assert.equal(inputs[0].signal.aborted, true);
  assert.equal(inputs[1].signal.aborted, false);
  h.render({ conversation: null });
  await tick();
  assert.equal(inputs.length, 2);
  assert.equal(h.state.summary, null);
  assert.equal(h.state.snapshot, null);
  h.render({ conversation: { id: 'wrong', project_id: 'p1' } });
  await tick();
  assert.equal(inputs.length, 2);
  h.unmount();
});

test('caller cancellation is forwarded and clears only its own loading state without publishing an error', async () => {
  const waits = [deferred(), deferred()];
  const inputs = [];
  const h = harness({
    changesOperations: {
      getRunChanges: (input) => {
        inputs.push(input);
        return waits[inputs.length - 1].promise;
      },
    },
  });
  const reload = h.render();
  const controller = new AbortController();
  const pending = reload(controller.signal);
  controller.abort();
  assert.equal(inputs[1].signal.aborted, true);
  waits[1].resolve({ id: 'cancelled' });
  await pending;
  assert.equal(h.state.snapshot, null);
  assert.equal(h.state.loading, false);
  assert.equal(h.state.error, null);
  waits[0].resolve({ id: 'older' });
  await tick();
  assert.equal(h.state.snapshot, null);
  h.unmount();
});

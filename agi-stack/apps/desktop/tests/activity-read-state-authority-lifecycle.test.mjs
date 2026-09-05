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
function harness(client) {
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
  const { useActivityInbox } = load(
    new URL('../src/features/activity/useActivityInbox.ts', import.meta.url),
  );
  let props = { items, scopeKey: 'scope', activityClientV2: client, authorityScope: scope };
  function render(next = {}) {
    props = { ...props, ...next };
    cursor = 0;
    effects = [];
    const result = useActivityInbox(props);
    for (const effect of effects) effect();
    return result;
  }
  return {
    render,
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

const scope = { authority: 'cloud', principalId: 'user1', tenantId: 't1', projectId: 'p1' };
const items = ['one', 'two'].map((id) => ({
  authority_kind: 'desktop_run',
  authority_id: id,
  conversation_id: id,
  project_id: 'p1',
  workspace_id: 'w1',
  title: id,
  capability_mode: 'code',
  group: 'ready_review',
  status: 'ready_review',
  required_action: 'review_result',
  summary: null,
  revision: 2,
  created_at: '2026-07-13T01:00:00Z',
  updated_at: '2026-07-13T04:00:00Z',
}));
const tick = async () => {
  for (let i = 0; i < 8; i++) await Promise.resolve();
};
const synced = (revision = 3, entries = []) => ({
  kind: 'synced',
  state: { project_id: 'p1', authority_revision: revision, entries },
});
function fixture(overrides = {}) {
  return {
    flushPendingActivityReadState: async () => synced(),
    getActivityReadState: async () => synced().state,
    putActivityReadState: async (_scope, request) =>
      synced(request.expected_authority_revision + 1, request.entries),
    ...overrides,
  };
}
for (const change of ['project', 'tenant', 'principal', 'authority', 'client', 'unmount']) {
  test(`${change} aborts in-flight write, blocks its queued follower and stale callbacks`, async () => {
    const wait = deferred();
    let signal;
    let calls = 0;
    let recovery = 0;
    const client = fixture({
      putActivityReadState: (_scope, _request, options) => {
        calls++;
        signal = options.signal;
        return wait.promise;
      },
      getActivityReadState: async () => {
        recovery++;
        return synced().state;
      },
    });
    const h = harness(client);
    h.render();
    await tick();
    const old = h.render();
    old.markRead(old.entries[0].id);
    old.markRead(old.entries[1].id);
    await tick();
    if (change === 'unmount') h.unmount();
    else if (change === 'client') h.render({ activityClientV2: fixture() });
    else {
      const field = {
        project: 'projectId',
        tenant: 'tenantId',
        principal: 'principalId',
        authority: 'authority',
      }[change];
      h.render({ authorityScope: { ...scope, [field]: change === 'authority' ? 'local' : 'new' } });
    }
    assert.equal(signal.aborted, true);
    old.markAllRead();
    wait.reject(new Error('old request failed'));
    await tick();
    assert.equal(calls, 1);
    assert.equal(recovery, 0);
    if (change !== 'unmount') {
      await tick();
      assert.equal(h.render().unreadCount, 2);
      h.unmount();
    }
  });
}
test('initialization buffers clicks and serial writes use the preceding acknowledged revision', async () => {
  const load = deferred();
  const writes = [];
  const waits = [deferred(), deferred()];
  const h = harness(
    fixture({
      flushPendingActivityReadState: () => load.promise,
      putActivityReadState: (_scope, request, options) => {
        writes.push({ request, options });
        return waits[writes.length - 1].promise;
      },
    }),
  );
  let api = h.render();
  api.markRead(api.entries[0].id);
  await tick();
  assert.equal(writes.length, 0);
  load.resolve(synced(7));
  await tick();
  assert.equal(writes.length, 1);
  assert.equal(writes[0].request.expected_authority_revision, 7);
  api = h.render();
  api.markRead(api.entries[1].id);
  await tick();
  assert.equal(writes.length, 1);
  waits[0].resolve(synced(9, writes[0].request.entries));
  await tick();
  assert.equal(writes.length, 2);
  assert.equal(writes[1].request.expected_authority_revision, 9);
  assert.equal(writes[1].request.entries.length, 2);
  assert.ok(writes[1].options.signal);
  waits[1].resolve(synced(10, writes[1].request.entries));
  await tick();
  assert.equal(h.render().unreadCount, 0);
  h.unmount();
});
test('write failure recovery is cancellable and cannot overwrite the next scope', async () => {
  const wait = deferred();
  let signal;
  const h = harness(
    fixture({
      putActivityReadState: async () => {
        throw new Error('409');
      },
      getActivityReadState: (_scope, options) => {
        signal = options.signal;
        return wait.promise;
      },
    }),
  );
  h.render();
  await tick();
  h.render().markAllRead();
  await tick();
  assert.ok(signal);
  h.render({ authorityScope: { ...scope, projectId: 'p2' }, activityClientV2: fixture() });
  assert.equal(signal.aborted, true);
  wait.resolve(
    synced(88, [
      { entry_id: 'desktop_run:one', entry_revision: 2, read_at: '2026-09-06T00:00:00Z' },
    ]).state,
  );
  await tick();
  assert.equal(h.render().unreadCount, 2);
  h.unmount();
});
test('offline receipts remain degraded and optimistic until the next successful write', async () => {
  let offline = true;
  const h = harness(
    fixture({
      putActivityReadState: async (_scope, request) =>
        offline
          ? {
              kind: 'queued_offline',
              availability: 'degraded',
              reasonCode: 'cloud_activity_read_state_offline_retry_pending',
              expectedAuthorityRevision: request.expected_authority_revision,
              entries: request.entries,
            }
          : synced(4, request.entries),
    }),
  );
  h.render();
  await tick();
  h.render().markAllRead();
  await tick();
  assert.equal(h.render().unreadCount, 0);
  assert.equal(h.render().availability, 'degraded');
  assert.equal(h.render().reasonCode, 'cloud_activity_read_state_offline_retry_pending');
  offline = false;
  h.render().markAllRead();
  await tick();
  assert.equal(h.render().availability, 'available');
  h.unmount();
});
test('StrictMode replay cancels old flush and pending callbacks; equivalent scope objects do not reload', async () => {
  const waits = [deferred(), deferred()];
  const signals = [];
  let writes = 0;
  const h = harness(
    fixture({
      flushPendingActivityReadState: (_scope, options) => {
        signals.push(options.signal);
        return waits[signals.length - 1].promise;
      },
      putActivityReadState: async (_scope, request) => {
        writes++;
        return synced(4, request.entries);
      },
    }),
  );
  const api = h.render();
  api.markAllRead();
  h.replay();
  assert.equal(signals[0].aborted, true);
  waits[0].resolve(synced());
  await tick();
  assert.equal(writes, 0);
  waits[1].resolve(synced());
  await tick();
  assert.equal(h.render().unreadCount, 2);
  h.render({ authorityScope: { ...scope } });
  assert.equal(signals.length, 2);
  h.unmount();
  api.markAllRead();
  await tick();
  assert.equal(writes, 0);
});
test('missing scope never acquires or writes even through UI mark callbacks', async () => {
  let calls = 0;
  const h = harness(
    fixture({
      flushPendingActivityReadState: async () => {
        calls++;
        return synced();
      },
    }),
  );
  const api = h.render({ authorityScope: null });
  api.markAllRead();
  await tick();
  assert.equal(calls, 0);
  assert.equal(h.render().availability, 'unavailable');
  h.unmount();
});

test('scope switch during initialization cancels flush and drops only the old pending UI marks', async () => {
  const wait = deferred();
  let signal;
  let writes = 0;
  const h = harness(
    fixture({
      flushPendingActivityReadState: (_scope, options) => {
        signal = options.signal;
        return wait.promise;
      },
      putActivityReadState: async (_scope, request) => {
        writes++;
        return synced(4, request.entries);
      },
    }),
  );
  const old = h.render();
  old.markAllRead();
  h.render({ authorityScope: { ...scope, projectId: 'p2' }, activityClientV2: fixture() });
  assert.equal(signal.aborted, true);
  wait.resolve(synced());
  await tick();
  assert.equal(writes, 0);
  assert.equal(h.render().unreadCount, 2);
  h.unmount();
});

test('failed write recovery supplies the revision for a following queued write', async () => {
  const revisions = [];
  let reads = 0;
  const h = harness(
    fixture({
      putActivityReadState: async (_scope, request) => {
        revisions.push(request.expected_authority_revision);
        if (revisions.length === 1) throw new Error('409');
        return synced(12, request.entries);
      },
      getActivityReadState: async (_scope, options) => {
        reads++;
        assert.ok(options.signal);
        return synced(11).state;
      },
    }),
  );
  h.render();
  await tick();
  const api = h.render();
  api.markRead(api.entries[0].id);
  api.markRead(api.entries[1].id);
  await tick();
  await tick();
  assert.equal(reads, 1);
  assert.deepEqual(revisions, [3, 11]);
  assert.equal(h.render().availability, 'available');
  h.unmount();
});

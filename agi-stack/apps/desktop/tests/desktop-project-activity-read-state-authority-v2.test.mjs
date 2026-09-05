import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const m = require(`${ROOT}/src/plugins/desktopProjectActivityReadStateAuthorityModuleV2.js`);
const p = require(`${ROOT}/src/plugins/desktopProjectActivityReadStateHttpProjectionV2.js`);
const { DesktopApiError } = require(`${ROOT}/src/api/client.js`);
const config = (mode = 'local') => ({
  apiBaseUrl: mode === 'local' ? 'http://127.0.0.1:43117' : 'https://api.test',
  deviceAuthorizationBaseUrl: 'https://api.test',
  apiKey: 'trusted-session',
  localApiToken: mode === 'local' ? 'private-launch' : '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode,
  workspaceRoot: '',
});
const scope = (mode = 'local') => ({
  authority: mode,
  principalId: mode === 'local' ? 'local-user' : 'user-1',
  tenantId: 'tenant-1',
  projectId: 'project-1',
});
const entry = { entry_id: 'entry-1', entry_revision: 2, read_at: '2026-09-05T00:00:00Z' };
const state = { project_id: 'project-1', authority_revision: 3, entries: [entry] };
const json = (value, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
});
function fixture(mode = 'local') {
  const events = [];
  let pending = [];
  const retryStore = {
    load() {
      events.push('load');
      return pending;
    },
    save(_scope, entries) {
      events.push('save');
      pending = [...entries];
    },
    clear() {
      throw new Error('must acknowledge');
    },
    acknowledge(_scope, entries) {
      events.push('ack');
      pending = pending.filter(
        (e) =>
          !entries.some(
            (s) =>
              s.entry_id === e.entry_id &&
              s.entry_revision >= e.entry_revision &&
              Date.parse(s.read_at) >= Date.parse(e.read_at),
          ),
      );
    },
  };
  const runtime = config(mode);
  const ops = m.createDesktopProjectActivityReadStateOperationsV2(() => ({
    async acquireServiceOperationLease(descriptor) {
      events.push(['acquire', descriptor]);
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation: (frozen) =>
              p.createDesktopProjectActivityReadStateHttpProjectionV2(frozen, { retryStore }),
          }),
        async release() {
          events.push('release');
        },
      };
    },
  }));
  return {
    client: m.createDesktopProjectActivityReadStateClientV2(ops, runtime),
    ops,
    events,
    retryStore,
  };
}
test('Activity V2 Local GET has exact project lease and private launch transport', async () => {
  globalThis.fetch = async (url, init) => {
    assert.equal(new URL(url).pathname, '/api/v1/projects/project-1/activity/read-state');
    assert.equal(new Headers(init.headers).get('x-agistack-launch'), 'private-launch');
    return json(state);
  };
  const f = fixture();
  assert.deepEqual(await f.client.getActivityReadState(scope()), state);
  assert.deepEqual(f.events[0][1].scope, {
    kind: 'project',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
  });
  assert.equal(f.events.at(-1), 'release');
});
test('Activity V2 Cloud preflight mismatch prevents receipt transport', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return json({ id: 'other', tenant_id: 'tenant-1' });
  };
  await assert.rejects(
    fixture('cloud').client.getActivityReadState(scope('cloud')),
    /project_mismatch/u,
  );
  assert.equal(calls, 1);
});
test('Activity V2 flush GET and PUT plus acknowledgement share one lease', async () => {
  const f = fixture('cloud');
  f.retryStore.save(scope('cloud'), [entry]);
  f.events.length = 0;
  globalThis.fetch = async (url, init) => {
    f.events.push(init.method);
    if (new URL(url).pathname === '/api/v1/projects/project-1')
      return json({ id: 'project-1', tenant_id: 'tenant-1' });
    if (init.method === 'PUT')
      assert.deepEqual(JSON.parse(init.body), { expected_authority_revision: 3, entries: [entry] });
    return json(state);
  };
  assert.deepEqual(await f.client.flushPendingActivityReadState(scope('cloud')), {
    kind: 'synced',
    state,
  });
  assert.deepEqual(
    f.events.map((e) => (Array.isArray(e) ? e[0] : e)),
    ['acquire', 'GET', 'load', 'GET', 'PUT', 'ack', 'release'],
  );
});
test('Activity V2 PUT network failure queues but GET failure does not', async () => {
  const f = fixture();
  globalThis.fetch = async () => {
    throw new TypeError('network');
  };
  const result = await f.client.putActivityReadState(scope(), {
    expected_authority_revision: 3,
    entries: [entry],
  });
  assert.equal(result.kind, 'queued_offline');
  assert.ok(f.events.includes('save'));
  f.events.length = 0;
  await assert.rejects(f.client.flushPendingActivityReadState(scope()), /network_unavailable/u);
  assert.equal(f.events.includes('save'), false);
});
test('Activity V2 direct HTTP 503 including native marker stays error', async () => {
  for (const reason_code of ['activity_read_state_transport_unavailable', 'unrelated']) {
    const f = fixture('cloud');
    globalThis.fetch = async (_url, init) =>
      init.method === 'GET'
        ? json({ id: 'project-1', tenant_id: 'tenant-1' })
        : json({ reason_code }, 503);
    await assert.rejects(
      f.client.putActivityReadState(scope('cloud'), {
        expected_authority_revision: 3,
        entries: [entry],
      }),
      (error) => error.status === 503,
    );
    assert.equal(f.events.includes('save'), false);
  }
});
test('Activity V2 CAS conflicts and malformed responses never queue or acknowledge', async () => {
  for (const response of [
    () => json({ detail: 'revision conflict' }, 409),
    () => json({ ...state, project_id: 'other' }),
    () => new Response('bad', { headers: { 'Content-Type': 'application/json' } }),
  ]) {
    const f = fixture();
    globalThis.fetch = async () => response();
    await assert.rejects(
      f.client.putActivityReadState(scope(), { expected_authority_revision: 3, entries: [entry] }),
    );
    assert.equal(f.events.includes('save'), false);
    assert.equal(f.events.includes('ack'), false);
    assert.equal(f.events.at(-1), 'release');
  }
});
test('Activity V2 captures immutable input before admission and rejects wrong scope before lease', async () => {
  let proceed;
  const wait = new Promise((resolve) => {
    proceed = resolve;
  });
  let captured;
  let acquisitions = 0;
  const ops = m.createDesktopProjectActivityReadStateOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions++;
      await wait;
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation: () => ({
              async execute(_method, input) {
                captured = input;
                return { kind: 'synced', state };
              },
            }),
          }),
        async release() {},
      };
    },
  }));
  const runtime = config();
  const currentScope = scope();
  const request = { expected_authority_revision: 3, entries: [{ ...entry }] };
  const job = ops.putActivityReadState({ config: runtime, scope: currentScope, request });
  runtime.tenantId = 'other';
  currentScope.projectId = 'other';
  request.entries[0].entry_revision = 99;
  proceed();
  await job;
  assert.equal(captured.config.tenantId, 'tenant-1');
  assert.equal(captured.scope.projectId, 'project-1');
  assert.equal(captured.request.entries[0].entry_revision, 2);
  assert.ok(Object.isFrozen(captured.request.entries[0]));
  await assert.rejects(
    ops.getActivityReadState({ config: config(), scope: { ...scope(), tenantId: 'other' } }),
    /scope_mismatch/u,
  );
  assert.equal(acquisitions, 1);
});
test('Activity V2 blank tenant constructs without effects and rejects before admission', async () => {
  let acquisitions = 0;
  const ops = m.createDesktopProjectActivityReadStateOperationsV2(() => ({
    async acquireServiceOperationLease() {
      acquisitions++;
      throw new Error('unexpected');
    },
  }));
  const client = m.createDesktopProjectActivityReadStateClientV2(ops, {
    ...config('cloud'),
    tenantId: '',
    projectId: '',
  });
  await assert.rejects(
    client.getActivityReadState({ ...scope('cloud'), tenantId: '', projectId: '' }),
    /scope_invalid/u,
  );
  assert.equal(acquisitions, 0);
});
test('Activity V2 abort after HTTP prevents retry acknowledgement and queue writes', async () => {
  for (const fail of [false, true]) {
    const f = fixture();
    const controller = new AbortController();
    globalThis.fetch = async () => {
      controller.abort();
      if (fail) throw new TypeError('network');
      return json(state);
    };
    await assert.rejects(
      f.client.putActivityReadState(
        scope(),
        { expected_authority_revision: 3, entries: [entry] },
        { signal: controller.signal },
      ),
      { name: 'AbortError' },
    );
    assert.equal(f.events.includes('save'), false);
    assert.equal(f.events.includes('ack'), false);
  }
});
test('Activity V2 delayed admission abort and escaped callback never rebind', async () => {
  let proceed,
    callback,
    binds = 0,
    releases = 0;
  const wait = new Promise((resolve) => {
    proceed = resolve;
  });
  const service = {
    bindOperation() {
      binds++;
      return { execute: async () => state };
    },
  };
  const ops = m.createDesktopProjectActivityReadStateOperationsV2(() => ({
    async acquireServiceOperationLease() {
      await wait;
      return {
        status: 'accepted',
        useService: (use) => {
          callback = use;
          return use(service);
        },
        async release() {
          releases++;
        },
      };
    },
  }));
  const controller = new AbortController();
  const job = m
    .createDesktopProjectActivityReadStateClientV2(ops, config())
    .getActivityReadState(scope(), { signal: controller.signal });
  controller.abort();
  proceed();
  await assert.rejects(job, { name: 'AbortError' });
  assert.equal(binds, 0);
  assert.equal(releases, 1);
  await assert.rejects(callback(service), /released/u);
});
test('Activity V2 release failure preserves the original CAS error', async () => {
  const failure = new DesktopApiError('conflict', 409, {});
  const ops = m.createDesktopProjectActivityReadStateOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation: () => ({
              async execute() {
                throw failure;
              },
            }),
          }),
        async release() {
          throw new Error('secondary');
        },
      };
    },
  }));
  await assert.rejects(
    m.createDesktopProjectActivityReadStateClientV2(ops, config()).getActivityReadState(scope()),
    (e) => e === failure,
  );
});
test('Activity V2 policy denial is not an offline receipt', async () => {
  const f = fixture('cloud');
  globalThis.fetch = async (url, init) => {
    if (init.method === 'GET') return json({ id: 'project-1', tenant_id: 'tenant-1' });
    throw new Error('cloud_request_endpoint_not_allowed');
  };
  await assert.rejects(
    f.client.putActivityReadState(scope('cloud'), {
      expected_authority_revision: 3,
      entries: [entry],
    }),
    /endpoint_not_allowed/u,
  );
  assert.equal(f.events.includes('save'), false);
});

test('Activity Read State V2 real Loader publishes project-resolvable service and disabled next generation removes it', async () => {
  const runtime = require('@agistack/plugin-runtime');
  const authorities = readdirSync(`${ROOT}/src/plugins`)
    .filter((name) => /AuthorityModules?V2\.js$/u.test(name))
    .flatMap((name) =>
      Object.values(require(`${ROOT}/src/plugins/${name}`)).filter(
        (value) => value?.moduleRef && typeof value.apply === 'function',
      ),
    );
  const profile = JSON.parse(
    readFileSync(
      new URL('../../../../shared/profiles/memstack-default-bootstrap.v2.json', import.meta.url),
      'utf8',
    ),
  );
  const loader = new runtime.LoaderV2(
    [...runtime.createDesktopRendererDefinitionsV2(), ...authorities],
    'desktop-renderer',
  );
  const generation = await loader.stage(profile);
  const scope = { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' };
  try {
    const service = generation.resolve(
      m.DESKTOP_PROJECT_ACTIVITY_READ_STATE_AUTHORITY_SERVICE_V2,
      scope,
      {
        version: '1.0.0',
      },
    );
    assert.equal(typeof service.bindOperation(config()).execute, 'function');
    const disabled = structuredClone(profile);
    disabled.entries.find(
      (entry) => entry.entry_id === 'builtin-desktop-project-activity-read-state-authority',
    ).enabled = false;
    const next = await loader.stage(disabled);
    try {
      assert.throws(
        () =>
          next.resolve(m.DESKTOP_PROJECT_ACTIVITY_READ_STATE_AUTHORITY_SERVICE_V2, scope, {
            version: '1.0.0',
          }),
        (error) => error.code === 'missing_service',
      );
      assert.equal(typeof service.bindOperation(config()).execute, 'function');
      const { acquireDesktopRendererServiceOperationLeaseV2 } = require(
        `${ROOT}/src/plugins/desktopRendererServiceOperationLeaseV2.js`,
      );
      const manager = new runtime.GenerationManagerV2();
      await manager.publish(next);
      let requests = 0;
      globalThis.fetch = async () => {
        requests++;
        return json(state);
      };
      const disabledOps = m.createDesktopProjectActivityReadStateOperationsV2(() => ({
        acquireServiceOperationLease: (request) =>
          acquireDesktopRendererServiceOperationLeaseV2(manager.current, request, (generation) =>
            manager.acquire(generation),
          ),
      }));
      await assert.rejects(
        m
          .createDesktopProjectActivityReadStateClientV2(disabledOps, config())
          .getActivityReadState({
            authority: 'local',
            principalId: 'local-user',
            tenantId: 'tenant-1',
            projectId: 'project-1',
          }),
        /service_resolve_failed/u,
      );
      assert.equal(requests, 0);
      assert.equal(next.leaseCount, 0);
      await manager.close();
    } finally {
      await next.dispose();
    }
  } finally {
    await generation.dispose();
  }
});
test('Activity V2 actual vault broker keeps identity private and queues exact native transport failure', async () => {
  const { executeVaultBoundCloudRequest } = require(`${ROOT}/electron/main/cloudRequestPolicy.js`);
  let fallback = 0,
    puts = 0;
  globalThis.fetch = async () => {
    fallback++;
    throw new Error('forbidden fallback');
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, args) {
          assert.equal(command, 'cloud_request');
          return executeVaultBoundCloudRequest(args.request, {
            async loadTrustedSession() {
              return {
                version: 1,
                api_base_url: 'https://api.test',
                runtime_mode: 'cloud',
                credential_kind: 'cloud_bearer',
                credential: 'private-test-session',
                expires_at: null,
              };
            },
            async fetch(url, init) {
              const path = new URL(url).pathname;
              if (path === '/api/v1/workspace-context')
                return json({
                  context: {
                    tenant_id: 'tenant-1',
                    project_id: 'project-1',
                    workspace_id: 'workspace-1',
                  },
                });
              if (path === '/api/v1/projects/project-1')
                return json({ id: 'project-1', tenant_id: 'tenant-1' });
              assert.equal(path, '/api/v1/projects/project-1/activity/read-state');
              assert.equal(init.method, 'PUT');
              puts++;
              throw new TypeError('offline');
            },
          });
        },
      },
    },
  };
  const f = fixture('cloud');
  const client = m.createDesktopProjectActivityReadStateClientV2(f.ops, {
    ...config('cloud'),
    apiKey: '',
  });
  const result = await client.putActivityReadState(scope('cloud'), {
    expected_authority_revision: 3,
    entries: [entry],
  });
  assert.equal(result.kind, 'queued_offline');
  assert.equal(puts, 1);
  assert.equal(fallback, 0);
});
test('Activity V2 native IPC contract TypeError is never misclassified as offline', async () => {
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(_command, args) {
          if (args.request.path.endsWith('/activity/read-state'))
            throw new TypeError('invalid IPC result');
          return { status: 200, body: { id: 'project-1', tenant_id: 'tenant-1' } };
        },
      },
    },
  };
  const f = fixture('cloud');
  const client = m.createDesktopProjectActivityReadStateClientV2(f.ops, {
    ...config('cloud'),
    apiKey: '',
  });
  await assert.rejects(
    client.putActivityReadState(scope('cloud'), {
      expected_authority_revision: 3,
      entries: [entry],
    }),
    /invalid IPC/u,
  );
  assert.equal(f.events.includes('save'), false);
});
test('Activity V2 duplicate lease callback cannot repeat persistent mutation', async () => {
  let callback,
    calls = 0,
    resolve;
  const wait = new Promise((r) => {
    resolve = r;
  });
  const service = {
    bindOperation: () => ({
      async execute() {
        calls++;
        await wait;
        return { kind: 'synced', state };
      },
    }),
  };
  const ops = m.createDesktopProjectActivityReadStateOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'accepted',
        useService: (use) => {
          callback = use;
          return use(service);
        },
        async release() {},
      };
    },
  }));
  const job = m
    .createDesktopProjectActivityReadStateClientV2(ops, config())
    .putActivityReadState(scope(), { expected_authority_revision: 3, entries: [entry] });
  await new Promise((resolve) => setImmediate(resolve));
  await assert.rejects(callback(service), /callback_consumed/u);
  assert.equal(calls, 1);
  resolve();
  await job;
});

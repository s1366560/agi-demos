import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const projection = require(`${ROOT}/src/plugins/desktopSessionProjectionAuthorityModuleV2.js`);
const changes = require(`${ROOT}/src/plugins/desktopSessionRunChangesAuthorityModuleV2.js`);
const config = (mode = 'cloud') => ({
  apiBaseUrl: 'https://api.test',
  deviceAuthorizationBaseUrl: 'https://api.test',
  apiKey: 'test-session',
  localApiToken: mode === 'local' ? 'test-launch' : '',
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
  mode,
  workspaceRoot: '',
});
const conversation = {
  id: 'conversation-1',
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  workspace_id: 'workspace-1',
};
const summary = {
  run_id: 'run-1',
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  conversation_id: 'conversation-1',
  status: 'completed',
  revision: 2,
  summary_state: 'partial',
  reason_code: 'summary_not_recorded',
  started_at: null,
  completed_at: null,
  duration_ms: null,
  input_tokens: null,
  output_tokens: null,
  cost_usd: null,
  model_breakdown: [],
  completion_summary: null,
  artifact_count: null,
  checks_passed: null,
  checks_failed: null,
  files_changed: null,
  lines_added: null,
  lines_deleted: null,
  evidence_references: [],
};
const snapshot = {
  id: 'snapshot-1',
  run_id: 'run-1',
  conversation_id: 'conversation-1',
  run_revision: 7,
  environment_id: null,
  repository_root: null,
  workspace_path: null,
  branch: null,
  base_revision: null,
  head_revision: null,
  status: 'unattributed',
  reason: 'change_attribution_not_recorded',
  additions: 0,
  deletions: 0,
  files_changed: 0,
  truncated: false,
  captured_at: '2026-09-05T00:00:00Z',
  files: [],
  scope: 'run',
  turn_id: null,
  snapshot_revision: 'a'.repeat(64),
  attribution: [],
};
const json = (value, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
});
function fixture(module = projection) {
  let service;
  const events = [];
  const apply =
    module === projection
      ? module.applyDesktopSessionProjectionAuthorityV2
      : module.applyDesktopSessionRunChangesAuthorityV2;
  apply(
    {
      provide(_name, value) {
        service = value;
      },
    },
    { strategy: 'desktop-api-client' },
  );
  const actions = {
    async acquireServiceOperationLease(request) {
      events.push(['acquire', request]);
      return {
        status: 'accepted',
        useService: (use) => use(service),
        async release() {
          events.push('release');
        },
      };
    },
  };
  const ops =
    module === projection
      ? module.createDesktopSessionProjectionOperationsV2(() => actions)
      : module.createDesktopSessionRunChangesOperationsV2(() => actions);
  return { ops, events };
}
const input = (mode = 'cloud') => ({
  config: config(mode),
  conversation,
  runId: 'run-1',
  signal: new AbortController().signal,
});
test('Run Review V2 summary preserves actual partial record under session lease', async () => {
  globalThis.fetch = async () => json(summary);
  const f = fixture();
  assert.deepEqual(await f.ops.getRunSummary(input()), summary);
  assert.equal(f.events[0][1].scope.kind, 'session');
  assert.equal(f.events.at(-1), 'release');
});
test('Run Review V2 Cloud scopes retain exact query and accept older persisted summary revision', async () => {
  for (const scope of ['run', 'turn', 'session']) {
    const calls = [];
    globalThis.fetch = async (url, init) => {
      calls.push(new URL(url));
      assert.equal(init.method, 'GET');
      return json(
        url.includes('/summary')
          ? summary
          : { ...snapshot, scope, turn_id: scope === 'turn' ? 'turn-1' : null },
      );
    };
    const f = fixture(changes);
    const value = await f.ops.getRunChanges({
      ...input(),
      scope,
      turnId: scope === 'turn' ? 'turn-1' : undefined,
      expectedRevision: 7,
    });
    assert.equal(value.scope, scope);
    assert.equal(calls.length, 2);
    assert.equal(calls[0].pathname, '/api/v1/agent/runs/run-1/summary');
    assert.equal(calls[1].searchParams.get('expected_revision'), '7');
    assert.equal(calls[1].searchParams.get('scope'), scope);
    assert.equal(calls[1].searchParams.get('turn_id'), scope === 'turn' ? 'turn-1' : null);
    assert.equal(f.events.filter((e) => Array.isArray(e)).length, 1);
  }
});
test('Run Review V2 summary cross-identity prevents changes transport', async () => {
  for (const extra of [
    { project_id: 'other' },
    { tenant_id: 'other' },
    { conversation_id: 'other' },
    { run_id: 'other' },
  ]) {
    let calls = 0;
    globalThis.fetch = async () => {
      calls++;
      return json({ ...summary, ...extra });
    };
    await assert.rejects(fixture(changes).ops.getRunChanges({ ...input(), expectedRevision: 7 }));
    assert.equal(calls, 1);
  }
});
test('Run Review V2 changes response binds conversation revision and requested turn', async () => {
  for (const extra of [
    { conversation_id: 'other' },
    { run_revision: 8 },
    { scope: 'session' },
    { turn_id: 'other' },
  ]) {
    globalThis.fetch = async (url) =>
      json(
        url.includes('/summary')
          ? summary
          : { ...snapshot, scope: 'turn', turn_id: 'turn-1', ...extra },
      );
    await assert.rejects(
      fixture(changes).ops.getRunChanges({
        ...input(),
        expectedRevision: 7,
        scope: 'turn',
        turnId: 'turn-1',
      }),
    );
  }
});
test('Run Review V2 Local run revision zero preserves actual wire and JSON extensions', async () => {
  const local = { ...snapshot, run_revision: 0, transport_extension: { revision_source: 'local' } };
  delete local.scope;
  delete local.turn_id;
  delete local.snapshot_revision;
  delete local.attribution;
  let calls = 0;
  globalThis.fetch = async (url, init) => {
    calls++;
    assert.equal(new URL(url).search, '?expected_revision=0');
    assert.equal(new Headers(init.headers).get('x-agistack-launch'), 'test-launch');
    return json(local);
  };
  assert.deepEqual(
    await fixture(changes).ops.getRunChanges({ ...input('local'), expectedRevision: 0 }),
    local,
  );
  assert.equal(calls, 1);
});
test('Run Review V2 Local unavailable scopes and summary do not make HTTP calls', async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    throw new Error('unexpected');
  };
  await assert.rejects(fixture().ops.getRunSummary(input('local')), (e) => e.status === 501);
  await assert.rejects(
    fixture(changes).ops.getRunChanges({
      ...input('local'),
      expectedRevision: 0,
      scope: 'session',
    }),
    (e) => e.status === 501,
  );
  assert.equal(calls, 0);
});
test('Run Review V2 rejects missing turn identity and Cloud revision zero before lease', async () => {
  const f = fixture(changes);
  for (const request of [
    { scope: 'turn', expectedRevision: 7 },
    { scope: 'run', expectedRevision: 0 },
    { scope: 'session', turnId: 'unexpected', expectedRevision: 7 },
  ])
    assert.throws(() => f.ops.getRunChanges({ ...input(), ...request }));
  assert.equal(f.events.length, 0);
});
test('Run Review V2 preserves structured backend error and CAS status', async () => {
  const error = {
    detail: { reason_code: 'run_changes_unavailable' },
    expected_revision: 7,
    actual_revision: 8,
  };
  globalThis.fetch = async (url) => (url.includes('/summary') ? json(summary) : json(error, 409));
  await assert.rejects(
    fixture(changes).ops.getRunChanges({ ...input(), expectedRevision: 7 }),
    (value) =>
      value.name === 'DesktopApiError' &&
      value.status === 409 &&
      JSON.stringify(value.payload) === JSON.stringify(error),
  );
});
test('Run Review V2 abort between summary and changes stops second read', async () => {
  const controller = new AbortController();
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    controller.abort();
    return json(summary);
  };
  await assert.rejects(
    fixture(changes).ops.getRunChanges({
      ...input(),
      signal: controller.signal,
      expectedRevision: 7,
    }),
    { name: 'AbortError' },
  );
  assert.equal(calls, 1);
});
test('Run Review V2 delayed lease abort prevents bind and preserves release', async () => {
  let proceed,
    binds = 0,
    releases = 0;
  const wait = new Promise((resolve) => {
    proceed = resolve;
  });
  const ops = projection.createDesktopSessionProjectionOperationsV2(() => ({
    async acquireServiceOperationLease() {
      await wait;
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation() {
              binds++;
              throw new Error('unexpected');
            },
          }),
        async release() {
          releases++;
        },
      };
    },
  }));
  const controller = new AbortController();
  const job = ops.getRunSummary({ ...input(), signal: controller.signal });
  controller.abort();
  proceed();
  await assert.rejects(job, { name: 'AbortError' });
  assert.equal(binds, 0);
  assert.equal(releases, 1);
});
test('Run Review V2 captures summary run and conversation before delayed admission', async () => {
  let proceed, captured;
  const wait = new Promise((resolve) => {
    proceed = resolve;
  });
  const ops = projection.createDesktopSessionProjectionOperationsV2(() => ({
    async acquireServiceOperationLease() {
      await wait;
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation: (config) => ({
              async getRunSummary(identity, runId) {
                captured = { config, identity, runId };
                return summary;
              },
            }),
          }),
        async release() {},
      };
    },
  }));
  const request = { ...input(), conversation: { ...conversation } };
  const job = ops.getRunSummary(request);
  request.runId = 'other';
  request.conversation.id = 'other';
  request.config.projectId = 'other';
  proceed();
  await job;
  assert.equal(captured.runId, 'run-1');
  assert.equal(captured.identity.id, 'conversation-1');
  assert.equal(captured.config.projectId, 'project-1');
});
test('Run Review V2 secondary lease release failure cannot hide primary error', async () => {
  const failure = new Error('primary');
  const ops = projection.createDesktopSessionProjectionOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation: () => ({
              async getRunSummary() {
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
  await assert.rejects(ops.getRunSummary(input()), (e) => e === failure);
});
test('Run Review V2 duplicate lease callback cannot perform second HTTP read', async () => {
  let callback,
    proceed,
    calls = 0;
  const wait = new Promise((resolve) => {
    proceed = resolve;
  });
  const service = {
    bindOperation: () => ({
      async getRunSummary() {
        calls++;
        await wait;
        return summary;
      },
    }),
  };
  const ops = projection.createDesktopSessionProjectionOperationsV2(() => ({
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
  const job = ops.getRunSummary(input());
  await new Promise((resolve) => setImmediate(resolve));
  await assert.rejects(callback(service), /consumed/u);
  assert.equal(calls, 1);
  proceed();
  await job;
});
test('Run Review V2 operation result boundary rejects malformed and crossed custom providers', async () => {
  for (const result of [{}, { ...summary, conversation_id: 'other' }]) {
    const ops = projection.createDesktopSessionProjectionOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return {
          status: 'accepted',
          useService: (use) =>
            use({ bindOperation: () => ({ getRunSummary: async () => result }) }),
          async release() {},
        };
      },
    }));
    await assert.rejects(ops.getRunSummary(input()));
  }
  for (const result of [
    {},
    { ...snapshot, conversation_id: 'other' },
    { ...snapshot, run_revision: 8 },
  ]) {
    const ops = changes.createDesktopSessionRunChangesOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return {
          status: 'accepted',
          useService: (use) =>
            use({ bindOperation: () => ({ getRunChanges: async () => result }) }),
          async release() {},
        };
      },
    }));
    await assert.rejects(ops.getRunChanges({ ...input(), expectedRevision: 7 }));
  }
});
test('Run Review V2 real Loader reuses both modules with disabled generation zero HTTP', async () => {
  const runtime = require('@agistack/plugin-runtime');
  const { acquireDesktopRendererServiceOperationLeaseV2 } = require(
    `${ROOT}/src/plugins/desktopRendererServiceOperationLeaseV2.js`,
  );
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
  assert.equal(profile.entries.length, 436);
  for (const worker of ['skill-evolution-worker', 'channel-outbox-worker', 'cron-scheduler-worker']) {
    const entry = profile.entries.find((item) => item.entry_id === `builtin-rust-server-${worker}`);
    assert.equal(entry?.module_ref, `builtin://memstack/rust-server/${worker}`);
    assert.equal(entry?.parent_entry_id, 'builtin-rust-server-generation-host');
    assert.deepEqual(entry?.config, { autostart: true });
  }
  const loader = new runtime.LoaderV2(
    [...runtime.createDesktopRendererDefinitionsV2(), ...authorities],
    'desktop-renderer',
  );
  const manager = new runtime.GenerationManagerV2();
  const generation = await loader.stage(profile);
  await manager.publish(generation);
  const actions = {
    acquireServiceOperationLease: (request) =>
      acquireDesktopRendererServiceOperationLeaseV2(manager.current, request, (g) =>
        manager.acquire(g),
      ),
  };
  let calls = 0;
  globalThis.fetch = async (url) => {
    calls++;
    return json(url.includes('/summary') ? summary : snapshot);
  };
  await projection.createDesktopSessionProjectionOperationsV2(() => actions).getRunSummary(input());
  await changes
    .createDesktopSessionRunChangesOperationsV2(() => actions)
    .getRunChanges({ ...input(), expectedRevision: 7 });
  assert.equal(calls, 3);
  assert.equal(generation.leaseCount, 0);
  const disabled = structuredClone(profile);
  for (const entry of disabled.entries)
    if (
      [
        'builtin-desktop-session-projection-authority',
        'builtin-desktop-session-run-changes-authority',
      ].includes(entry.entry_id)
    )
      entry.enabled = false;
  const next = await loader.stage(disabled);
  await manager.publish(next);
  calls = 0;
  await assert.rejects(
    projection.createDesktopSessionProjectionOperationsV2(() => actions).getRunSummary(input()),
  );
  await assert.rejects(
    changes
      .createDesktopSessionRunChangesOperationsV2(() => actions)
      .getRunChanges({ ...input(), expectedRevision: 7 }),
  );
  assert.equal(calls, 0);
  assert.equal(next.leaseCount, 0);
  await manager.close();
});
test('Run Review V2 actual native broker validates Cloud summary and requested changes scope', async () => {
  const { executeVaultBoundCloudRequest } = require(`${ROOT}/electron/main/cloudRequestPolicy.js`);
  let fallback = 0,
    summaries = 0;
  globalThis.fetch = async () => {
    fallback++;
    throw new Error('unexpected fallback');
  };
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(_command, args) {
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
            async fetch(url) {
              const path = new URL(url).pathname;
              if (path === '/api/v1/workspace-context')
                return json({
                  context: {
                    tenant_id: 'tenant-1',
                    project_id: 'project-1',
                    workspace_id: 'workspace-1',
                  },
                });
              if (path.endsWith('/summary')) {
                summaries++;
                return json(summary);
              }
              return json({ ...snapshot, scope: 'turn', turn_id: 'turn-1' });
            },
          });
        },
      },
    },
  };
  const value = await fixture(changes).ops.getRunChanges({
    ...input(),
    config: { ...config(), apiKey: '' },
    expectedRevision: 7,
    scope: 'turn',
    turnId: 'turn-1',
  });
  assert.equal(value.turn_id, 'turn-1');
  assert.ok(summaries >= 2);
  assert.equal(fallback, 0);
});

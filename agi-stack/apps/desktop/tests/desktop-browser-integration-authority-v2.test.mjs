import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const m = require(`${ROOT}/src/plugins/desktopBrowserIntegrationAuthorityModuleV2.js`);
const p = require(`${ROOT}/src/plugins/desktopBrowserIntegrationHttpProjectionV2.js`);
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
function fixture(
  runtime = config(),
  authority = p.createDesktopBrowserIntegrationHttpProjectionV2(runtime),
) {
  const events = [];
  const ops = m.createDesktopBrowserIntegrationOperationsV2(() => ({
    async acquireServiceOperationLease(descriptor) {
      events.push(['acquire', descriptor]);
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation: (frozen) => {
              assert.ok(Object.isFrozen(frozen));
              return authority;
            },
          }),
        async release() {
          events.push(['release']);
        },
      };
    },
  }));
  return { client: m.createDesktopBrowserIntegrationClientV2(ops, runtime), ops, events };
}
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
});
const json = (value) =>
  new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });

const grant = {
  id: 'grant-1',
  host: 'example.com',
  decision: 'site',
  source_hitl_request_id: 'hitl-1',
  created_at: '2026-09-05T00:00:00Z',
};
const capability = { ...grant, capability: 'full_cdp' };
const credential = {
  id: 'credential-1',
  origin: 'example.com',
  username: 'user',
  created_at: '2026-09-05T00:00:00Z',
};
const credentialInput = {
  origin: 'example.com',
  username: 'user',
  password: ' test-only-password ',
};
test('Browser Integration V2 eight methods use root lease with blank tenant and project', async () => {
  globalThis.fetch = async () => json({ grants: [grant] });
  const f = fixture({ ...config(), tenantId: '', projectId: '' });
  assert.equal(Object.keys(f.ops).length, 8);
  assert.equal((await f.client.listBrowserOriginGrants())[0].id, 'grant-1');
  assert.deepEqual(f.events[0][1].scope, { kind: 'root' });
  assert.equal(f.events.at(-1)[0], 'release');
});
test('Browser Integration V2 Local eight endpoint bodies preserve password bytes and metadata only', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    calls.push({ url: String(url), init, body: init.body ? JSON.parse(init.body) : null });
    if (path.endsWith('/audit')) return json({ entries: [] });
    if (path.includes('site-credentials'))
      return json(
        init.method === 'GET'
          ? {
              credentials: [
                {
                  ...credential,
                  password: 'test-only-password',
                  credential_ref: 'test-only-vault-ref',
                },
              ],
            }
          : {
              success: true,
              credential: {
                ...credential,
                password: 'test-only-password',
                credential_ref: 'test-only-vault-ref',
              },
            },
      );
    const value = path.includes('capability-grants') ? capability : grant;
    return json(init.method === 'GET' ? { grants: [value] } : { success: true, grant: value });
  };
  const f = fixture();
  await f.client.listBrowserOriginGrants();
  await f.client.revokeBrowserOriginGrant('grant-1');
  await f.client.listBrowserCapabilityGrants();
  await f.client.revokeBrowserCapabilityGrant('grant-1');
  const listed = await f.client.listBrowserSiteCredentials();
  const saved = await f.client.upsertBrowserSiteCredential({
    ...credentialInput,
    username: ' user ',
  });
  await f.client.deleteBrowserSiteCredential('credential-1');
  await f.client.listBrowserAuditEntries({ limit: 501.5, origin: ' example.com ' });
  assert.deepEqual(saved, credential);
  assert.deepEqual(listed, [credential]);
  assert.equal(calls[5].body.password, ' test-only-password ');
  assert.equal(calls[5].body.username, 'user');
  assert.deepEqual(
    calls.map((x) => x.init.method),
    ['GET', 'DELETE', 'GET', 'DELETE', 'GET', 'PUT', 'DELETE', 'GET'],
  );
  assert.ok(calls[7].url.endsWith('/audit?limit=500&origin=example.com'));
  assert.ok(calls.every((x) => x.init.headers.get('X-Agistack-Launch') === 'private-launch'));
  assert.equal(f.events.filter((x) => x[0] === 'release').length, 8);
});
test('Browser Integration V2 preserves snake camel compatibility and real numeric audit protocol', async () => {
  const f = fixture();
  globalThis.fetch = async () =>
    json([
      {
        id: 'grant-1',
        host: 'example.com',
        decision: 'all',
        sourceHitlRequestId: 'hitl',
        createdAt: '2026-09-05T00:00:00Z',
      },
    ]);
  assert.equal((await f.client.listBrowserOriginGrants())[0].source_hitl_request_id, 'hitl');
  const outcomes = ['ok', 'consent', 'error', 'denied', 'consent_required', 'declined'];
  globalThis.fetch = async () =>
    json({
      entries: outcomes.map((outcome, index) => ({
        id: index + 1,
        run_id: null,
        tool_name: 'getSidePanelSession',
        origin: null,
        target_summary: 'session requested',
        outcome,
        latency_ms: 1,
        created_at: 1700000000000,
      })),
    });
  const entries = await f.client.listBrowserAuditEntries();
  assert.deepEqual(
    entries.map((x) => x.outcome),
    outcomes,
  );
  assert.equal(entries[0].id, '1');
  assert.equal(entries[0].created_at, '2023-11-14T22:13:20.000Z');
  assert.equal(entries[0].run_id, '');
  assert.equal(entries[0].origin, '');
  globalThis.fetch = async () =>
    json({
      entries: [
        {
          id: 'audit-1',
          runId: 'run',
          toolName: 'tool',
          origin: 'example.com',
          targetSummary: 'target',
          outcome: 'ok',
          latencyMs: 0,
          createdAt: '2026-09-05T00:00:00Z',
        },
      ],
    });
  assert.equal((await f.client.listBrowserAuditEntries())[0].tool_name, 'tool');
});
test('Browser Integration V2 Cloud unsupported is decided inside admitted authority without HTTP', async () => {
  let fetches = 0;
  globalThis.fetch = async () => {
    fetches++;
    return json({});
  };
  const f = fixture({ ...config('cloud'), tenantId: '', projectId: '' });
  const methods = [
    () => f.client.listBrowserOriginGrants(),
    () => f.client.revokeBrowserOriginGrant('grant-1'),
    () => f.client.listBrowserCapabilityGrants(),
    () => f.client.revokeBrowserCapabilityGrant('grant-1'),
    () => f.client.listBrowserSiteCredentials(),
    () => f.client.upsertBrowserSiteCredential(credentialInput),
    () => f.client.deleteBrowserSiteCredential('credential-1'),
    () => f.client.listBrowserAuditEntries(),
  ];
  for (const method of methods)
    await assert.rejects(
      method(),
      (error) =>
        error instanceof DesktopApiError &&
        error.status === 501 &&
        error.payload.reason_code === 'cloud_browser_integration_unavailable',
    );
  assert.equal(fetches, 0);
  assert.equal(f.events.filter((x) => x[0] === 'acquire').length, 8);
  assert.equal(f.events.filter((x) => x[0] === 'release').length, 8);
});
test('Browser Integration V2 invalid input fails before admission without exposing password', async () => {
  const f = fixture();
  for (const input of [
    { ...credentialInput, password: '' },
    { ...credentialInput, password: '界'.repeat(1366) },
    { ...credentialInput, username: '界'.repeat(85) },
    { ...credentialInput, credential_ref: 'forbidden' },
  ])
    await assert.rejects(
      f.client.upsertBrowserSiteCredential(input),
      (error) =>
        error.status === 422 &&
        error.payload.password === undefined &&
        (!input.password || !JSON.stringify(error).includes(input.password)),
    );
  assert.equal(f.events.length, 0);
  globalThis.fetch = async () => json({ credential });
  await f.client.upsertBrowserSiteCredential({ ...credentialInput, password: '   ' });
  assert.equal(f.events.length, 2);
});
test('Browser Integration V2 response validation enforces mutation identity and excludes raw secrets', async () => {
  const f = fixture();
  globalThis.fetch = async () =>
    json({
      success: true,
      credential: { ...credential, id: 'other', password: 'test-only-password' },
    });
  await assert.rejects(
    f.client.deleteBrowserSiteCredential('credential-1'),
    (error) => error.status === 502 && !JSON.stringify(error).includes('test-only-password'),
  );
  globalThis.fetch = async () => json({ success: false, grant });
  await assert.rejects(f.client.revokeBrowserOriginGrant('grant-1'), /response/u);
  globalThis.fetch = async () =>
    json({ credentials: [{ password: 'test-only-password', credential_ref: 'vault-ref' }] });
  await assert.rejects(
    f.client.listBrowserSiteCredentials(),
    (error) => error.status === 502 && !JSON.stringify(error.payload).includes('vault-ref'),
  );
});
test('Browser Integration V2 errors preserve public Rust reasons and never echo vault or password text', async () => {
  const f = fixture();
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        detail: 'site credential vault is unavailable',
        reason_code: 'browser_site_credential_vault_unavailable',
        password: 'test-only-password',
        credential_ref: 'vault-ref',
      }),
      { status: 500, headers: { 'Content-Type': 'application/json' } },
    );
  await assert.rejects(
    f.client.upsertBrowserSiteCredential(credentialInput),
    (error) =>
      error instanceof DesktopApiError &&
      error.status === 500 &&
      error.payload.reason_code === 'browser_site_credential_vault_unavailable' &&
      !JSON.stringify(error.payload).includes('vault-ref'),
  );
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        detail: 'store error test-only-password vault-ref',
        reason_code: 'vault-ref',
        password: 'test-only-password',
      }),
      { status: 500, headers: { 'Content-Type': 'application/json' } },
    );
  await assert.rejects(
    f.client.upsertBrowserSiteCredential(credentialInput),
    (error) =>
      error.status === 500 &&
      error.message === 'HTTP 500' &&
      !JSON.stringify(error.payload).includes('test-only-password'),
  );
});
test('Browser Integration V2 disabled admission performs no HTTP', async () => {
  let fetches = 0;
  globalThis.fetch = async () => {
    fetches++;
    return json({ grants: [] });
  };
  const ops = m.createDesktopBrowserIntegrationOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return { status: 'rejected', reasonCode: 'missing_service' };
    },
  }));
  await assert.rejects(
    m.createDesktopBrowserIntegrationClientV2(ops, config()).listBrowserOriginGrants(),
    /missing_service/u,
  );
  assert.equal(fetches, 0);
});
test('Browser Integration V2 freezes password before delayed lease and keeps primary failure', async () => {
  let proceed;
  const pending = new Promise((resolve) => {
    proceed = resolve;
  });
  let captured;
  const failure = new DesktopApiError('conflict', 409, {});
  const ops = m.createDesktopBrowserIntegrationOperationsV2(() => ({
    async acquireServiceOperationLease() {
      await pending;
      return {
        status: 'accepted',
        useService: (use) =>
          use({
            bindOperation: () => ({
              async execute(method, input) {
                captured = input;
                throw failure;
              },
            }),
          }),
        async release() {
          throw new Error('secondary release failure');
        },
      };
    },
  }));
  const runtime = config();
  const input = { ...credentialInput };
  const job = ops.upsertBrowserSiteCredential({
    config: runtime,
    scope: { authority: 'local' },
    args: [input],
  });
  input.password = 'changed';
  runtime.apiKey = 'changed';
  proceed();
  await assert.rejects(job, (error) => error === failure);
  assert.equal(captured.args[0].password, ' test-only-password ');
  assert.equal(captured.config.apiKey, 'trusted-session');
});
test('Browser Integration V2 abort during acquire releases and escaped callback cannot rebind', async () => {
  let proceed;
  const pending = new Promise((resolve) => {
    proceed = resolve;
  });
  let callback;
  let binds = 0;
  let releases = 0;
  const service = {
    bindOperation() {
      binds++;
      return {
        async execute() {
          return { grants: [] };
        },
      };
    },
  };
  const ops = m.createDesktopBrowserIntegrationOperationsV2(() => ({
    async acquireServiceOperationLease() {
      await pending;
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
    .createDesktopBrowserIntegrationClientV2(ops, config())
    .listBrowserOriginGrants(controller.signal);
  controller.abort();
  proceed();
  await assert.rejects(job, { name: 'AbortError' });
  assert.equal(binds, 0);
  assert.equal(releases, 1);
  await assert.rejects(callback(service), /released/u);
});
test('Browser Integration V2 abort after HTTP rejects late result and releases', async () => {
  const controller = new AbortController();
  globalThis.fetch = async () => {
    controller.abort();
    return json({ grants: [grant] });
  };
  const f = fixture();
  await assert.rejects(f.client.listBrowserOriginGrants(controller.signal), { name: 'AbortError' });
  assert.equal(f.events.at(-1)[0], 'release');
});
test('Browser Integration V2 real Loader publishes root-resolvable service and disabled next generation removes it', async () => {
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
  const scope = { kind: 'root' };
  try {
    const service = generation.resolve(m.DESKTOP_BROWSER_INTEGRATION_AUTHORITY_SERVICE_V2, scope, {
      version: '1.0.0',
    });
    assert.equal(typeof service.bindOperation(config()).execute, 'function');
    const disabled = structuredClone(profile);
    disabled.entries.find(
      (entry) => entry.entry_id === 'builtin-desktop-browser-integration-authority',
    ).enabled = false;
    const next = await loader.stage(disabled);
    try {
      assert.throws(
        () =>
          next.resolve(m.DESKTOP_BROWSER_INTEGRATION_AUTHORITY_SERVICE_V2, scope, {
            version: '1.0.0',
          }),
        (error) => error.code === 'missing_service',
      );
      assert.equal(typeof service.bindOperation(config()).execute, 'function');
    } finally {
      await next.dispose();
    }
  } finally {
    await generation.dispose();
  }
});

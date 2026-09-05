import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const m = require(`${ROOT}/src/plugins/desktopProjectMcpAppsAuthorityModuleV2.js`);
const p = require(`${ROOT}/src/plugins/desktopProjectMcpAppsHttpProjectionV2.js`);
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
  authority = p.createDesktopProjectMcpAppsHttpProjectionV2(runtime),
) {
  const events = [];
  const ops = m.createDesktopProjectMcpAppsOperationsV2(() => ({
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
  return { client: m.createDesktopProjectMcpAppsClientV2(ops, runtime), ops, events };
}
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
});
const json = (value) =>
  new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });

const app = (extra = {}) => ({
  id: 'app-1',
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  server_name: 'tools',
  tool_name: 'open',
  ...extra,
});
const unavailable = {
  content: [{ type: 'text', text: 'Durable tool idempotency unavailable' }],
  is_error: true,
  error_message: 'cloud_mcp_tool_idempotency_unavailable',
  error_code: -32000,
};
test('MCP Apps V2 six operations reject blank scope and invalid payload before lease', async () => {
  const f = fixture({ ...config('cloud'), tenantId: '', projectId: '' });
  assert.equal(Object.keys(f.ops).length, 6);
  await assert.rejects(f.client.listMCPApps('project-1'), /identifier|scope/u);
  assert.equal(f.events.length, 0);
  const live = fixture();
  await assert.rejects(live.client.callMCPAppTool('app-1', 'open', [], 'key'), /arguments/u);
  assert.equal(live.events.length, 0);
});
test('MCP Apps V2 Local preserves all six endpoint bodies and App visibility failures', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ path, body, init });
    if (init.method === 'GET') return json([app()]);
    if (path.endsWith('/resources/read'))
      return json({
        contents: [
          { uri: body.uri, blob: 'AA==', _meta: { x: true } },
          { uri: 'text://second', text: 'plain' },
        ],
      });
    if (path.endsWith('/resources/list'))
      return json({ resources: [{ uri: 'file://one', name: 'one', _meta: { x: 1 } }] });
    if (path === '/api/v1/mcp/tools/call')
      return json({
        result: { text: 'ok' },
        is_error: false,
        error_message: null,
        execution_time_ms: 0.1,
        duplicate: true,
      });
    return json({
      content: [{ type: 'text', text: 'ok' }],
      is_error: false,
      error_code: null,
      duplicate: true,
    });
  };
  const f = fixture();
  assert.equal((await f.client.listMCPApps('project-1'))[0].id, 'app-1');
  await f.client.callMCPAppTool('app-1', 'open', { value: 1 }, 'app-key');
  assert.equal(
    (await f.client.callMCPToolByServerId('server-1', 'open', {}, 'server-key')).duplicate,
    true,
  );
  await f.client.callMCPAppToolDirect('project-1', 'tools', 'open', {}, 'direct-key');
  const content = await f.client.readMCPAppResource('project-1', 'file://one');
  assert.equal(content.contents[0].blob, 'AA==');
  assert.deepEqual(content.contents[0]._meta, { x: true });
  await f.client.listMCPAppResources('project-1', ' tools ');
  assert.deepEqual(
    calls.map((x) => x.path),
    [
      '/api/v1/mcp/apps',
      '/api/v1/mcp/apps/app-1/tool-call',
      '/api/v1/mcp/tools/call',
      '/api/v1/mcp/apps/proxy/tool-call',
      '/api/v1/mcp/apps/resources/read',
      '/api/v1/mcp/apps/resources/list',
    ],
  );
  assert.equal(calls[1].body.idempotency_key, 'app-key');
  assert.equal(calls[2].body.server_id, 'server-1');
  assert.equal('server_name' in calls[4].body, false);
  assert.equal(calls[5].body.server_name, 'tools');
  assert.ok(calls.every((x) => x.init.headers.get('X-Agistack-Launch') === 'private-launch'));
  assert.deepEqual(f.events[0][1].scope, {
    kind: 'project',
    tenant_id: 'tenant-1',
    project_id: 'project-1',
  });
  assert.equal(f.events.filter((x) => x[0] === 'release').length, 6);
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        detail: 'Tool is not app-visible',
        reason_code: 'local_mcp_tool_not_app_visible',
      }),
      { status: 403, headers: { 'Content-Type': 'application/json' } },
    );
  await assert.rejects(
    f.client.callMCPAppTool('app-1', 'hidden', {}, 'visibility-key'),
    (error) =>
      error instanceof DesktopApiError &&
      error.status === 403 &&
      error.payload.reason_code === 'local_mcp_tool_not_app_visible',
  );
});
test('MCP Apps V2 Cloud preserves 200 error result, 409 detail and every idempotency key', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ path, method: init.method, body });
    if (init.method === 'GET')
      return json(app({ id: path.endsWith('/server-1') ? 'server-1' : 'app-1' }));
    if (path === '/api/v1/mcp/tools/call')
      return new Response(
        JSON.stringify({
          detail: {
            reason_code: 'cloud_mcp_tool_idempotency_unavailable',
            message: 'Durable idempotency unavailable',
            arguments: { secret: 'test-only-secret' },
          },
        }),
        { status: 409, headers: { 'Content-Type': 'application/json' } },
      );
    return json(unavailable);
  };
  const f = fixture(config('cloud'));
  assert.equal((await f.client.callMCPAppTool('app-1', 'open', {}, 'app-key')).error_code, -32000);
  assert.equal(
    (await f.client.callMCPAppToolDirect('project-1', 'tools', 'open', {}, 'direct-key')).is_error,
    true,
  );
  await assert.rejects(
    f.client.callMCPToolByServerId('server-1', 'open', {}, 'generic-key'),
    (error) =>
      error instanceof DesktopApiError &&
      error.status === 409 &&
      error.payload.detail.reason_code === 'cloud_mcp_tool_idempotency_unavailable' &&
      !JSON.stringify(error.payload).includes('test-only-secret'),
  );
  assert.deepEqual(
    calls.filter((x) => x.method === 'POST').map((x) => x.body.idempotency_key),
    ['app-key', 'direct-key', 'generic-key'],
  );
  assert.deepEqual(
    calls.filter((x) => x.method === 'GET').map((x) => x.path),
    ['/api/v1/mcp/apps/app-1', '/api/v1/mcp/server-1'],
  );
});
test('MCP Apps V2 Cloud cross-project App and server targets fail before side effects', async () => {
  let count = 0;
  globalThis.fetch = async () => {
    count++;
    return json(app({ project_id: 'other-project' }));
  };
  const f = fixture(config('cloud'));
  await assert.rejects(f.client.callMCPAppTool('app-1', 'open', {}, 'key'), /response/u);
  await assert.rejects(f.client.callMCPToolByServerId('server-1', 'open', {}, 'key'), /response/u);
  assert.equal(count, 2);
  assert.equal(f.events.filter((x) => x[0] === 'release').length, 2);
});
test('MCP Apps V2 resources preserve open text blob metadata and project aggregation', async () => {
  globalThis.fetch = async () =>
    json({
      resources: [
        { uri: 'a://one', name: 'A' },
        { uri: 'b://two', name: 'B', annotations: { audience: ['user'] } },
      ],
    });
  const f = fixture(config('cloud'));
  assert.equal((await f.client.listMCPAppResources('project-1', 'server-A')).resources.length, 2);
  globalThis.fetch = async () =>
    json({
      contents: [
        { uri: 'a://one', text: 'plain', _meta: { tag: 1 } },
        { uri: 'b://two', mimeType: 'image/png', blob: 'AA==' },
      ],
    });
  const result = await f.client.readMCPAppResource('project-1', 'a://one');
  assert.equal(result.contents.length, 2);
  assert.ok(Object.isFrozen(result.contents[0]._meta));
  globalThis.fetch = async () => json({ contents: [{ uri: 'a://one', blob: 5 }] });
  await assert.rejects(f.client.readMCPAppResource('project-1', 'a://one'), /response/u);
});
test('MCP Apps V2 disabled admission performs no HTTP', async () => {
  let fetches = 0;
  globalThis.fetch = async () => {
    fetches++;
    return json([]);
  };
  const ops = m.createDesktopProjectMcpAppsOperationsV2(() => ({
    async acquireServiceOperationLease() {
      return { status: 'rejected', reasonCode: 'missing_service' };
    },
  }));
  await assert.rejects(
    m.createDesktopProjectMcpAppsClientV2(ops, config()).listMCPApps('project-1'),
    /missing_service/u,
  );
  assert.equal(fetches, 0);
});
test('MCP Apps V2 freezes request before delayed lease and retains primary failure on release', async () => {
  let proceed;
  const pending = new Promise((resolve) => {
    proceed = resolve;
  });
  let captured;
  const failure = new DesktopApiError('conflict', 409, {
    reason_code: 'local_mcp_idempotency_conflict',
  });
  const ops = m.createDesktopProjectMcpAppsOperationsV2(() => ({
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
  const args = { nested: { value: 1 } };
  const job = ops.callMCPAppTool({
    config: runtime,
    scope: { authority: 'local', tenantId: 'tenant-1', projectId: 'project-1' },
    args: ['app-1', 'open', args, 'key'],
  });
  args.nested.value = 2;
  runtime.projectId = 'other';
  proceed();
  await assert.rejects(job, (error) => error === failure);
  assert.equal(captured.args[2].nested.value, 1);
  assert.equal(captured.config.projectId, 'project-1');
});
test('MCP Apps V2 abort during acquire and escaped callback cannot bind generation', async () => {
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
          return [];
        },
      };
    },
  };
  const ops = m.createDesktopProjectMcpAppsOperationsV2(() => ({
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
    .createDesktopProjectMcpAppsClientV2(ops, config())
    .listMCPApps('project-1', controller.signal);
  controller.abort();
  proceed();
  await assert.rejects(job, { name: 'AbortError' });
  assert.equal(binds, 0);
  assert.equal(releases, 1);
  await assert.rejects(callback(service), /released/u);
  assert.equal(binds, 0);
});
test('MCP Apps V2 abort after preflight prevents POST and abort after HTTP rejects result', async () => {
  const controller = new AbortController();
  let count = 0;
  globalThis.fetch = async () => {
    count++;
    controller.abort();
    return json(app());
  };
  const f = fixture(config('cloud'));
  await assert.rejects(f.client.callMCPAppTool('app-1', 'open', {}, 'key', controller.signal), {
    name: 'AbortError',
  });
  assert.equal(count, 1);
  const localController = new AbortController();
  globalThis.fetch = async () => {
    localController.abort();
    return json([]);
  };
  await assert.rejects(fixture().client.listMCPApps('project-1', localController.signal), {
    name: 'AbortError',
  });
});
test('MCP Apps V2 native Cloud broker denial never falls back to renderer fetch', async () => {
  let calls = 0;
  let fetches = 0;
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command) {
          assert.equal(command, 'cloud_request');
          calls++;
          throw new Error('cloud_request_endpoint_not_allowed');
        },
      },
    },
  };
  globalThis.fetch = async () => {
    fetches++;
    throw new Error('unexpected fetch');
  };
  const f = fixture({ ...config('cloud'), apiKey: '' });
  for (const run of [
    () => f.client.listMCPApps('project-1'),
    () => f.client.callMCPAppTool('app-1', 'open', {}, 'key'),
    () => f.client.callMCPToolByServerId('server-1', 'open', {}, 'key'),
    () => f.client.callMCPAppToolDirect('project-1', 'tools', 'open', {}, 'key'),
    () => f.client.readMCPAppResource('project-1', 'file://one'),
    () => f.client.listMCPAppResources('project-1'),
  ])
    await assert.rejects(run(), /endpoint_not_allowed/u);
  assert.equal(calls, 6);
  assert.equal(fetches, 0);
});
test('MCP Apps V2 real Loader publishes project-resolvable service and disabled next generation removes it', async () => {
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
    const service = generation.resolve(m.DESKTOP_PROJECT_MCP_APPS_AUTHORITY_SERVICE_V2, scope, {
      version: '1.0.0',
    });
    assert.equal(typeof service.bindOperation(config()).execute, 'function');
    const disabled = structuredClone(profile);
    disabled.entries.find(
      (entry) => entry.entry_id === 'builtin-desktop-project-mcp-apps-authority',
    ).enabled = false;
    const next = await loader.stage(disabled);
    try {
      assert.throws(
        () =>
          next.resolve(m.DESKTOP_PROJECT_MCP_APPS_AUTHORITY_SERVICE_V2, scope, {
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

test('MCP Apps V2 resource metadata stays typed and preserves top-level values', async () => {
  const f = fixture();
  globalThis.fetch = async () =>
    json({
      _meta: { cursor: 'next' },
      contents: [{ uri: 'file://one', text: 'plain', _meta: { tag: 1 } }],
    });
  assert.deepEqual((await f.client.readMCPAppResource('project-1', 'file://one'))._meta, {
    cursor: 'next',
  });
  globalThis.fetch = async () =>
    json({ _meta: { cursor: 'next' }, resources: [{ uri: 'file://one', _meta: { tag: 1 } }] });
  assert.deepEqual((await f.client.listMCPAppResources('project-1'))._meta, { cursor: 'next' });
  for (const payload of [
    { _meta: [], contents: [] },
    { contents: [{ uri: 'file://one', text: 'x', _meta: null }] },
  ]) {
    globalThis.fetch = async () => json(payload);
    await assert.rejects(f.client.readMCPAppResource('project-1', 'file://one'), /response/u);
  }
  for (const payload of [
    { _meta: 'invalid', resources: [] },
    { resources: [{ uri: 'file://one', _meta: [] }] },
  ]) {
    globalThis.fetch = async () => json(payload);
    await assert.rejects(f.client.listMCPAppResources('project-1'), /response/u);
  }
});

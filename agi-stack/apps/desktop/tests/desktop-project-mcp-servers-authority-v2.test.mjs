import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { afterEach, test } from 'node:test';
const require = createRequire(import.meta.url);
const ROOT = '/tmp/agistack-desktop-test-dist';
const m = require(`${ROOT}/src/plugins/desktopProjectMcpServersAuthorityModuleV2.js`);
const p = require(`${ROOT}/src/plugins/desktopProjectMcpServersHttpProjectionV2.js`);
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
const server = (mode = 'local', extra = {}) => ({
  id: 'server-1',
  tenant_id: 'tenant-1',
  project_id: 'project-1',
  name: 'tools',
  description: null,
  server_type: 'stdio',
  transport_config: {
    command: 'tool-server',
    url: null,
    cwd: null,
    arguments_redacted: true,
    vault_env_names: [],
    vault_header_names: [],
  },
  enabled: true,
  runtime_status: 'stopped',
  runtime_metadata:
    mode === 'local'
      ? { revision: 2, contract_version: 'desktop-local-mcp-v2', reason_code: null }
      : {},
  discovered_tools: [],
  ...extra,
});
const mutation = () => ({
  name: 'tools',
  description: null,
  server_type: 'stdio',
  transport_config: { command: 'tool-server', args: ['--serve'] },
  enabled: true,
  project_id: 'project-1',
  idempotency_key: 'mutation-key',
});
const provision = () => ({
  project_id: 'project-1',
  server_name: 'tools',
  server_type: 'stdio',
  transport_config: { command: 'tool-server', args: ['--serve'] },
  credential_kind: 'env',
  credential_name: 'TOOL_SECRET',
  secret: 'test-only-secret',
  idempotency_key: 'provision-key',
  mutation_idempotency_key: 'mutation-key',
});
function fixture(
  runtime = config(),
  authority = p.createDesktopProjectMcpServersHttpProjectionV2(runtime),
) {
  const events = [];
  const ops = m.createDesktopProjectMcpServersOperationsV2(() => ({
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
  return { client: m.createDesktopProjectMcpServersClientV2(ops, runtime), ops, events };
}
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  delete globalThis.window;
});
const json = (value) =>
  new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });

test('MCP Servers V2 exposes seven operations and rejects blank scope before lease', async () => {
  const f = fixture({ ...config('cloud'), tenantId: '', projectId: '' });
  assert.equal(Object.keys(f.ops).length, 7);
  await assert.rejects(f.client.listMCPServers('project-1'), /scope|identifier/u);
  assert.equal(f.events.length, 0);
});

test('MCP Servers V2 Cloud preflight prevents cross-project writes and preserves missing revision', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), method: init.method });
    return json(server('cloud', { project_id: 'other-project' }));
  };
  const f = fixture(config('cloud'));
  await assert.rejects(f.client.updateMCPServer('server-1', mutation()), /scope/u);
  assert.deepEqual(
    calls.map((c) => c.method),
    ['GET'],
  );
  assert.equal(f.events.at(-1)[0], 'release');
});

test('MCP Servers V2 Local seven operations preserve two-phase vault keys, CAS and replay receipts', async () => {
  const calls = [];
  let provisionCount = 0;
  globalThis.fetch = async (url, init) => {
    const path = new URL(url).pathname;
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ path, init, body });
    if (path.endsWith('/credentials/provision'))
      return json({
        stored: true,
        credential_kind: 'env',
        credential_name: 'TOOL_SECRET',
        duplicate: provisionCount++ > 0,
      });
    if (init.method === 'DELETE')
      return json({ deleted: true, id: 'server-1', revision: 3, duplicate: true });
    if (path.endsWith('/test'))
      return json({
        success: true,
        message: 'MCP handshake succeeded',
        tools_discovered: 1,
        connection_time_ms: 0.5,
        errors: [],
        secret: 'test-only-extra',
      });
    return json(init.method === 'GET' ? [server()] : server());
  };
  const f = fixture();
  const listed = await f.client.listMCPServers('project-1');
  assert.equal(listed[0].runtime_metadata.revision, 2);
  assert.equal('url' in listed[0].transport_config, false);
  assert.equal('cwd' in listed[0].transport_config, false);
  assert.equal(listed[0].transport_config.arguments_redacted, true);
  const first = await f.client.provisionMCPServerCredential(provision());
  const replay = await f.client.provisionMCPServerCredential(provision());
  assert.equal(first.duplicate, false);
  assert.equal(replay.duplicate, true);
  await f.client.createMCPServer({
    ...mutation(),
    transport_config: { ...mutation().transport_config, credential_env_names: ['TOOL_SECRET'] },
  });
  await f.client.updateMCPServer('server-1', { ...mutation(), expected_revision: 2 });
  await f.client.setMCPServerEnabled('server-1', {
    enabled: false,
    project_id: 'project-1',
    expected_revision: 2,
    idempotency_key: 'toggle-key',
  });
  await f.client.deleteMCPServer('server-1', {
    project_id: 'project-1',
    expected_revision: 2,
    idempotency_key: 'delete-key',
  });
  const tested = await f.client.testMCPServer('server-1');
  assert.equal(calls.length, 8);
  assert.equal(f.events.length, 16);
  assert.deepEqual(f.events[0][1], {
    service: m.DESKTOP_PROJECT_MCP_SERVERS_AUTHORITY_SERVICE_V2,
    version: '1.0.0',
    scope: { kind: 'project', tenant_id: 'tenant-1', project_id: 'project-1' },
  });
  assert.deepEqual(calls[1].body, provision());
  assert.deepEqual(calls[2].body, provision());
  assert.equal(calls[3].body.idempotency_key, calls[1].body.mutation_idempotency_key);
  assert.equal('secret' in calls[3].body, false);
  assert.equal(calls[4].body.expected_revision, 2);
  assert.equal(calls[5].body.expected_revision, 2);
  assert.equal(calls[6].body.expected_revision, 2);
  assert.equal('secret' in tested, false);
  assert.equal(calls[0].init.headers.get('X-Agistack-Launch'), 'private-launch');
  assert.equal(calls[0].init.headers.get('Authorization'), 'Bearer trusted-session');
});

test('MCP Servers V2 Cloud GET guards every id action and writes omit optimistic revisions', async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ path: new URL(url).pathname, method: init.method, body });
    if (init.method === 'DELETE') return new Response(null, { status: 204 });
    if (new URL(url).pathname.endsWith('/test'))
      return json({
        success: false,
        message: 'Connection failed',
        tools_discovered: 0,
        connection_time_ms: 0,
        errors: ['Connection failed'],
      });
    return json(server('cloud'));
  };
  const f = fixture(config('cloud'));
  const updated = await f.client.updateMCPServer('server-1', {
    ...mutation(),
    expected_revision: 9,
  });
  await f.client.setMCPServerEnabled('server-1', {
    enabled: false,
    project_id: 'project-1',
    idempotency_key: 'toggle-key',
  });
  await f.client.deleteMCPServer('server-1', {
    project_id: 'project-1',
    expected_revision: 9,
    idempotency_key: 'delete-key',
  });
  const result = await f.client.testMCPServer('server-1');
  assert.deepEqual(
    calls.map((c) => c.method),
    ['GET', 'PUT', 'GET', 'PUT', 'GET', 'DELETE', 'GET', 'POST'],
  );
  assert.equal(
    calls.filter((c) => c.body).every((c) => !('expected_revision' in c.body)),
    true,
  );
  assert.equal('revision' in updated.runtime_metadata, false);
  assert.equal(result.success, false);
  assert.equal(f.events.length, 8);
});

test('MCP Servers V2 rejects invalid Local revisions and scope before lease', async () => {
  const f = fixture();
  for (const expected_revision of [undefined, 0, -1, 1.5, Number.MAX_SAFE_INTEGER + 1])
    await assert.rejects(
      f.client.deleteMCPServer('server-1', {
        project_id: 'project-1',
        expected_revision,
        idempotency_key: 'delete-key',
      }),
      (error) => error instanceof DesktopApiError && error.status === 428,
    );
  await assert.rejects(f.client.listMCPServers('other-project'), /scope/u);
  await assert.rejects(
    f.client.createMCPServer({ ...mutation(), project_id: 'other-project' }),
    /scope/u,
  );
  assert.equal(f.events.length, 0);
  await assert.rejects(
    f.client.createMCPServer({
      ...mutation(),
      transport_config: { command: 'tool-server', env: { TOKEN: 'test-only-extra' } },
    }),
    /transport_fields/u,
  );
  assert.equal(f.events.length, 0);
});

test('MCP Servers V2 Cloud provisioning is unavailable inside the acquired authority without fetch', async () => {
  let fetches = 0;
  globalThis.fetch = async () => {
    fetches++;
    throw new Error('unexpected fetch');
  };
  const f = fixture(config('cloud'));
  await assert.rejects(
    f.client.provisionMCPServerCredential(provision()),
    (error) =>
      error instanceof DesktopApiError &&
      error.status === 501 &&
      error.payload.reason_code === 'cloud_mcp_credential_provision_unavailable',
  );
  assert.equal(fetches, 0);
  assert.deepEqual(
    f.events.map((e) => e[0]),
    ['acquire', 'release'],
  );
});

test('MCP Servers V2 service disabled or missing never binds projection or fetches', async () => {
  let fetches = 0;
  globalThis.fetch = async () => {
    fetches++;
    throw new Error('unexpected fetch');
  };
  const missing = m.createDesktopProjectMcpServersClientV2(
    m.createDesktopProjectMcpServersOperationsV2(() => null),
    config(),
  );
  await assert.rejects(missing.listMCPServers('project-1'), (error) => error.status === 503);
  const disabled = m.createDesktopProjectMcpServersClientV2(
    m.createDesktopProjectMcpServersOperationsV2(() => ({
      async acquireServiceOperationLease() {
        return { status: 'rejected', reasonCode: 'missing_service_provider' };
      },
    })),
    config(),
  );
  await assert.rejects(disabled.listMCPServers('project-1'), /missing_service_provider/u);
  assert.equal(fetches, 0);
});

test('MCP Servers V2 safe summaries discard Cloud env, headers, vault refs and unknown metadata', async () => {
  const raw = server('cloud', {
    transport_config: {
      command: ['tool-server'],
      args: ['--serve'],
      cwd: null,
      url: null,
      env: { KEY: 'test-only-secret' },
      headers: { Authorization: 'test-only-secret' },
      vault_env_refs: { KEY: 'test-only-secret' },
    },
    runtime_metadata: { server_info: { secret: 'test-only-secret' } },
    discovered_tools: [{ name: 'echo', secret: 'test-only-secret' }],
    secret: 'test-only-secret',
  });
  const f = fixture(config('cloud'), {
    async execute() {
      return [raw];
    },
  });
  const [value] = await f.client.listMCPServers('project-1');
  assert.equal(JSON.stringify(value).includes('test-only-secret'), false);
  assert.deepEqual(value.discovered_tools, [{ name: 'echo' }]);
  assert.deepEqual(value.runtime_metadata, {});
  assert.deepEqual(value.transport_config, { command: ['tool-server'], args: ['--serve'] });
  assert.ok(Object.isFrozen(value.transport_config));
});

test('MCP Servers V2 receipt, summary and test contract failures release without echoing input secrets', async () => {
  for (const raw of [
    { stored: true, credential_kind: 'env', credential_name: 'OTHER', duplicate: false },
    {
      stored: true,
      credential_kind: 'env',
      credential_name: 'TOOL_SECRET',
      duplicate: false,
      vault_reference: 'test-only-secret',
    },
  ]) {
    const f = fixture(config(), {
      async execute() {
        return raw;
      },
    });
    await assert.rejects(
      f.client.provisionMCPServerCredential(provision()),
      (error) =>
        error.status === 502 && !JSON.stringify(error.payload).includes('test-only-secret'),
    );
    assert.equal(f.events.at(-1)[0], 'release');
  }
  for (const raw of [
    { deleted: true, id: 'other', revision: 3, duplicate: false },
    { deleted: true, id: 'server-1', revision: 3 },
    { deleted: false, id: 'server-1', revision: 3, duplicate: false },
  ]) {
    const f = fixture(config(), {
      async execute() {
        return raw;
      },
    });
    await assert.rejects(
      f.client.deleteMCPServer('server-1', {
        project_id: 'project-1',
        expected_revision: 2,
        idempotency_key: 'delete-key',
      }),
      /delete_response/u,
    );
  }
  const f = fixture(config(), {
    async execute() {
      return [server('local', { runtime_metadata: {} })];
    },
  });
  await assert.rejects(f.client.listMCPServers('project-1'), /revision_response/u);
  const badTest = fixture(config(), {
    async execute() {
      return {
        success: true,
        message: 'ok',
        tools_discovered: NaN,
        connection_time_ms: 1,
        errors: [],
      };
    },
  });
  await assert.rejects(badTest.client.testMCPServer('server-1'), /test_response/u);
});

test('MCP Servers V2 freezes credential binding before acquisition and keeps primary error over release failure', async () => {
  let proceed;
  let captured;
  const pending = new Promise((resolve) => {
    proceed = resolve;
  });
  const failure = new DesktopApiError('MCP conflict', 409, {
    reason_code: 'local_mcp_idempotency_conflict',
  });
  const ops = m.createDesktopProjectMcpServersOperationsV2(() => ({
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
          throw new Error('release failed');
        },
      };
    },
  }));
  const input = provision();
  const runtime = config();
  const job = ops.provisionMCPServerCredential({
    config: runtime,
    scope: { authority: 'local', tenantId: 'tenant-1', projectId: 'project-1' },
    args: [input],
  });
  input.secret = 'changed';
  input.mutation_idempotency_key = 'changed';
  input.transport_config.args.push('changed');
  runtime.projectId = 'changed';
  proceed();
  await assert.rejects(job, (error) => error === failure);
  assert.equal(captured.args[0].secret, 'test-only-secret');
  assert.equal(captured.args[0].mutation_idempotency_key, 'mutation-key');
  assert.deepEqual(captured.args[0].transport_config.args, ['--serve']);
  assert.equal(captured.config.projectId, 'project-1');
});

test('MCP Servers V2 abort during acquire releases without bind, and escaped callback cannot rebind', async () => {
  const controller = new AbortController();
  let proceed;
  let callback;
  let binds = 0;
  let releases = 0;
  const pending = new Promise((resolve) => {
    proceed = resolve;
  });
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
  const ops = m.createDesktopProjectMcpServersOperationsV2(() => ({
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
  const client = m.createDesktopProjectMcpServersClientV2(ops, config());
  const job = client.listMCPServers('project-1', controller.signal);
  controller.abort();
  proceed();
  await assert.rejects(job, { name: 'AbortError' });
  assert.equal(binds, 0);
  assert.equal(releases, 1);
  await assert.rejects(callback(service), /released/u);
  assert.equal(binds, 0);
});

test('MCP Servers V2 abort after Cloud preflight prevents write and HTTP conflict preserves detail safely', async () => {
  const controller = new AbortController();
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    controller.abort();
    return json(server('cloud'));
  };
  const f = fixture(config('cloud'));
  await assert.rejects(f.client.testMCPServer('server-1', controller.signal), {
    name: 'AbortError',
  });
  assert.equal(calls, 1);
  assert.equal(f.events.at(-1)[0], 'release');
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        detail: 'MCP server revision conflict',
        reason_code: 'local_mcp_revision_conflict',
        code: 'local_mcp_revision_conflict',
        secret: 'test-only-secret',
        transport_config: { env: { KEY: 'test-only-secret' } },
      }),
      { status: 409, headers: { 'Content-Type': 'application/json' } },
    );
  const local = fixture();
  await assert.rejects(
    local.client.updateMCPServer('server-1', { ...mutation(), expected_revision: 2 }),
    (error) =>
      error instanceof DesktopApiError &&
      error.status === 409 &&
      error.message === 'MCP server revision conflict' &&
      error.payload.reason_code === 'local_mcp_revision_conflict' &&
      !JSON.stringify(error.payload).includes('test-only-secret'),
  );
});

test('MCP Servers V2 native Cloud broker denial never falls back to renderer fetch', async () => {
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
    throw new Error('unexpected direct fetch');
  };
  const f = fixture({ ...config('cloud'), apiKey: '' });
  await assert.rejects(f.client.listMCPServers('project-1'), /endpoint_not_allowed/u);
  assert.equal(calls, 1);
  assert.equal(fetches, 0);
  assert.equal(f.events.at(-1)[0], 'release');
});

test('MCP Servers V2 real Loader publishes project-resolvable service and disabled next generation removes it', async () => {
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
    const service = generation.resolve(m.DESKTOP_PROJECT_MCP_SERVERS_AUTHORITY_SERVICE_V2, scope, {
      version: '1.0.0',
    });
    assert.equal(typeof service.bindOperation(config()).execute, 'function');
    const disabled = structuredClone(profile);
    disabled.entries.find(
      (entry) => entry.entry_id === 'builtin-desktop-project-mcp-servers-authority',
    ).enabled = false;
    const next = await loader.stage(disabled);
    try {
      assert.throws(
        () =>
          next.resolve(m.DESKTOP_PROJECT_MCP_SERVERS_AUTHORITY_SERVICE_V2, scope, {
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

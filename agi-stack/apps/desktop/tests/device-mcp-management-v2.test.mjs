import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const dist = process.env.DEVICE_MCP_TEST_DIST ?? '/tmp/agistack-desktop-test-dist';
const { createDeviceMcpClientV2 } = require(`${dist}/src/api/deviceMcpClientV2.js`);
const { requireDeviceMcpRequestV2 } = require(`${dist}/src/api/deviceMcpContractV2.js`);
const { executeDeviceMcpManagementV2 } = require(
  `${dist}/electron/main/deviceMcpManagementPolicy.js`,
);
const { mcpManagementOwnerKey } = require(
  `${dist}/src/features/settings/mcpManagementLocationModel.js`,
);
const config = {
  mode: 'cloud',
  apiBaseUrl: 'https://cloud.example/api/v1',
  deviceAuthorizationBaseUrl: '',
  apiKey: '',
  localApiToken: '',
  tenantId: 'tenant-a',
  projectId: 'project-a',
  workspaceId: '',
  workspaceRoot: '',
};
const summary = {
  id: 'server-a',
  tenant_id: 'tenant-a',
  project_id: 'project-a',
  name: 'Device tools',
  server_type: 'stdio',
  enabled: false,
  runtime_status: 'stopped',
  runtime_metadata: { revision: 1 },
};
const create = {
  project_id: 'project-a',
  name: 'Device tools',
  server_type: 'stdio',
  transport_config: { command: 'node', args: ['/tmp/tool.mjs'] },
  enabled: false,
  idempotency_key: 'create-a',
};
const envelope = (result, token = 'context-a') => ({
  context: { tenant_id: 'tenant-a', project_id: 'project-a', location: 'device', token },
  result,
});
const request = (operation, context_token = 'context-a') => ({
  input: {
    tenant_id: 'tenant-a',
    project_id: 'project-a',
    ...(operation.action === 'list' ? {} : { context_token }),
    operation,
  },
});

test('device mutations require a list-issued context, preserve cloud configuration and never send credentials', async () => {
  const calls = [];
  const client = createDeviceMcpClientV2(
    config,
    () => true,
    async (command, args) => {
      calls.push({ command, args });
      return envelope(args.input.operation.action === 'list' ? [summary] : summary);
    },
  );
  await assert.rejects(client.createMCPServer(create), /device_mcp_context_required/);
  assert.equal(calls.length, 0);
  assert.deepEqual(await client.listMCPServers('project-a'), [summary]);
  await client.createMCPServer(create);
  assert.equal(calls[1].command, 'device_mcp_manage_v2');
  assert.deepEqual(calls[1].args, request({ action: 'create', body: create }));
  assert.equal(config.mode, 'cloud');
  assert.deepEqual(Object.keys(calls[1].args.input).sort(), [
    'context_token',
    'operation',
    'project_id',
    'tenant_id',
  ]);
  await assert.rejects(
    client.createMCPServer({ ...create, enabled: true }),
    /device_mcp_request_invalid/,
  );
  assert.equal(calls.length, 2);
});

test('device update, toggle, credential provisioning, test and delete retain item and revision scope', async () => {
  const seen = [];
  const client = createDeviceMcpClientV2(
    config,
    () => true,
    async (_, args) => {
      const operation = args.input.operation;
      seen.push(operation);
      switch (operation.action) {
        case 'list':
          return envelope([summary]);
        case 'delete':
          return envelope({ deleted: true, id: 'server-a', revision: 2, duplicate: false });
        case 'provision_credential':
          return envelope({
            stored: true,
            credential_kind: 'env',
            credential_name: 'TOKEN',
            duplicate: false,
          });
        case 'test':
          return envelope({
            success: true,
            message: 'Connected',
            tools_discovered: 1,
            connection_time_ms: 2,
            errors: [],
          });
        default:
          return envelope(summary);
      }
    },
  );
  await client.listMCPServers('project-a');
  await client.updateMCPServer('server-a', {
    project_id: 'project-a',
    name: 'Device tools',
    expected_revision: 1,
    idempotency_key: 'edit',
  });
  await client.setMCPServerEnabled('server-a', {
    project_id: 'project-a',
    enabled: true,
    expected_revision: 1,
    idempotency_key: 'toggle',
  });
  await client.provisionMCPServerCredential({
    project_id: 'project-a',
    server_name: 'Device tools',
    server_type: 'stdio',
    transport_config: create.transport_config,
    credential_kind: 'env',
    credential_name: 'TOKEN',
    secret: 'test-only-value',
    idempotency_key: 'secret',
    mutation_idempotency_key: 'edit',
  });
  await client.testMCPServer('server-a');
  assert.equal(
    await client.deleteMCPServer('server-a', {
      project_id: 'project-a',
      expected_revision: 1,
      idempotency_key: 'remove',
    }),
    undefined,
  );
  assert.equal(seen[2].body.expected_revision, 1);
  assert.deepEqual(seen[4], { action: 'test', server_id: 'server-a' });
  await assert.rejects(
    client.setMCPServerEnabled('server-a', {
      project_id: 'project-a',
      enabled: true,
      idempotency_key: 'missing-revision',
    }),
    /device_mcp_request_invalid/,
  );
});

test('owner changes before or during a call fail closed without automatic mutation retry', async () => {
  let current = true;
  let resolve;
  let calls = 0;
  const client = createDeviceMcpClientV2(
    config,
    () => current,
    async () => {
      calls += 1;
      if (calls === 1) return envelope([summary]);
      return new Promise((done) => {
        resolve = done;
      });
    },
  );
  await client.listMCPServers('project-a');
  const pending = client.createMCPServer(create);
  current = false;
  resolve(envelope(summary));
  await assert.rejects(pending, /device_mcp_context_changed/);
  await assert.rejects(client.createMCPServer(create), /device_mcp_context_changed/);
  assert.equal(calls, 2);
});

test('stale list, changed token and wrong workspace responses cannot grant mutation authority', async () => {
  const resolvers = [];
  const client = createDeviceMcpClientV2(
    config,
    () => true,
    () => new Promise((resolve) => resolvers.push(resolve)),
  );
  const older = client.listMCPServers('project-a');
  const latest = client.listMCPServers('project-a');
  resolvers[1](envelope([summary], 'latest'));
  await latest;
  resolvers[0](envelope([summary], 'older'));
  await assert.rejects(older, /device_mcp_context_changed/);
  const mutation = client.createMCPServer(create);
  resolvers[2](envelope(summary, 'changed'));
  await assert.rejects(mutation, /device_mcp_context_changed/);
  await assert.rejects(client.createMCPServer(create), /device_mcp_context_required/);
  const other = createDeviceMcpClientV2(
    config,
    () => true,
    async () => ({ ...envelope([]), context: { ...envelope([]).context, project_id: 'other' } }),
  );
  await assert.rejects(other.listMCPServers('project-a'), /device_mcp_response_scope_invalid/);
  await assert.rejects(other.createMCPServer(create), /device_mcp_context_required/);
});

test('preload and main contract reject caller authority, raw transport secrets and malformed revisions', () => {
  const good = request({ action: 'create', body: create });
  assert.equal(requireDeviceMcpRequestV2(good), good);
  for (const key of ['user_id', 'api_base_url', 'credential', 'mode', 'workspace_revision']) {
    assert.throws(
      () => requireDeviceMcpRequestV2({ input: { ...good.input, [key]: 'untrusted' } }),
      /device_mcp_request_invalid/,
    );
  }
  for (const key of ['env', 'headers', 'vault_env', 'vault_header_refs']) {
    assert.throws(
      () =>
        requireDeviceMcpRequestV2(
          request({
            action: 'create',
            body: {
              ...create,
              transport_config: { ...create.transport_config, [key]: { TOKEN: 'untrusted' } },
            },
          }),
        ),
      /device_mcp_request_invalid/,
    );
  }
  assert.throws(
    () => requireDeviceMcpRequestV2(request({ action: 'get', server_id: 'server-a' }, '')),
    /device_mcp_request_invalid/,
  );
  assert.throws(
    () =>
      requireDeviceMcpRequestV2(
        request({
          action: 'delete',
          server_id: 'server-a',
          body: { project_id: 'other', expected_revision: 1, idempotency_key: 'remove' },
        }),
      ),
    /device_mcp_request_invalid/,
  );
});

test('main authorizes the owner before invoking and before delivering the result', async () => {
  let calls = 0;
  const args = request({ action: 'list' });
  await assert.rejects(
    executeDeviceMcpManagementV2(
      args,
      () => {
        throw new Error('unauthorized');
      },
      async () => {
        calls += 1;
      },
    ),
    /unauthorized/,
  );
  assert.equal(calls, 0);
  let owner = 1;
  await assert.rejects(
    executeDeviceMcpManagementV2(
      args,
      () => owner,
      async () => {
        owner = 2;
        return envelope([]);
      },
    ),
    /device_mcp_owner_changed/,
  );
  assert.deepEqual(
    await executeDeviceMcpManagementV2(
      args,
      () => 1,
      async () => envelope([]),
    ),
    envelope([]),
  );
});

test('settings owner invalidation covers user, session, origin, workspace and context revision', () => {
  const auth = {
    status: 'authenticated',
    user: { user_id: 'user-a' },
    session: { session_id: 'session-a' },
    context: { tenant_id: 'tenant-a', project_id: 'project-a', revision: 1 },
  };
  const initial = mcpManagementOwnerKey(config, auth);
  for (const next of [
    { ...auth, user: { user_id: 'user-b' } },
    { ...auth, session: { session_id: 'session-b' } },
    { ...auth, context: { ...auth.context, revision: 2 } },
    { ...auth, status: 'anonymous' },
  ])
    assert.notEqual(mcpManagementOwnerKey(config, next), initial);
  for (const next of [
    { ...config, apiBaseUrl: 'https://other.example' },
    { ...config, workspaceId: 'other' },
  ])
    assert.notEqual(mcpManagementOwnerKey(next, auth), initial);
});

function managementHarness(location, runtimeMode = 'cloud') {
  const ts = require('typescript');
  const source = readFileSync(
    new URL('../src/features/settings/useMCPServerManagement.ts', import.meta.url),
    'utf8',
  );
  const code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS },
  }).outputText;
  const states = [],
    refs = [],
    writes = [];
  let stateIndex = 0,
    refIndex = 0;
  const react = {
    useState: (initial) => {
      const index = stateIndex++;
      if (!(index in states)) states[index] = initial;
      return [
        states[index],
        (value) => {
          states[index] = value;
        },
      ];
    },
    useRef: (initial) => {
      const index = refIndex++;
      return (refs[index] ??= { current: initial });
    },
    useCallback: (fn) => fn,
    useEffect: () => {},
  };
  const module = { exports: {} };
  new Function('require', 'module', 'exports', code)(
    (name) => {
      if (name === 'react') return react;
      if (name.startsWith('./'))
        return require(`${dist}/src/features/settings/${name.slice(2)}.js`);
      throw new Error(`Unexpected hook import ${name}`);
    },
    module,
    module.exports,
  );
  const client = {
    listMCPServers: async () => [summary],
    createMCPServer: async (body) => {
      writes.push(['create', body]);
      return summary;
    },
    setMCPServerEnabled: async (id, body) => {
      writes.push(['toggle', id, body]);
      return summary;
    },
  };
  return {
    writes,
    render: () => {
      stateIndex = 0;
      refIndex = 0;
      return module.exports.useMCPServerManagement({
        client,
        active: true,
        config: { ...config, mode: runtimeMode },
        contextKey: 'context-a',
        canManage: true,
        location,
      });
    },
  };
}

test('device settings create disabled and toggle with revision while existing cloud creation stays enabled', async () => {
  for (const [location, enabled] of [
    ['device', false],
    ['project', true],
  ]) {
    const h = managementHarness(location);
    h.render().openCreate();
    await h
      .render()
      .create({
        name: 'Device tools',
        serverType: 'stdio',
        transport: create.transport_config,
        credential: null,
      });
    assert.equal(h.writes[0][0], 'create');
    assert.equal(h.writes[0][1].enabled, enabled);
    await h.render().toggleServer(summary);
    assert.equal(h.writes[1][2].enabled, true);
    assert.equal(h.writes[1][2].expected_revision, location === 'device' ? 1 : undefined);
    assert.equal(h.render().oauthClient, null);
  }
  const local = managementHarness('project', 'local');
  assert.notEqual(local.render().oauthClient, null);
});

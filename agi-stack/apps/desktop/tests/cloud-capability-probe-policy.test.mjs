import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';
const require = createRequire(import.meta.url);
const {
  executeVaultBoundCloudRequest,
} = require('/tmp/agistack-desktop-test-dist/electron/main/cloudRequestPolicy.js');
const cases = [
  { path: '/api/v1/agent/trace/runs/project/project-1?limit=8', method: 'GET' },
  { path: '/api/v1/agent/trace/runs/project/project-1?limit=100', method: 'GET' },
  { path: '/api/v1/agent/trace/runs/project/project-1/active/count', method: 'GET' },
  {
    path: '/api/v1/agent/workflows/patterns/project/project-1?page=1&page_size=100',
    method: 'GET',
  },
  {
    path: '/api/v1/agent/definitions?include_total=true&limit=50&offset=0&tenant_id=tenant-1&project_id=project-1',
    method: 'GET',
  },
  { path: '/api/v1/mcp/apps/resources/list', method: 'POST', body: { project_id: 'project-1' } },
];
function dependencies(projectId = 'project-1', tenantId = 'tenant-1') {
  const calls = [];
  return {
    calls,
    loadTrustedSession: async () => ({
      version: 1,
      api_base_url: 'https://cloud.test',
      runtime_mode: 'cloud',
      credential_kind: 'cloud_bearer',
      credential: 'test-only',
      expires_at: '2099-09-14T00:00:00Z',
    }),
    async fetch(url) {
      const path = new URL(url).pathname;
      calls.push(path);
      return new Response(
        JSON.stringify(
          path === '/api/v1/workspace-context'
            ? { context: { tenant_id: tenantId, project_id: projectId, revision: 1 } }
            : { items: [] },
        ),
        { headers: { 'content-type': 'application/json' } },
      );
    },
  };
}
for (const request of cases) {
  test(`exact capability probe reaches scope-checked cloud transport: ${request.path}`, async () => {
    const deps = dependencies();
    assert.equal((await executeVaultBoundCloudRequest(request, deps)).status, 200);
    assert.deepEqual(deps.calls, [
      '/api/v1/workspace-context',
      new URL(request.path, 'https://cloud.test').pathname,
    ]);
    const foreign = dependencies('project-other');
    await assert.rejects(executeVaultBoundCloudRequest(request, foreign), /project scope mismatch/);
    assert.deepEqual(foreign.calls, ['/api/v1/workspace-context']);
    for (const invalid of [
      {
        ...request,
        path: request.path + (request.path.includes('?') ? '&' : '?') + 'include_secrets=true',
      },
      { ...request, method: 'DELETE' },
      { ...request, mutation: { expected_revision: 1, idempotency_key: 'not-a-mutation' } },
      { ...request, body: { ...request.body, unknown: true } },
    ]) {
      const denied = {
        loadTrustedSession: async () => {
          throw Error('must reject before vault');
        },
        fetch: async () => {
          throw Error('must not fetch');
        },
      };
      await assert.rejects(
        executeVaultBoundCloudRequest(invalid, denied),
        /endpoint is not allowed|mutation is invalid|body is not allowed/,
      );
    }
  });
}
test('MCP resource discovery accepts only optional server name without resource reads', async () => {
  assert.equal(
    (
      await executeVaultBoundCloudRequest(
        { ...cases[5], body: { project_id: 'project-1', server_name: 'server-one' } },
        dependencies(),
      )
    ).status,
    200,
  );
  for (const body of [
    { project_id: 'project-1', server_name: 4 },
    { project_id: '' },
    { project_id: 'project-1', uri: 'file:///secret' },
  ])
    await assert.rejects(
      executeVaultBoundCloudRequest({ ...cases[5], body }, dependencies()),
      /endpoint is not allowed/,
    );
});

test('actual project capability projections generate only admitted probe requests', async () => {
  const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');
  const config = {
    ...DEFAULT_CONFIG,
    mode: 'cloud',
    apiBaseUrl: 'https://cloud.test',
    apiKey: '',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
  const scope = { authority: 'cloud', tenantId: 'tenant-1', projectId: 'project-1' };
  const original = globalThis.window;
  const requests = [];
  const deps = dependencies();
  const transport = deps.fetch;
  deps.fetch = async (url) =>
    new URL(url).pathname === '/api/v1/workspace-context'
      ? new Response(
          JSON.stringify({
            context: { tenant_id: 'tenant-1', project_id: 'project-1', revision: 1 },
            membership_role: 'owner',
          }),
          { headers: { 'content-type': 'application/json' } },
        )
      : transport(url);
  globalThis.window = {
    __MEMSTACK_DESKTOP__: {
      core: {
        async invoke(command, input) {
          assert.equal(command, 'cloud_request');
          requests.push(input.request);
          return executeVaultBoundCloudRequest(input.request, deps);
        },
      },
    },
  };
  try {
    for (const name of [
      'ProjectAgentDashboard',
      'ProjectAgentLogs',
      'ProjectAgentPatterns',
      'ProjectTeam',
    ]) {
      const module = require(
        `/tmp/agistack-desktop-test-dist/src/plugins/desktop${name}HttpProjectionV2.js`,
      );
      const authority = module[`createDesktop${name}HttpAuthorityV2`](config, scope);
      // Empty transport fixtures may fail response decoding, but must reach the intended backend.
      await authority.load().catch((error) => {
        assert.doesNotMatch(error.message, /endpoint is not allowed/);
      });
    }
    const {
      createDesktopProjectMcpAppsHttpProjectionV2,
    } = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopProjectMcpAppsHttpProjectionV2.js');
    await createDesktopProjectMcpAppsHttpProjectionV2(config).execute('listMCPAppResources', {
      config,
      scope,
      args: ['project-1', null],
    });
    for (const expected of cases)
      assert.ok(
        requests.some((actual) => actual.path === expected.path),
        expected.path,
      );
  } finally {
    globalThis.window = original;
  }
});

test('tenant SubAgent catalog does not claim or transmit unsupported project filtering', async () => {
  const { DEFAULT_CONFIG } = require('/tmp/agistack-desktop-test-dist/src/types.js');
  const {
    createDesktopTenantSubAgentDefinitionsClientV2,
  } = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopTenantSubAgentDefinitionsAuthorityModuleV2.js');
  const {
    prepareDesktopTenantSubAgentDefinitionsLoadV2,
  } = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopTenantSubAgentDefinitionsOperationContractV2.js');
  const {
    createDesktopTenantSubAgentDefinitionsHttpProjectionV2,
  } = require('/tmp/agistack-desktop-test-dist/src/plugins/desktopTenantSubAgentDefinitionsHttpProjectionV2.js');
  const config = {
    ...DEFAULT_CONFIG,
    mode: 'cloud',
    apiBaseUrl: 'https://cloud.test',
    apiKey: 'fixture',
    tenantId: 'tenant-1',
    projectId: 'project-1',
  };
  const original = globalThis.fetch;
  const paths = [];
  let observed;
  globalThis.fetch = async (input) => {
    paths.push(new URL(input));
    return new Response(JSON.stringify({ subagents: [], total: 0 }), {
      headers: { 'content-type': 'application/json' },
    });
  };
  try {
    const client = createDesktopTenantSubAgentDefinitionsClientV2(
      {
        async loadTenantSubAgentDefinitions(input) {
          observed = prepareDesktopTenantSubAgentDefinitionsLoadV2(input);
          return createDesktopTenantSubAgentDefinitionsHttpProjectionV2(config).load(
            observed.scope,
          );
        },
      },
      config,
    );
    assert.deepEqual(await client.listManagedSubAgents(), []);
    assert.equal(observed.scope.projectId, null);
    assert.equal(paths[0].searchParams.get('tenant_id'), 'tenant-1');
    assert.equal(paths[0].searchParams.has('project_id'), false);
    assert.throws(() =>
      prepareDesktopTenantSubAgentDefinitionsLoadV2({
        ...observed,
        scope: { ...observed.scope, projectId: 'project-1' },
      }),
    );
  } finally {
    globalThis.fetch = original;
  }
});

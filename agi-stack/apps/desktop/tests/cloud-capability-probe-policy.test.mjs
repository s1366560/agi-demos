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
  test(`legacy capability probe is not a full-desktop bypass: ${request.path}`, async () => {
    const deps = dependencies();
    await assert.rejects(
      executeVaultBoundCloudRequest(request, deps),
      /cloud request endpoint is not allowed|cloud request memory endpoint is not allowed/,
    );
    assert.deepEqual(deps.calls, []);
    const foreign = dependencies('project-other');
    await assert.rejects(
      executeVaultBoundCloudRequest(request, foreign),
      /cloud request endpoint is not allowed|cloud request memory endpoint is not allowed/,
    );
    assert.deepEqual(foreign.calls, []);
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
test('MCP resource discovery is not admitted as legacy business HTTP', async () => {
  await assert.rejects(
    executeVaultBoundCloudRequest(
      { ...cases[5], body: { project_id: 'project-1', server_name: 'server-one' } },
      dependencies(),
    ),
    /cloud request endpoint is not allowed/,
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


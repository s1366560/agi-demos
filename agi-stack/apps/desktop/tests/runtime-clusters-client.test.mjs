import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  createRuntimeClustersClient,
  RuntimeClustersUnavailableError,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/runtime-clusters/runtimeClustersClient.js'
);

function runtimeConfig(mode, overrides = {}) {
  return {
    mode,
    apiBaseUrl: 'https://api.example.test',
    deviceAuthorizationBaseUrl: 'https://api.example.test',
    apiKey: 'cloud-token',
    localApiToken: 'local-token',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

function response(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

test('Cloud Runtime Clusters projects only safe list and health fields', async () => {
  const calls = [];
  const client = createRuntimeClustersClient(runtimeConfig('cloud'), {
    fetch: async (input, init) => {
      calls.push({ url: String(input), init });
      if (String(input).endsWith('/health')) {
        return response({
          status: 'healthy',
          node_count: 3,
          cpu_usage: 20.5,
          memory_usage: 40.25,
          checked_at: '2026-08-02T00:00:00Z',
          registration_token: 'must-not-cross-renderer',
        });
      }
      return response({
        clusters: [
          {
            id: 'cluster-1',
            name: 'Primary',
            tenant_id: 'tenant-1',
            compute_provider: 'kubernetes',
            proxy_endpoint: 'https://cluster.example.test',
            provider_config: { kubeconfig: 'must-not-cross-renderer' },
            credentials_encrypted: 'must-not-cross-renderer',
            status: 'active',
            health_status: 'healthy',
            last_health_check: '2026-08-02T00:00:00Z',
            created_by: 'user-1',
            created_at: '2026-08-01T00:00:00Z',
            updated_at: null,
          },
        ],
        total: 1,
        page: 2,
        page_size: 20,
      });
    },
  });
  const scope = { authority: 'cloud', tenantId: 'tenant-1' };
  const page = await client.list(scope, { page: 2, pageSize: 20 });
  assert.deepEqual(page.clusters[0], {
    id: 'cluster-1',
    name: 'Primary',
    computeProvider: 'kubernetes',
    proxyEndpoint: 'https://cluster.example.test',
    status: 'active',
    healthStatus: 'healthy',
    lastHealthCheck: '2026-08-02T00:00:00Z',
    createdAt: '2026-08-01T00:00:00Z',
    updatedAt: null,
  });
  assert.equal(JSON.stringify(page).includes('credentials_encrypted'), false);
  assert.equal(JSON.stringify(page).includes('kubeconfig'), false);
  assert.match(calls[0].url, /clusters\/\?page=2&page_size=20$/u);
  assert.equal(calls[0].init.headers.get('Authorization'), 'Bearer cloud-token');

  const health = await client.getHealth(scope, 'cluster-1');
  assert.deepEqual(health, {
    status: 'healthy',
    nodeCount: 3,
    cpuUsage: 20.5,
    memoryUsage: 40.25,
    checkedAt: '2026-08-02T00:00:00Z',
  });
  assert.equal(JSON.stringify(health).includes('registration_token'), false);
});

test('Local Runtime Clusters returns a stable unavailable reason without network access', async () => {
  let fetchCalls = 0;
  const client = createRuntimeClustersClient(runtimeConfig('local'), {
    fetch: async () => {
      fetchCalls += 1;
      return response({});
    },
  });
  await assert.rejects(
    () => client.list({ authority: 'local', tenantId: 'tenant-1' }),
    (error) =>
      error instanceof RuntimeClustersUnavailableError &&
      error.reasonCode === 'cloud_cluster_control_not_applicable',
  );
  assert.equal(fetchCalls, 0);
});

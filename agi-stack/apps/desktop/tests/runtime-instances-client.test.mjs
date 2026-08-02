import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  createRuntimeInstancesClient,
  RuntimeInstancesUnavailableError,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/runtime-instances/runtimeInstancesClient.js'
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

test('Cloud Runtime Instances projects only safe list fields and binds query plus mutations', async () => {
  const calls = [];
  const client = createRuntimeInstancesClient(runtimeConfig('cloud'), {
    fetch: async (input, init) => {
      calls.push({ url: String(input), init });
      if (init?.method === 'POST') return response({ status: 'restarting' });
      if (init?.method === 'DELETE') return response({ status: 'deleted' });
      return response({
        instances: [
          {
            id: 'instance-1',
            name: 'Primary',
            status: 'running',
            health_status: 'healthy',
            image_version: '2026.08',
            replicas: 2,
            available_replicas: 1,
            cluster_id: 'cluster-1',
            created_at: '2026-08-02T00:00:00Z',
            updated_at: null,
            proxy_token: 'must-not-cross-renderer',
            env_vars: { API_KEY: 'must-not-cross-renderer' },
            advanced_config: { endpoint: 'https://private.example' },
          },
        ],
        total: 1,
        page: 2,
        page_size: 20,
      });
    },
  });
  const scope = { authority: 'cloud', tenantId: 'tenant-1' };
  const page = await client.list(scope, {
    page: 2,
    pageSize: 20,
    search: 'Primary',
    status: 'running',
  });
  assert.deepEqual(page.instances[0], {
    id: 'instance-1',
    name: 'Primary',
    status: 'running',
    healthStatus: 'healthy',
    imageVersion: '2026.08',
    replicas: 2,
    availableReplicas: 1,
    clusterId: 'cluster-1',
    createdAt: '2026-08-02T00:00:00Z',
    updatedAt: null,
    projection: 'cloud',
  });
  assert.equal(JSON.stringify(page).includes('proxy_token'), false);
  assert.equal(JSON.stringify(page).includes('API_KEY'), false);
  assert.match(calls[0].url, /instances\/\?page=2&page_size=20&search=Primary&status=running/u);
  assert.equal(calls[0].init.headers.get('Authorization'), 'Bearer cloud-token');

  await client.restart(scope, 'instance-1');
  await client.delete(scope, 'instance-1');
  assert.match(calls[1].url, /instances\/instance-1\/restart$/u);
  assert.equal(calls[1].init.method, 'POST');
  assert.match(calls[2].url, /instances\/instance-1$/u);
  assert.equal(calls[2].init.method, 'DELETE');
});
test('Local Runtime Instances projects exactly one supervised sidecar without Cloud lifecycle fields', async () => {
  const client = createRuntimeInstancesClient(runtimeConfig('local'), {
    readLocalRuntimeStatus: async () => ({
      running: true,
      tool_count: 12,
      runtime_providers: ['builtin'],
      host_path: '/private/workspace',
      endpoint: 'http://127.0.0.1:9999',
    }),
  });
  const scope = { authority: 'local', tenantId: 'tenant-1' };
  const page = await client.list(scope, { search: 'sidecar', status: 'running' });
  assert.deepEqual(page, {
    instances: [
      {
        id: 'local-sidecar',
        name: 'Local sidecar',
        status: 'running',
        healthStatus: 'healthy',
        imageVersion: null,
        replicas: null,
        availableReplicas: null,
        clusterId: null,
        createdAt: null,
        updatedAt: null,
        projection: 'local_sidecar',
      },
    ],
    total: 1,
    page: 1,
    pageSize: 20,
  });
  assert.equal(JSON.stringify(page).includes('host_path'), false);
  assert.equal(JSON.stringify(page).includes('endpoint'), false);
  await assert.rejects(
    () => client.restart(scope, 'local-sidecar'),
    (error) =>
      error instanceof RuntimeInstancesUnavailableError &&
      error.reasonCode === 'local_instance_lifecycle_not_applicable',
  );
});

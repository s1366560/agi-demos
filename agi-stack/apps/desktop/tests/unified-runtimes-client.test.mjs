import assert from 'node:assert/strict';
import { test } from 'node:test';

const {
  createUnifiedRuntimesClient,
  UnifiedRuntimesUnavailableError,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/unified-runtimes/unifiedRuntimesClient.js'
);

function runtimeConfig(mode, overrides = {}) {
  return {
    mode,
    apiBaseUrl: 'https://api.example.test',
    deviceAuthorizationBaseUrl: 'https://api.example.test',
    apiKey: 'test-token',
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

test('Cloud Unified Runtimes binds every inventory response to the tenant and project scope', async () => {
  const calls = [];
  const poolScopes = [];
  const client = createUnifiedRuntimesClient(runtimeConfig('cloud'), {
    poolClient: {
      getStatus: async (scope) => {
        poolScopes.push(scope);
        return {
          enabled: true,
          status: 'running',
          totalInstances: 1,
          hotInstances: 1,
          warmInstances: 0,
          coldInstances: 0,
          readyInstances: 1,
          executingInstances: 0,
          unhealthyInstances: 0,
          prewarmPool: null,
          resourceUsage: null,
          reasonCode: 'global_pool_capacity_not_available_in_tenant_scope',
        };
      },
      listInstances: async (scope) => {
        poolScopes.push(scope);
        return {
          instances: [
            {
              instanceKey: 'actor-1',
              tenantId: 'tenant-1',
              projectId: 'project-1',
              agentMode: 'react',
              tier: 'hot',
              status: 'ready',
              createdAt: '2026-08-02T00:00:00Z',
              lastRequestAt: null,
              activeRequests: 0,
              totalRequests: 2,
              memoryUsedMb: 64,
              healthStatus: 'healthy',
            },
          ],
          total: 1,
          page: 1,
          pageSize: 100,
        };
      },
    },
    fetch: async (url) => {
      calls.push(String(url));
      if (String(url).includes('/projects/sandboxes')) {
        return response({
          sandboxes: [
            {
              sandbox_id: 'sandbox-1',
              tenant_id: 'tenant-1',
              project_id: 'project-1',
              status: 'running',
              is_healthy: true,
            },
          ],
          total: 1,
        });
      }
      if (String(url).includes('/projects/project-1/sandbox/stats')) {
        return response({
          project_id: 'project-1',
          sandbox_id: 'sandbox-1',
          status: 'running',
          cpu_percent: 4,
          memory_usage: 1048576,
          memory_limit: 2097152,
          memory_percent: 50,
          pids: 3,
          collected_at: '2026-08-02T00:00:00Z',
        });
      }
      throw new Error(`unexpected request ${String(url)}`);
    },
  });

  const scope = { authority: 'cloud', tenantId: 'tenant-1', projectId: 'project-1' };
  const [status, instances, sandboxes, stats] = await Promise.all([
    client.getPoolStatus(scope),
    client.listPoolInstances(scope),
    client.listSandboxes(scope),
    client.getSandboxStats(scope, 'project-1'),
  ]);

  assert.equal(status.totalInstances, 1);
  assert.equal(instances.instances[0].tenantId, 'tenant-1');
  assert.equal(sandboxes[0].projectId, 'project-1');
  assert.equal(stats?.pids, 3);
  assert.ok(calls.every((url) => url.startsWith('https://api.example.test/')));
  assert.deepEqual(poolScopes, [
    { authority: 'cloud', tenantId: 'tenant-1' },
    { authority: 'cloud', tenantId: 'tenant-1' },
  ]);
});

test('Cloud Unified Runtimes rejects cross-tenant sandbox rows before projection', async () => {
  const client = createUnifiedRuntimesClient(runtimeConfig('cloud'), {
    fetch: async () =>
      response({
        sandboxes: [
          {
            sandbox_id: 'sandbox-other',
            tenant_id: 'tenant-2',
            project_id: 'project-2',
            status: 'running',
            is_healthy: true,
          },
        ],
        total: 1,
      }),
  });

  await assert.rejects(
    () =>
      client.listSandboxes({
        authority: 'cloud',
        tenantId: 'tenant-1',
        projectId: 'project-1',
      }),
    (error) =>
      error instanceof UnifiedRuntimesUnavailableError &&
      error.reasonCode === 'unified_runtimes_sandbox_scope_mismatch',
  );
});

test('Local Unified Runtimes reads only redacted sidecar status and sandbox capabilities', async () => {
  let fetchCalls = 0;
  let statusCalls = 0;
  const client = createUnifiedRuntimesClient(runtimeConfig('local'), {
    fetch: async (url) => {
      fetchCalls += 1;
      assert.match(String(url), /\/projects\/project-1\/sandbox\/capabilities$/u);
      return response({
        service_version: '0.1.0',
        contract_version: 2,
        terminal_interactive: {
          availability: 'available',
          contract_version: 1,
          reason_code: null,
        },
        terminal_resume: {
          availability: 'unavailable',
          contract_version: 2,
          reason_code: 'local_terminal_resume_unavailable',
        },
        files: {
          availability: 'available',
          contract_version: 1,
          reason_code: null,
        },
        kasm_vnc: {
          availability: 'not_applicable',
          contract_version: 1,
          reason_code: 'local_kasm_vnc_not_applicable',
        },
      });
    },
    readLocalRuntimeStatus: async () => {
      statusCalls += 1;
      return {
        running: true,
        api_base_url: 'http://127.0.0.1:31000',
        api_token: 'must-never-project',
        workspace_root: '/private/workspace',
        tool_count: 14,
        tools: ['read_file'],
        config: { workspace_root: '/private/workspace' },
        runtime_providers: [
          {
            tenant_id: 'tenant-1',
            provider_id: 'provider-1',
            provider_type: 'openai',
            model: 'model-1',
            credential_configured: true,
          },
        ],
      };
    },
  });
  const scope = { authority: 'local', tenantId: 'tenant-1', projectId: 'project-1' };

  const [sidecar, capabilities] = await Promise.all([
    client.getLocalSidecar(scope),
    client.getSandboxCapabilities(scope),
  ]);
  assert.deepEqual(sidecar, {
    running: true,
    toolCount: 14,
    providerCount: 1,
  });
  assert.equal(capabilities.files.availability, 'available');
  assert.equal(statusCalls, 1);
  assert.equal(fetchCalls, 1);
  await assert.rejects(
    () => client.getPoolStatus(scope),
    (error) =>
      error instanceof UnifiedRuntimesUnavailableError &&
      error.reasonCode === 'local_pool_not_applicable_sidecar_projection',
  );
});

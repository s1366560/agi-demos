import assert from 'node:assert/strict';
import { test } from 'node:test';

const { createUnifiedRuntimesController } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/unified-runtimes/unifiedRuntimesController.js'
);

const cloudScope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
  projectId: 'project-1',
});
const localScope = Object.freeze({
  authority: 'local',
  tenantId: 'tenant-1',
  projectId: 'project-1',
});

function poolStatus() {
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
}

function poolPage() {
  return {
    instances: [
      {
        instanceKey: 'actor-1',
        tenantId: 'tenant-1',
        projectId: 'project-1',
        agentMode: 'react',
        tier: 'hot',
        status: 'ready',
        createdAt: null,
        lastRequestAt: null,
        activeRequests: 0,
        totalRequests: 1,
        memoryUsedMb: 64,
        healthStatus: 'healthy',
      },
    ],
    total: 1,
    page: 1,
    pageSize: 100,
  };
}

test('Cloud Unified Runtimes settles pool and sandbox resources independently', async () => {
  const controller = createUnifiedRuntimesController({
    authority: 'cloud',
    initialScope: cloudScope,
    client: {
      getPoolStatus: async () => poolStatus(),
      listPoolInstances: async () => poolPage(),
      listSandboxes: async () => [
        {
          sandboxId: 'sandbox-1',
          tenantId: 'tenant-1',
          projectId: 'project-1',
          status: 'running',
          healthy: true,
          createdAt: null,
          lastAccessedAt: null,
        },
      ],
      getSandboxStats: async () => ({
        projectId: 'project-1',
        sandboxId: 'sandbox-1',
        status: 'running',
        memoryUsageBytes: 1048576,
        pids: 2,
        collectedAt: '2026-08-02T00:00:00Z',
      }),
      getLocalSidecar: async () => {
        throw new Error('local status must not be called');
      },
      getSandboxCapabilities: async () => {
        throw new Error('local capabilities must not be called');
      },
    },
  });

  await controller.load(cloudScope);
  const model = controller.getSnapshot();
  assert.equal(model.poolState, 'ready');
  assert.equal(model.sandboxState, 'ready');
  assert.equal(model.sidecarState, 'not_applicable');
  assert.equal(model.rows.length, 2);
  assert.equal(model.rows[0].kind, 'pool_actor');
  assert.equal(model.rows[1].kind, 'sandbox');
  assert.equal(model.reasonCode, 'global_pool_capacity_not_available_in_tenant_scope');
  assert.ok(model.allowedActions.includes('inspect-pool'));
});

test('Cloud Unified Runtimes retains verified rows as stale when one authority fails', async () => {
  let failPool = false;
  const controller = createUnifiedRuntimesController({
    authority: 'cloud',
    initialScope: cloudScope,
    client: {
      getPoolStatus: async () => {
        if (failPool) throw new Error('pool offline');
        return poolStatus();
      },
      listPoolInstances: async () => {
        if (failPool) throw new Error('pool offline');
        return poolPage();
      },
      listSandboxes: async () => [],
      getSandboxStats: async () => null,
      getLocalSidecar: async () => {
        throw new Error('local status must not be called');
      },
      getSandboxCapabilities: async () => {
        throw new Error('local capabilities must not be called');
      },
    },
  });
  await controller.load(cloudScope);
  failPool = true;
  await controller.retry(cloudScope);

  const model = controller.getSnapshot();
  assert.equal(model.poolState, 'stale');
  assert.equal(model.rows.length, 1);
  assert.equal(model.poolReasonCode, 'unified_runtimes_pool_load_failed');
  assert.equal(model.retryPoolVisible, true);
});

test('Local Unified Runtimes never simulates a Cloud pool and exposes sidecar degradation', async () => {
  let cloudCalls = 0;
  const controller = createUnifiedRuntimesController({
    authority: 'local',
    initialScope: localScope,
    client: {
      getPoolStatus: async () => {
        cloudCalls += 1;
        return poolStatus();
      },
      listPoolInstances: async () => {
        cloudCalls += 1;
        return poolPage();
      },
      listSandboxes: async () => {
        cloudCalls += 1;
        return [];
      },
      getSandboxStats: async () => {
        cloudCalls += 1;
        return null;
      },
      getLocalSidecar: async () => ({
        running: true,
        toolCount: 12,
        providerCount: 1,
      }),
      getSandboxCapabilities: async () => ({
        serviceVersion: '0.1.0',
        contractVersion: '2',
        terminalInteractive: {
          availability: 'available',
          reasonCode: null,
        },
        terminalResume: {
          availability: 'unavailable',
          reasonCode: 'local_terminal_resume_unavailable',
        },
        files: { availability: 'available', reasonCode: null },
        kasmVnc: {
          availability: 'not_applicable',
          reasonCode: 'local_kasm_vnc_not_applicable',
        },
      }),
    },
  });

  await controller.load(localScope);
  const model = controller.getSnapshot();
  assert.equal(cloudCalls, 0);
  assert.equal(model.poolState, 'not_applicable');
  assert.equal(model.poolReasonCode, 'local_pool_not_applicable_sidecar_projection');
  assert.equal(model.sidecarState, 'ready');
  assert.equal(model.sandboxState, 'degraded');
  assert.equal(model.rows.length, 2);
  assert.deepEqual(model.allowedActions, [
    'view',
    'refresh',
    'inspect-sidecar',
    'inspect-sandbox-capabilities',
  ]);
});

test('Unified Runtimes suppresses stale completion after a scope switch', async () => {
  let resolveFirst;
  const first = new Promise((resolve) => {
    resolveFirst = resolve;
  });
  const client = {
    getPoolStatus: async (scope) => {
      if (scope.tenantId === 'tenant-1') return first;
      return { ...poolStatus(), totalInstances: 0 };
    },
    listPoolInstances: async () => ({ ...poolPage(), instances: [] }),
    listSandboxes: async () => [],
    getSandboxStats: async () => null,
    getLocalSidecar: async () => {
      throw new Error('local status must not be called');
    },
    getSandboxCapabilities: async () => {
      throw new Error('local capabilities must not be called');
    },
  };
  const controller = createUnifiedRuntimesController({
    authority: 'cloud',
    initialScope: cloudScope,
    client,
  });

  const oldLoad = controller.load(cloudScope);
  const nextScope = { ...cloudScope, tenantId: 'tenant-2', projectId: 'project-2' };
  await controller.load(nextScope);
  resolveFirst(poolStatus());
  await oldLoad;

  const model = controller.getSnapshot();
  assert.equal(model.scope.tenantId, 'tenant-2');
  assert.equal(model.poolStatus?.totalInstances, 0);
});

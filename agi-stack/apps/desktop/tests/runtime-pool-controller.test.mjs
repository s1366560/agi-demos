import assert from 'node:assert/strict';
import { test } from 'node:test';

const { DesktopApiError } = await import(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);
const { createRuntimePoolController } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/runtime-pool/runtimePoolController.js'
);

test('Runtime Pool controller settles resources independently and retains verified stale data', async () => {
  let fail = false;
  const controller = createRuntimePoolController({
    authority: 'cloud',
    client: client({
      async getMetrics() {
        if (fail) throw new DesktopApiError('offline', 503, {});
        return metrics();
      },
      async getStatus() {
        if (fail) throw new DesktopApiError('offline', 503, {});
        return status();
      },
      async listInstances() {
        if (fail) throw new DesktopApiError('offline', 503, {});
        return instancePage();
      },
    }),
    initialScope: scope(),
  });

  await controller.load(scope());
  assert.equal(controller.getSnapshot().statusState, 'ready');
  assert.equal(controller.getSnapshot().instancesState, 'ready');
  assert.equal(controller.getSnapshot().metricsState, 'ready');
  fail = true;
  await controller.retry();
  assert.equal(controller.getSnapshot().statusState, 'stale');
  assert.equal(controller.getSnapshot().instancesState, 'stale');
  assert.equal(controller.getSnapshot().metricsState, 'stale');
  assert.equal(controller.getSnapshot().instances.length, 1);
});

test('Runtime Pool controller supports exact filters, lifecycle actions, and structured errors', async () => {
  const calls = [];
  const controller = createRuntimePoolController({
    authority: 'cloud',
    client: client({
      async listInstances(_scope, query) {
        calls.push(['list', query]);
        return instancePage({ page: query.page, pageSize: query.pageSize });
      },
      async pauseInstance(_scope, instanceKey) {
        calls.push(['pause', instanceKey]);
      },
      async resumeInstance(_scope, instanceKey) {
        calls.push(['resume', instanceKey]);
      },
      async terminateInstance(_scope, instanceKey, graceful) {
        calls.push(['terminate', instanceKey, graceful]);
      },
    }),
    initialScope: scope(),
  });

  await controller.load(scope());
  await controller.setQuery({
    tier: 'hot',
    status: 'ready',
    page: 2,
    pageSize: 25,
  });
  await controller.pauseInstance('instance-1');
  await controller.resumeInstance('instance-1');
  await controller.terminateInstance('instance-1');

  assert.deepEqual(controller.getSnapshot().query, {
    tier: 'hot',
    status: 'ready',
    page: 2,
    pageSize: 25,
  });
  assert.deepEqual(
    calls.filter(([kind]) => kind !== 'list'),
    [
      ['pause', 'instance-1'],
      ['resume', 'instance-1'],
      ['terminate', 'instance-1', true],
    ],
  );

  const forbidden = createRuntimePoolController({
    authority: 'cloud',
    client: client({
      async pauseInstance() {
        throw new DesktopApiError('forbidden', 403, {
          reason_code: 'global_admin_required',
        });
      },
    }),
    initialScope: scope(),
  });
  await forbidden.load(scope());
  await assert.rejects(forbidden.pauseInstance('instance-1'), /forbidden/u);
  assert.equal(forbidden.getSnapshot().mutationState, 'forbidden');
  assert.equal(
    forbidden.getSnapshot().mutationReasonCode,
    'global_admin_required',
  );
});

test('Local Runtime Pool is structurally not-applicable without invoking its client', async () => {
  let calls = 0;
  const localScope = { authority: 'local', tenantId: 'tenant-1' };
  const local = createRuntimePoolController({
    authority: 'local',
    client: client({
      async getStatus() {
        calls += 1;
        return status();
      },
      async listInstances() {
        calls += 1;
        return instancePage();
      },
      async getMetrics() {
        calls += 1;
        return metrics();
      },
    }),
    initialScope: localScope,
  });
  await local.load(localScope);

  const model = local.getSnapshot();
  assert.equal(model.statusState, 'unavailable');
  assert.equal(model.instancesState, 'unavailable');
  assert.equal(model.metricsState, 'unavailable');
  assert.equal(model.statusReasonCode, 'cloud_runtime_pool_not_applicable');
  assert.deepEqual(model.allowedActions, []);
  assert.equal(model.status, null);
  assert.equal(model.metrics, null);
  assert.equal(calls, 0);
});

function client(overrides = {}) {
  return {
    async getStatus() {
      return status();
    },
    async listInstances() {
      return instancePage();
    },
    async getMetrics() {
      return metrics();
    },
    async pauseInstance() {},
    async resumeInstance() {},
    async terminateInstance() {},
    ...overrides,
  };
}

function scope() {
  return { authority: 'cloud', tenantId: 'tenant-1' };
}

function status() {
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

function instancePage(overrides = {}) {
  return {
    instances: [
      {
        instanceKey: 'instance-1',
        tenantId: 'tenant-1',
        projectId: 'project-1',
        agentMode: 'chat',
        tier: 'hot',
        status: 'ready',
        createdAt: '2026-08-01T00:00:00Z',
        lastRequestAt: '2026-08-01T00:01:00Z',
        activeRequests: 0,
        totalRequests: 1,
        memoryUsedMb: 128,
        healthStatus: 'healthy',
      },
    ],
    total: 1,
    page: 1,
    pageSize: 20,
    ...overrides,
  };
}

function metrics() {
  return {
    instances: {
      total: 1,
      byTier: { hot: 1, warm: 0, cold: 0 },
      byStatus: { ready: 1, executing: 0, unhealthy: 0 },
    },
    unhealthyCount: 0,
    prewarm: null,
    reasonCode: 'global_pool_capacity_not_available_in_tenant_scope',
  };
}

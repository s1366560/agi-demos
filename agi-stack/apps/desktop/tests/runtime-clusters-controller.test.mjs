import assert from 'node:assert/strict';
import { test } from 'node:test';

const { createRuntimeClustersController } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/runtime-clusters/runtimeClustersController.js'
);
const { DesktopApiError } = await import(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);

const cloudScope = Object.freeze({ authority: 'cloud', tenantId: 'tenant-1' });
const localScope = Object.freeze({ authority: 'local', tenantId: 'tenant-1' });

function cluster() {
  return {
    id: 'cluster-1',
    name: 'Primary',
    computeProvider: 'kubernetes',
    proxyEndpoint: 'https://cluster.example.test',
    status: 'active',
    healthStatus: 'healthy',
    lastHealthCheck: null,
    createdAt: null,
    updatedAt: null,
  };
}

function page() {
  return { clusters: [cluster()], total: 1, page: 1, pageSize: 20 };
}

test('Runtime Clusters covers Cloud load, current-page filters, health, and stale retention', async () => {
  let fail = false;
  const controller = createRuntimeClustersController({
    authority: 'cloud',
    initialScope: cloudScope,
    client: {
      list: async () => {
        if (fail) throw new Error('offline');
        return page();
      },
      getHealth: async () => ({
        status: 'healthy',
        nodeCount: 3,
        cpuUsage: 20,
        memoryUsage: 40,
        checkedAt: null,
      }),
    },
  });
  await controller.load(cloudScope);
  assert.equal(controller.getSnapshot().state, 'ready');
  await controller.setFilters({ search: 'no-match', status: 'all' });
  assert.equal(controller.getSnapshot().visibleClusters.length, 0);
  await controller.setFilters({ search: '', status: 'active' });
  assert.equal(controller.getSnapshot().visibleClusters.length, 1);
  await controller.inspectHealth('cluster-1');
  assert.equal(controller.getSnapshot().health?.nodeCount, 3);
  fail = true;
  await controller.retry();
  assert.equal(controller.getSnapshot().state, 'stale');
  assert.equal(controller.getSnapshot().clusters.length, 1);
});

test('Runtime Clusters keeps Local unavailable and maps Cloud forbidden errors', async () => {
  const local = createRuntimeClustersController({
    authority: 'local',
    initialScope: localScope,
    client: {
      list: async () => {
        throw new Error('must not run');
      },
      getHealth: async () => {
        throw new Error('must not run');
      },
    },
  });
  await local.load(localScope);
  assert.equal(local.getSnapshot().state, 'unavailable');
  assert.equal(
    local.getSnapshot().reasonCode,
    'cloud_cluster_control_not_applicable',
  );
  assert.deepEqual(local.getSnapshot().allowedActions, []);

  const forbidden = createRuntimeClustersController({
    authority: 'cloud',
    initialScope: cloudScope,
    client: {
      list: async () => {
        throw new DesktopApiError('forbidden', 403, null);
      },
      getHealth: async () => {
        throw new Error('unused');
      },
    },
  });
  await forbidden.load(cloudScope);
  assert.equal(forbidden.getSnapshot().state, 'forbidden');

  const conflict = createRuntimeClustersController({
    authority: 'cloud',
    initialScope: cloudScope,
    client: {
      list: async () => {
        throw new DesktopApiError('conflict', 409, null);
      },
      getHealth: async () => {
        throw new Error('unused');
      },
    },
  });
  await conflict.load(cloudScope);
  assert.equal(conflict.getSnapshot().state, 'conflict');
  await conflict.load({ authority: 'local', tenantId: 'tenant-1' });
  assert.equal(conflict.getSnapshot().state, 'unavailable');
  assert.equal(
    conflict.getSnapshot().reasonCode,
    'runtime_clusters_controller_authority_mismatch',
  );
});

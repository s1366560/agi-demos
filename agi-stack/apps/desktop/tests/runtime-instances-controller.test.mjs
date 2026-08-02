import assert from 'node:assert/strict';
import { test } from 'node:test';

const { createRuntimeInstancesController } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/runtime-instances/runtimeInstancesController.js'
);
const { DesktopApiError } = await import(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);

const cloudScope = Object.freeze({ authority: 'cloud', tenantId: 'tenant-1' });
const localScope = Object.freeze({ authority: 'local', tenantId: 'tenant-1' });

function instance(projection = 'cloud') {
  return {
    id: projection === 'cloud' ? 'instance-1' : 'local-sidecar',
    name: projection === 'cloud' ? 'Primary' : 'Local sidecar',
    status: 'running',
    healthStatus: 'healthy',
    imageVersion: projection === 'cloud' ? '2026.08' : null,
    replicas: projection === 'cloud' ? 1 : null,
    availableReplicas: projection === 'cloud' ? 1 : null,
    clusterId: projection === 'cloud' ? 'cluster-1' : null,
    createdAt: null,
    updatedAt: null,
    projection,
  };
}

function page(projection = 'cloud') {
  return {
    instances: [instance(projection)],
    total: 1,
    page: 1,
    pageSize: 20,
  };
}

test('Runtime Instances covers Cloud load, query, mutation refresh, and stale retention', async () => {
  const queries = [];
  let restarts = 0;
  let fail = false;
  const controller = createRuntimeInstancesController({
    authority: 'cloud',
    initialScope: cloudScope,
    client: {
      list: async (_scope, query) => {
        queries.push(query);
        if (fail) throw new Error('offline');
        return page();
      },
      restart: async () => {
        restarts += 1;
      },
      delete: async () => {},
    },
  });
  await controller.load(cloudScope);
  assert.equal(controller.getSnapshot().state, 'ready');
  assert.ok(controller.getSnapshot().allowedActions.includes('restart'));
  await controller.setQuery({ search: 'Primary', status: 'running', page: 1 });
  assert.equal(queries.at(-1).search, 'Primary');
  await controller.restart('instance-1');
  assert.equal(restarts, 1);
  fail = true;
  await controller.retry();
  assert.equal(controller.getSnapshot().state, 'stale');
  assert.equal(controller.getSnapshot().instances.length, 1);
  assert.equal(controller.getSnapshot().reasonCode, 'runtime_instances_load_failed');
});
test('Runtime Instances exposes Local read-only actions and structured forbidden/conflict states', async () => {
  const local = createRuntimeInstancesController({
    authority: 'local',
    initialScope: localScope,
    client: {
      list: async () => page('local_sidecar'),
      restart: async () => {
        throw new Error('must not run');
      },
      delete: async () => {
        throw new Error('must not run');
      },
    },
  });
  await local.load(localScope);
  assert.deepEqual(local.getSnapshot().allowedActions, [
    'view',
    'list',
    'refresh',
    'search',
    'filter-status',
  ]);
  await assert.rejects(() => local.restart('local-sidecar'), /not_allowed/u);

  for (const [status, expected] of [
    [403, 'forbidden'],
    [409, 'conflict'],
  ]) {
    const controller = createRuntimeInstancesController({
      authority: 'cloud',
      initialScope: cloudScope,
      client: {
        list: async () => page(),
        restart: async () => {
          throw new DesktopApiError('mutation failed', status, null);
        },
        delete: async () => {},
      },
    });
    await controller.load(cloudScope);
    await assert.rejects(() => controller.restart('instance-1'));
    assert.equal(controller.getSnapshot().mutationState, expected);
  }
});

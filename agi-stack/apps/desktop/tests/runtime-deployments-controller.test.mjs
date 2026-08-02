import assert from 'node:assert/strict';
import { test } from 'node:test';

const { createRuntimeDeploymentsController } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/runtime-deployments/runtimeDeploymentsController.js'
);
const { DesktopApiError } = await import(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);

const cloudScope = Object.freeze({
  authority: 'cloud',
  tenantId: 'tenant-1',
  instanceId: 'instance-1',
});
const localScope = Object.freeze({
  authority: 'local',
  tenantId: 'tenant-1',
  instanceId: 'instance-1',
});

function deployment(overrides = {}) {
  return {
    id: 'deploy-1',
    instanceId: 'instance-1',
    action: 'update',
    revision: 7,
    status: 'running',
    imageVersion: 'v1.2.3',
    replicas: 3,
    startedAt: '2026-08-02T08:00:00Z',
    finishedAt: null,
    createdAt: '2026-08-02T07:59:00Z',
    ...overrides,
  };
}

function page() {
  return {
    deployments: [deployment()],
    total: 1,
    page: 1,
    pageSize: 10,
  };
}

test('Runtime Deployments loads history, refreshes detail from SSE, and retains stale data', async () => {
  let failList = false;
  let detailStatus = 'running';
  let onProgressEvent;
  const controller = createRuntimeDeploymentsController({
    authority: 'cloud',
    initialScope: cloudScope,
    client: {
      list: async () => {
        if (failList) throw new Error('offline');
        return page();
      },
      get: async () => deployment({ status: detailStatus }),
      streamProgress: (_scope, _deployId, onEvent) => {
        onProgressEvent = onEvent;
        return new Promise(() => {});
      },
    },
  });
  await controller.load(cloudScope);
  assert.equal(controller.getSnapshot().state, 'ready');
  await controller.inspect('deploy-1');
  assert.equal(controller.getSnapshot().selectedDeployment?.status, 'running');
  assert.equal(controller.getSnapshot().progressState, 'connected');

  detailStatus = 'success';
  await onProgressEvent({ type: 'done', status: 'success', deployId: null });
  assert.equal(controller.getSnapshot().selectedDeployment?.status, 'success');
  assert.equal(controller.getSnapshot().progressState, 'complete');

  failList = true;
  await controller.retry();
  assert.equal(controller.getSnapshot().state, 'stale');
  assert.equal(controller.getSnapshot().deployments.length, 1);
});

test('Runtime Deployments exposes reconnect after stream failure', async () => {
  let streamCalls = 0;
  const controller = createRuntimeDeploymentsController({
    authority: 'cloud',
    initialScope: cloudScope,
    client: {
      list: async () => page(),
      get: async () => deployment(),
      streamProgress: async () => {
        streamCalls += 1;
        throw new Error('stream disconnected');
      },
    },
  });
  await controller.load(cloudScope);
  await controller.inspect('deploy-1');
  assert.equal(controller.getSnapshot().progressState, 'stale');
  assert.equal(controller.getSnapshot().progressRetryVisible, true);
  await controller.reconnectProgress();
  assert.equal(streamCalls, 2);
});

test('Runtime Deployments keeps Local unavailable and maps Cloud forbidden errors', async () => {
  const local = createRuntimeDeploymentsController({
    authority: 'local',
    initialScope: localScope,
    client: {
      list: async () => {
        throw new Error('must not run');
      },
      get: async () => {
        throw new Error('must not run');
      },
      streamProgress: async () => {
        throw new Error('must not run');
      },
    },
  });
  await local.load(localScope);
  assert.equal(local.getSnapshot().state, 'unavailable');
  assert.equal(
    local.getSnapshot().reasonCode,
    'cloud_deployment_authority_not_applicable',
  );
  assert.deepEqual(local.getSnapshot().allowedActions, []);

  const forbidden = createRuntimeDeploymentsController({
    authority: 'cloud',
    initialScope: cloudScope,
    client: {
      list: async () => {
        throw new DesktopApiError('forbidden', 403, null);
      },
      get: async () => deployment(),
      streamProgress: async () => {},
    },
  });
  await forbidden.load(cloudScope);
  assert.equal(forbidden.getSnapshot().state, 'forbidden');
});

test('Runtime Deployments fails closed when Cloud instance scope is missing', async () => {
  let listCalls = 0;
  const controller = createRuntimeDeploymentsController({
    authority: 'cloud',
    initialScope: {
      authority: 'cloud',
      tenantId: 'tenant-1',
      instanceId: null,
    },
    client: {
      list: async () => {
        listCalls += 1;
        return page();
      },
      get: async () => deployment(),
      streamProgress: async () => {},
    },
  });
  await controller.load({
    authority: 'cloud',
    tenantId: 'tenant-1',
    instanceId: null,
  });
  assert.equal(controller.getSnapshot().state, 'unavailable');
  assert.equal(
    controller.getSnapshot().reasonCode,
    'runtime_deployments_instance_scope_required',
  );
  assert.equal(listCalls, 0);
});

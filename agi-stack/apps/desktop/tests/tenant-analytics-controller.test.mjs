import assert from 'node:assert/strict';
import { test } from 'node:test';

const { DesktopApiError } = await import(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);
const {
  createTenantAnalyticsController,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantAnalyticsController.js'
);

test('analytics controller cancels stale scope reads and retries the latest scope', async () => {
  const pending = new Map();
  const client = {
    load(scope, options) {
      const request = deferred();
      pending.set(scope.tenantId, { ...request, signal: options.signal });
      return request.promise;
    },
  };
  const controller = createTenantAnalyticsController({
    authority: 'cloud',
    client,
    initialScope: scope('tenant-1'),
  });

  const first = controller.load(scope('tenant-1'));
  const second = controller.load(scope('tenant-2'));
  assert.equal(pending.get('tenant-1').signal.aborted, true);
  assert.equal(controller.getSnapshot().state, 'scope_switch');

  pending.get('tenant-1').resolve(snapshot('tenant-1'));
  await first;
  assert.equal(controller.getSnapshot().scope.tenantId, 'tenant-2');

  pending.get('tenant-2').resolve(snapshot('tenant-2'));
  await second;
  assert.equal(controller.getSnapshot().state, 'empty');

  const retry = controller.retry();
  pending.get('tenant-2').resolve(snapshot('tenant-2'));
  await retry;
});

test('analytics controller maps forbidden, conflict, unavailable and retryable errors', async () => {
  const cases = [
    [403, 'tenant_analytics_forbidden', 'forbidden', false],
    [409, 'tenant_analytics_conflict', 'conflict', true],
    [503, 'tenant_analytics_unavailable', 'unavailable', true],
    [500, 'tenant_analytics_failed', 'error', true],
  ];
  for (const [status, reasonCode, state, retryVisible] of cases) {
    const controller = createTenantAnalyticsController({
      authority: 'cloud',
      client: {
        async load() {
          throw new DesktopApiError(reasonCode, status, {
            reason_code: reasonCode,
          });
        },
      },
      initialScope: scope('tenant-1'),
    });
    await controller.load(scope('tenant-1'));
    assert.equal(controller.getSnapshot().state, state);
    assert.equal(controller.getSnapshot().reasonCode, reasonCode);
    assert.equal(controller.getSnapshot().retryVisible, retryVisible);
  }
});

function scope(tenantId) {
  return { authority: 'cloud', tenantId, period: '30d' };
}

function snapshot(tenantId) {
  const available = (value) => ({
    availability: 'available',
    reasonCode: null,
    value,
  });
  return {
    scope: scope(tenantId),
    authority: 'cloud',
    availability: 'available',
    reasonCode: null,
    serviceVersion: 'cloud',
    contractVersion: '3.0.0',
    allowedActions: ['view', 'retry'],
    authorityRevision: null,
    memoryGrowth: available([]),
    projectStorage: available([]),
    summary: {
      totalMemories: available(0),
      totalStorageBytes: available(0),
      totalProjects: available(0),
      periodDays: 30,
    },
  };
}

function deferred() {
  let resolve;
  const promise = new Promise((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

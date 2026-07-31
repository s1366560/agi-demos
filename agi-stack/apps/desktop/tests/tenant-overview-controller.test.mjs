import assert from 'node:assert/strict';
import { test } from 'node:test';

const { DesktopApiError } = await import(
  '/tmp/agistack-desktop-test-dist/src/api/client.js'
);
const {
  createTenantOverviewController,
} = await import(
  '/tmp/agistack-desktop-test-dist/src/features/tenant/tenantOverviewController.js'
);

test('controller loads, retries and hides stale tenant results after a scope switch', async () => {
  const pending = new Map();
  const client = {
    load(scope, options) {
      const request = deferred();
      pending.set(scope.tenantId, { ...request, signal: options.signal });
      return request.promise;
    },
  };
  const controller = createTenantOverviewController({
    authority: 'cloud',
    client,
    initialScope: cloudScope('tenant-1'),
  });

  const first = controller.load(cloudScope('tenant-1'));
  assert.equal(controller.getSnapshot().state, 'loading');
  const second = controller.load(cloudScope('tenant-2'));
  assert.equal(pending.get('tenant-1').signal.aborted, true);
  assert.equal(controller.getSnapshot().state, 'scope_switch');
  assert.equal(controller.getSnapshot().tenant, null);

  pending.get('tenant-1').resolve(snapshot('tenant-1'));
  await first;
  assert.equal(controller.getSnapshot().scope.tenantId, 'tenant-2');
  assert.equal(controller.getSnapshot().state, 'scope_switch');

  pending.get('tenant-2').resolve(snapshot('tenant-2'));
  await second;
  assert.equal(controller.getSnapshot().state, 'ready');
  assert.equal(controller.getSnapshot().scope.tenantId, 'tenant-2');

  const retry = controller.retry();
  pending.get('tenant-2').resolve(snapshot('tenant-2'));
  await retry;
});

test('controller maps forbidden, unavailable and retryable failures structurally', async () => {
  const cases = [
    [403, 'tenant_forbidden', 'forbidden', false],
    [503, 'tenant_stats_unavailable', 'unavailable', true],
    [500, 'tenant_stats_failed', 'error', true],
  ];
  for (const [status, reasonCode, state, retryVisible] of cases) {
    const controller = createTenantOverviewController({
      authority: 'cloud',
      client: {
        async load() {
          throw new DesktopApiError(reasonCode, status, {
            reason_code: reasonCode,
          });
        },
      },
      initialScope: cloudScope('tenant-1'),
    });
    await controller.load(cloudScope('tenant-1'));
    assert.equal(controller.getSnapshot().state, state);
    assert.equal(controller.getSnapshot().reasonCode, reasonCode);
    assert.equal(controller.getSnapshot().retryVisible, retryVisible);
  }
});

test('controller rejects authority drift before calling the client', async () => {
  let calls = 0;
  const controller = createTenantOverviewController({
    authority: 'local',
    client: {
      async load() {
        calls += 1;
        return snapshot('tenant-1', 'local');
      },
    },
    initialScope: localScope('tenant-1'),
  });

  await controller.load(cloudScope('tenant-1'));

  assert.equal(calls, 0);
  assert.equal(controller.getSnapshot().state, 'unavailable');
  assert.equal(
    controller.getSnapshot().reasonCode,
    'tenant_overview_controller_authority_mismatch',
  );
});

function cloudScope(tenantId) {
  return { authority: 'cloud', tenantId };
}

function localScope(tenantId) {
  return { authority: 'local', tenantId };
}

function snapshot(tenantId, authority = 'cloud') {
  return {
    scope: { authority, tenantId },
    authority,
    availability: 'available',
    reasonCode: null,
    serviceVersion: '1.0.0',
    contractVersion: '3.0.0',
    allowedActions: ['view'],
    authorityRevision: null,
    tenantInfo: {
      organizationId: '#TEN-ABC',
      plan: 'Pro',
      region: availableField(null),
      nextBillingDate: availableField(null),
    },
    storage: availableField({ used: 0, total: 1, percentage: 0 }),
    projects: {
      availability: 'available',
      reasonCode: null,
      value: [],
      active: 0,
      newThisWeek: 0,
    },
    members: availableField({ total: 1, newAdded: 0 }),
    memoryHistory: availableField([]),
  };
}

function availableField(value) {
  return { availability: 'available', reasonCode: null, value };
}

function deferred() {
  let resolve;
  const promise = new Promise((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

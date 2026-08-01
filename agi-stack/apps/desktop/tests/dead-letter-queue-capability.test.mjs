import assert from 'node:assert/strict';
import { test } from 'node:test';

const { CANONICAL_DESKTOP_ROUTE_IDS, createDesktopCanonicalRouteCatalog } =
  await import('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopCanonicalRouteCatalog.js');
const { evaluateDesktopRouteAccess } =
  await import('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteHostModel.js');
const { deadLetterQueueCapability } =
  await import('/tmp/agistack-desktop-test-dist/src/features/governance/deadLetterQueueCapability.js');

test('DLQ capability is Cloud available and Local specifically not-applicable', () => {
  const definition = catalog().byId.get('tenant-tenant-dead-letter-queue');
  const context = { tenantId: 'tenant-1' };
  const match = { definition, context, canonicalPath: '/tenant/tenant-1/dead-letter-queue' };
  const permissions = new Set(['authenticated', 'global_admin']);
  const cloudCapability = deadLetterQueueCapability(runtimeConfig());
  const localCapability = deadLetterQueueCapability(runtimeConfig({ mode: 'local' }));

  assert.equal(cloudCapability.availability, 'available');
  assert.deepEqual(
    evaluateDesktopRouteAccess({ match, mode: 'cloud', permissions, capability: cloudCapability }),
    { status: 'allowed', presentation: 'ready', capability: cloudCapability },
  );
  assert.equal(localCapability.availability, 'not_applicable');
  assert.deepEqual(
    evaluateDesktopRouteAccess({ match, mode: 'local', permissions, capability: localCapability }),
    {
      status: 'unavailable',
      reasonCode: 'cloud_message_bus_dlq_not_applicable',
      capability: localCapability,
    },
  );
});

function catalog() {
  const loaders = Object.fromEntries(
    CANONICAL_DESKTOP_ROUTE_IDS.map((routeId) => [routeId, async () => ({ routeId })]),
  );
  return createDesktopCanonicalRouteCatalog(loaders);
}

function runtimeConfig(overrides = {}) {
  return {
    mode: 'cloud',
    apiBaseUrl: 'https://memstack.test',
    deviceAuthorizationBaseUrl: 'https://memstack.test',
    apiKey: 'test-token',
    localApiToken: 'test-local-token',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: '',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

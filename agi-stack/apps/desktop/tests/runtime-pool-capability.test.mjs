import assert from 'node:assert/strict';
import { test } from 'node:test';

const { CANONICAL_DESKTOP_ROUTE_IDS, createDesktopCanonicalRouteCatalog } =
  await import(
    '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopCanonicalRouteCatalog.js'
  );
const { evaluateDesktopRouteAccess } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteHostModel.js'
);
const { runtimePoolCapability } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/runtime-pool/runtimePoolCapability.js'
);

test('Runtime Pool is Cloud global-admin-only and Local specifically not-applicable', () => {
  const definition = catalog().byId.get('tenant-tenant-pool');
  const context = { tenantId: 'tenant-1' };
  const match = { definition, context, canonicalPath: '/tenant/tenant-1/pool' };
  const cloudCapability = {
    ...runtimePoolCapability(runtimeConfig()),
    authority_revision: 1,
    authority_source: 'cloud_service',
    provenance: 'observed',
  };
  const localCapability = runtimePoolCapability(
    runtimeConfig({ mode: 'local' }),
  );

  assert.equal(cloudCapability.availability, 'degraded');
  assert.equal(
    cloudCapability.reason_code,
    'global_pool_capacity_not_available_in_tenant_scope',
  );
  assert.equal(
    evaluateDesktopRouteAccess({
      match,
      mode: 'cloud',
      permissions: new Set(['authenticated']),
      capability: cloudCapability,
    }).status,
    'forbidden',
  );
  assert.equal(
    evaluateDesktopRouteAccess({
      match,
      mode: 'cloud',
      permissions: new Set(['authenticated', 'global_admin']),
      capability: cloudCapability,
    }).status,
    'allowed',
  );
  assert.deepEqual(
    evaluateDesktopRouteAccess({
      match,
      mode: 'local',
      permissions: new Set(['authenticated']),
      capability: localCapability,
    }),
    {
      status: 'unavailable',
      reasonCode: 'cloud_runtime_pool_not_applicable',
      capability: localCapability,
    },
  );
});

function catalog() {
  const loaders = Object.fromEntries(
    CANONICAL_DESKTOP_ROUTE_IDS.map((routeId) => [
      routeId,
      async () => ({ routeId }),
    ]),
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

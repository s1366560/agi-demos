import assert from 'node:assert/strict';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const compiledNavigationDirectory =
  '/tmp/agistack-desktop-test-dist/src/features/navigation';
mkdirSync(compiledNavigationDirectory, { recursive: true });
writeFileSync(`${compiledNavigationDirectory}/NativeUnavailableRoute.css`, '');
require.extensions['.css'] = () => {};
const {
  DESKTOP_CAPABILITY_NAMES,
  DESKTOP_INTERNAL_CAPABILITY_NAMES,
  DESKTOP_PARITY_CAPABILITY_NAMES,
  desktopCapability,
  parseDesktopCapabilitySnapshot,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/capabilitySnapshot.js');
const {
  createDesktopWorkbenchCapabilityClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/workbenchCapabilityClient.js');
const {
  DESKTOP_IMPLEMENTED_ROUTE_IDS,
  createDesktopProductionRouteRegistry,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRegistry.js');
const {
  evaluateDesktopRouteAccess,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteHostModel.js');
const {
  createDesktopRouteRegistry,
  matchDesktopRoute,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js');
const {
  DEFAULT_CONFIG,
} = require('/tmp/agistack-desktop-test-dist/src/types.js');

const parityManifest = JSON.parse(
  readFileSync(
    new URL(
      '../contracts/desktop-web-parity/parity-manifest.v3.json',
      import.meta.url,
    ),
    'utf8',
  ),
);

test('Snapshot v4 capability catalog closes every parity-manifest capability exactly once', () => {
  const manifestIds = parityManifest.capabilities.map(({ id }) => id);
  assert.equal(new Set(DESKTOP_CAPABILITY_NAMES).size, DESKTOP_CAPABILITY_NAMES.length);
  assert.deepEqual([...DESKTOP_PARITY_CAPABILITY_NAMES].sort(), manifestIds.sort());
  assert.deepEqual(DESKTOP_INTERNAL_CAPABILITY_NAMES, [
    'automation_run',
    'search',
    'workspace_collaboration',
    'sandbox_isolation',
  ]);
  assert.deepEqual(DESKTOP_CAPABILITY_NAMES, [
    ...DESKTOP_INTERNAL_CAPABILITY_NAMES,
    ...DESKTOP_PARITY_CAPABILITY_NAMES,
  ]);
});

const desktopRoot = new URL('../', import.meta.url);
const v3Fixture = JSON.parse(
  readFileSync(
    new URL('tests/fixtures/desktop-capability-snapshot.v3.json', desktopRoot),
    'utf8',
  ),
);
const v2Fixture = JSON.parse(
  readFileSync(
    new URL(
      'contracts/desktop-web-parity/fixtures/capability-snapshot.v2.json',
      desktopRoot,
    ),
    'utf8',
  ),
).input.snapshot;

const nullScope = {
  tenant_id: null,
  project_id: null,
  workspace_id: null,
  instance_id: null,
};

function v4Capability(overrides = {}) {
  return {
    availability: 'available',
    reason_code: null,
    service_version: '0.1.0',
    contract_version: '3.0.0',
    allowed_actions: ['view'],
    scope: nullScope,
    authority_revision: 1,
    authority_source: 'cloud_service',
    provenance: 'observed',
    ...overrides,
  };
}

function routeMatch() {
  const registry = createDesktopRouteRegistry([
    {
      id: 'tenant-overview',
      path: '/tenant/:tenantId/overview',
      scope: ['tenant'],
      navGroup: 'tenant-core',
      capability: 'tenant-tenant-overview',
      requiredPermission: [['authenticated', 'tenant_member']],
      localPolicy: 'native_equivalent',
      loader: async () => ({ default: 'TenantOverview' }),
    },
  ]);
  const match = matchDesktopRoute(registry, '#/tenant/tenant-1/overview');
  assert.ok(match);
  return match;
}

test('DesktopCapabilitySnapshot v4 accepts only observed active authority from the current mode', () => {
  const snapshot = parseDesktopCapabilitySnapshot({
    version: '4.0.0',
    mode: 'cloud',
    capabilities: { search: v4Capability() },
  });

  assert.equal(snapshot?.version, '4.0.0');
  assert.deepEqual(snapshot?.capabilities.search, v4Capability());
  assert.deepEqual(snapshot?.capabilities.workspace_collaboration, {
    availability: 'unavailable',
    reason_code: 'capability_not_declared',
    service_version: null,
    contract_version: null,
    allowed_actions: [],
    scope: nullScope,
    authority_revision: null,
    authority_source: 'renderer',
    provenance: 'declared',
  });

  const declaredActive = {
    version: '4.0.0',
    mode: 'cloud',
    capabilities: {
      search: v4Capability({
        authority_source: 'renderer',
        provenance: 'declared',
      }),
    },
  };
  assert.equal(parseDesktopCapabilitySnapshot(declaredActive), null);
  assert.equal(
    parseDesktopCapabilitySnapshot({
      ...declaredActive,
      capabilities: {
        search: v4Capability({ authority_source: 'sidecar' }),
      },
    }),
    null,
  );
  assert.equal(
    parseDesktopCapabilitySnapshot({
      ...declaredActive,
      capabilities: {
        search: v4Capability({ authority_revision: -1 }),
      },
    }),
    null,
  );
  assert.equal(
    parseDesktopCapabilitySnapshot({
      ...declaredActive,
      capabilities: {
        search: v4Capability({ authority_revision: null }),
      },
    }),
    null,
  );
  assert.equal(
    parseDesktopCapabilitySnapshot({
      ...declaredActive,
      capabilities: {
        search: v4Capability({ allowed_actions: [] }),
      },
    }),
    null,
  );
});

test('v2 and v3 snapshots remain readable but normalize to declared, non-ready authority', () => {
  const v3 = parseDesktopCapabilitySnapshot(v3Fixture);
  const v2 = parseDesktopCapabilitySnapshot(v2Fixture);

  assert.equal(v3?.version, '4.0.0');
  assert.equal(v2?.version, '4.0.0');
  assert.deepEqual(
    {
      authority_source: v3?.capabilities.search.authority_source,
      provenance: v3?.capabilities.search.provenance,
      available: desktopCapability(v3, 'search').available,
    },
    {
      authority_source: 'renderer',
      provenance: 'declared',
      available: false,
    },
  );
  assert.deepEqual(
    {
      authority_source: v2?.capabilities.search.authority_source,
      provenance: v2?.capabilities.search.provenance,
      available: desktopCapability(v2, 'search').available,
    },
    {
      authority_source: 'renderer',
      provenance: 'declared',
      available: false,
    },
  );
});

test('route host rejects legacy declared authority and mode-mismatched observed authority', () => {
  const legacy = parseDesktopCapabilitySnapshot(v3Fixture);
  const legacyCapability = legacy?.capabilities.search;
  assert.ok(legacyCapability);
  assert.deepEqual(
    evaluateDesktopRouteAccess({
      match: routeMatch(),
      mode: 'cloud',
      permissions: new Set(['authenticated', 'tenant_member']),
      capability: legacyCapability,
    }),
    {
      status: 'unavailable',
      reasonCode: 'desktop_route_capability_authority_unobserved',
      capability: legacyCapability,
    },
  );

  const wrongSource = v4Capability({
    scope: { ...nullScope, tenant_id: 'tenant-1' },
    authority_source: 'sidecar',
  });
  assert.deepEqual(
    evaluateDesktopRouteAccess({
      match: routeMatch(),
      mode: 'cloud',
      permissions: new Set(['authenticated', 'tenant_member']),
      capability: wrongSource,
    }),
    {
      status: 'unavailable',
      reasonCode: 'desktop_route_capability_authority_source_mismatch',
      capability: wrongSource,
    },
  );
});

test('route host requires observed active authority to bind every routed scope', () => {
  const unbound = v4Capability();
  assert.deepEqual(
    evaluateDesktopRouteAccess({
      match: routeMatch(),
      mode: 'cloud',
      permissions: new Set(['authenticated', 'tenant_member']),
      capability: unbound,
    }),
    {
      status: 'unavailable',
      reasonCode: 'desktop_route_capability_scope_mismatch',
      capability: unbound,
    },
  );

  const bound = v4Capability({
    scope: { ...nullScope, tenant_id: 'tenant-1' },
  });
  assert.equal(
    evaluateDesktopRouteAccess({
      match: routeMatch(),
      mode: 'cloud',
      permissions: new Set(['authenticated', 'tenant_member']),
      capability: bound,
    }).status,
    'allowed',
  );
});

test('workbench v4 marks transport authority observed and renderer declarations fail closed', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () =>
    new Response(
      JSON.stringify({
        service_version: '0.1.0',
        contract_version: '2.0.0',
        mode: 'keyword_degraded',
        reason_code: 'local_embeddings_unavailable',
        tenant_id: 'local',
        project_id: 'local-project',
        projection_revision: 21,
        backfill_cursor: null,
        supported_search_types: ['advanced', 'temporal', 'faceted'],
        unavailable_search_types: ['graph_traversal', 'community'],
      }),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );

  try {
    const client = createDesktopWorkbenchCapabilityClient(
      {
        getAutomationCapabilities: async () => ({
          service_version: '0.1.0',
          contract_version: '2.0.0',
          schema_version: 1,
          read: true,
          revision_guarded: true,
          idempotency_guarded: true,
          durable_execution: true,
          supported_read_trigger_kinds: ['manual', 'schedule', 'event'],
          create: { allowed: true },
          edit: { allowed: true },
          toggle: { allowed: true },
          run_now: { allowed: true },
          delete: { allowed: true },
        }),
      },
      {
        ...DEFAULT_CONFIG,
        mode: 'local',
        tenantId: 'local',
        projectId: 'local-project',
        workspaceId: 'local-workspace',
      },
    );
    const snapshot = await client.loadSnapshot();

    assert.equal(snapshot.version, '4.0.0');
    assert.deepEqual(
      {
        authority_source: snapshot.capabilities.search.authority_source,
        provenance: snapshot.capabilities.search.provenance,
        availability: snapshot.capabilities.search.availability,
      },
      {
        authority_source: 'sidecar',
        provenance: 'observed',
        availability: 'degraded',
      },
    );
    assert.deepEqual(
      {
        authority_source:
          snapshot.capabilities['tenant-tenant-tasks'].authority_source,
        provenance: snapshot.capabilities['tenant-tenant-tasks'].provenance,
        availability: snapshot.capabilities['tenant-tenant-tasks'].availability,
        reason_code: snapshot.capabilities['tenant-tenant-tasks'].reason_code,
        allowed_actions:
          snapshot.capabilities['tenant-tenant-tasks'].allowed_actions,
      },
      {
        authority_source: 'renderer',
        provenance: 'declared',
        availability: 'unavailable',
        reason_code: 'renderer_capability_authority_unobserved',
        allowed_actions: [],
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('v4 route readiness rejects callable placeholders before capability authority', () => {
  const implementedRouteIds = new Set(DESKTOP_IMPLEMENTED_ROUTE_IDS);
  const implementedLoaders = Object.fromEntries(
    DESKTOP_IMPLEMENTED_ROUTE_IDS.map((routeId) => [routeId, async () => null]),
  );
  const registry = createDesktopProductionRouteRegistry({
    implementedLoaders,
  });
  const implementedDefinitions = registry.definitions.filter(({ id }) =>
    implementedRouteIds.has(id),
  );
  const plannedDefinitions = registry.definitions.filter(
    ({ id }) => !implementedRouteIds.has(id),
  );

  assert.equal(implementedDefinitions.length, implementedRouteIds.size);
  assert.equal(plannedDefinitions.length, 0);

  for (const definition of implementedDefinitions) {
    const match = Object.freeze({
      definition,
      context: Object.freeze({}),
      canonicalPath: definition.path,
    });
    const permissions = new Set(definition.requiredPermission.flat());
    assert.deepEqual(definition.structuralReadiness, {
      status: 'unavailable',
      reasonCode: 'desktop_route_structural_loader_missing',
    });
    for (const capability of [
      v4Capability({ authority_source: 'renderer', provenance: 'declared' }),
      v4Capability({ authority_source: 'sidecar' }),
      v4Capability(),
    ]) {
      assert.deepEqual(
        evaluateDesktopRouteAccess({
          match,
          mode: 'cloud',
          permissions,
          capability,
        }),
        {
          status: 'unavailable',
          reasonCode: 'desktop_route_structural_loader_missing',
          capability: null,
        },
      );
    }
  }

  const missingBindings = createDesktopProductionRouteRegistry({
    implementedLoaders: {},
  });
  for (const definition of missingBindings.definitions.filter(({ id }) =>
    implementedRouteIds.has(id),
  )) {
    assert.deepEqual(definition.structuralReadiness, {
      status: 'unavailable',
      reasonCode: 'desktop_route_structural_app_binding_missing',
    });
  }
});

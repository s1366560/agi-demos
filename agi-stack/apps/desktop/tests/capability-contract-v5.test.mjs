import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  parseDesktopCapabilitySnapshot,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/capabilitySnapshot.js');
const {
  evaluateDesktopRouteAccess,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteHostModel.js');
const {
  createDesktopRouteRegistry,
  matchDesktopRoute,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js');

const nullScope = {
  tenant_id: null,
  project_id: null,
  workspace_id: null,
  instance_id: null,
};

function v5Capability(overrides = {}) {
  return {
    availability: 'available',
    reason_code: null,
    service_version: '0.1.0',
    contract_version: '3.0.0',
    allowed_actions: ['view'],
    scope: nullScope,
    authority_revision: 1,
    retryable: false,
    authority_source: 'cloud_service',
    supporting_authority_sources: ['electron'],
    provenance: 'observed',
    ...overrides,
  };
}

function routeMatch(localPolicy = 'native_equivalent') {
  const registry = createDesktopRouteRegistry([
    {
      id: 'tenant-overview',
      path: '/tenant/:tenantId/overview',
      scope: ['tenant'],
      navGroup: 'tenant-core',
      capability: 'tenant-tenant-overview',
      requiredPermission: [['authenticated', 'tenant_member']],
      localPolicy,
      loader: async () => ({ default: 'TenantOverview' }),
    },
  ]);
  const match = matchDesktopRoute(registry, '#/tenant/tenant-1/overview');
  assert.ok(match);
  return match;
}

test('v5 exposes exact runtime state plus explicit primary and supporting authority', () => {
  const capability = v5Capability();
  const snapshot = parseDesktopCapabilitySnapshot({
    version: '5.0.0',
    runtime_state: 'cloud',
    capabilities: { search: capability },
  });

  assert.equal(snapshot?.version, '5.0.0');
  assert.equal(snapshot?.runtime_state, 'cloud');
  assert.deepEqual(snapshot?.capabilities.search, capability);
  assert.equal(Object.hasOwn(snapshot ?? {}, 'mode'), false);
});

test('v5 rejects unsafe or ambiguous compound authority', () => {
  const parse = (entry, runtimeState = 'cloud') =>
    parseDesktopCapabilitySnapshot({
      version: '5.0.0',
      runtime_state: runtimeState,
      capabilities: { search: entry },
    });

  assert.equal(
    parse(v5Capability({ supporting_authority_sources: ['electron', 'electron'] })),
    null,
  );
  assert.equal(parse(v5Capability({ supporting_authority_sources: ['cloud_service'] })), null);
  assert.equal(parse(v5Capability({ supporting_authority_sources: ['renderer'] })), null);
  assert.equal(parse(v5Capability({ authority_source: 'sidecar' })), null);
  assert.equal(
    parse(
      v5Capability({
        availability: 'unavailable',
        reason_code: 'service_unavailable',
        allowed_actions: [],
        authority_revision: null,
      }),
    ),
    null,
  );
  assert.equal(
    parse(
      v5Capability({
        availability: 'not_applicable',
        reason_code: 'capability_not_applicable',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        authority_revision: null,
        retryable: true,
        supporting_authority_sources: [],
      }),
    ),
    null,
  );
});

test('v4 local input normalizes conservatively to local_offline v5', () => {
  const legacy = v5Capability({
    authority_source: 'sidecar',
  });
  delete legacy.retryable;
  delete legacy.supporting_authority_sources;
  const snapshot = parseDesktopCapabilitySnapshot({
    version: '4.0.0',
    mode: 'local',
    capabilities: { search: legacy },
  });

  assert.equal(snapshot?.version, '5.0.0');
  assert.equal(snapshot?.runtime_state, 'local_offline');
  assert.deepEqual(snapshot?.capabilities.search.supporting_authority_sources, []);
});

test('local_online cloud-only routes require Cloud primary authority', () => {
  const cloudCapability = v5Capability({
    scope: { ...nullScope, tenant_id: 'tenant-1' },
    supporting_authority_sources: ['sidecar', 'electron'],
  });
  const sidecarPrimary = {
    ...cloudCapability,
    authority_source: 'sidecar',
    supporting_authority_sources: ['cloud_service', 'electron'],
  };
  const input = {
    match: routeMatch('cloud_only'),
    permissions: new Set(['authenticated', 'tenant_member']),
  };

  assert.equal(
    evaluateDesktopRouteAccess({
      ...input,
      mode: 'local_online',
      capability: cloudCapability,
    }).status,
    'allowed',
  );
  assert.deepEqual(
    evaluateDesktopRouteAccess({
      ...input,
      mode: 'local_online',
      capability: sidecarPrimary,
    }),
    {
      status: 'unavailable',
      reasonCode: 'desktop_route_capability_authority_source_mismatch',
      capability: sidecarPrimary,
    },
  );
  assert.deepEqual(
    evaluateDesktopRouteAccess({
      ...input,
      mode: 'local_offline',
      capability: cloudCapability,
    }),
    {
      status: 'unavailable',
      reasonCode: 'desktop_route_local_cloud_only',
      capability: null,
    },
  );
});

test('supporting authority never satisfies the primary route gate', () => {
  const capability = v5Capability({
    scope: { ...nullScope, tenant_id: 'tenant-1' },
    authority_source: 'cloud_service',
    supporting_authority_sources: ['sidecar', 'electron'],
  });

  assert.deepEqual(
    evaluateDesktopRouteAccess({
      match: routeMatch(),
      mode: 'local_offline',
      permissions: new Set(['authenticated', 'tenant_member']),
      capability,
    }),
    {
      status: 'unavailable',
      reasonCode: 'desktop_route_capability_authority_source_mismatch',
      capability,
    },
  );
});

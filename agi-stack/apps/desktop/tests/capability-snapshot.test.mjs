import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  desktopCapability,
  parseDesktopCapabilitySnapshot,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime/capabilitySnapshot.js');
const fixture = JSON.parse(
  readFileSync(
    new URL(
      '../contracts/desktop-web-parity/fixtures/capability-snapshot.v2.json',
      import.meta.url,
    ),
    'utf8',
  ),
);

const nullScope = {
  tenant_id: null,
  project_id: null,
  workspace_id: null,
  instance_id: null,
};

function declaredExpected(capability) {
  return {
    ...capability,
    retryable: false,
    authority_source: 'renderer',
    supporting_authority_sources: [],
    provenance: 'declared',
  };
}

test('DesktopCapabilitySnapshot v2 normalizes read-only input into declared v5', () => {
  const snapshot = parseDesktopCapabilitySnapshot(fixture.input.snapshot);
  assert.equal(snapshot?.version, '5.0.0');
  assert.deepEqual(
    desktopCapability(snapshot, 'project-project-overview'),
    declaredExpected({
      availability: 'unavailable',
      reason_code: 'capability_not_declared',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: nullScope,
      authority_revision: null,
      status: 'unavailable',
      available: false,
    }),
  );
  assert.deepEqual(
    desktopCapability(snapshot, 'project-project-search'),
    declaredExpected({
      availability: 'unavailable',
      reason_code: 'capability_not_declared',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: nullScope,
      authority_revision: null,
      status: 'unavailable',
      available: false,
    }),
  );
  assert.deepEqual(
    desktopCapability(snapshot, 'sandbox_isolation'),
    declaredExpected({
      availability: 'not_applicable',
      reason_code: 'local_isolation_not_applicable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: nullScope,
      authority_revision: null,
      status: 'not_applicable',
      available: false,
    }),
  );
  assert.deepEqual(
    desktopCapability(snapshot, 'search'),
    declaredExpected({
      availability: 'degraded',
      reason_code: 'local_search_keyword_only',
      service_version: '0.1.0',
      contract_version: '2.0.0',
      allowed_actions: [],
      scope: nullScope,
      authority_revision: null,
      status: 'degraded',
      available: false,
    }),
  );
  assert.deepEqual(
    desktopCapability(snapshot, 'workspace_collaboration'),
    declaredExpected({
      availability: 'unavailable',
      reason_code: 'local_workspace_collaboration_unavailable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: nullScope,
      authority_revision: null,
      status: 'unavailable',
      available: false,
    }),
  );
});

test('DesktopCapabilitySnapshot closes missing capabilities and rejects unsafe fields', () => {
  const missing = structuredClone(fixture.input.snapshot);
  delete missing.capabilities.search;
  assert.deepEqual(
    parseDesktopCapabilitySnapshot(missing)?.capabilities.search,
    declaredExpected({
      availability: 'unavailable',
      reason_code: 'capability_not_declared',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: nullScope,
      authority_revision: null,
    }),
  );

  const extra = structuredClone(fixture.input.snapshot);
  extra.capabilities.search.hint = 'guess from a 404';
  assert.equal(parseDesktopCapabilitySnapshot(extra), null);

  const inconsistent = structuredClone(fixture.input.snapshot);
  inconsistent.capabilities.search.status = 'available';
  assert.equal(parseDesktopCapabilitySnapshot(inconsistent), null);

  assert.deepEqual(
    desktopCapability(null, 'search'),
    declaredExpected({
      availability: 'unavailable',
      reason_code: 'capability_snapshot_unavailable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: nullScope,
      authority_revision: null,
      status: 'unavailable',
      available: false,
    }),
  );
});

test('DesktopCapabilitySnapshot resolves route capability strings without inventing authority', () => {
  const snapshot = parseDesktopCapabilitySnapshot({
    version: '3.0.0',
    mode: 'local',
    capabilities: {
      'tenant-tenant-overview': {
        availability: 'degraded',
        reason_code: 'local_tenant_overview_memory_projection_unavailable',
        service_version: '0.1.0',
        contract_version: '3.0.0',
        allowed_actions: ['view'],
        scope: {
          tenant_id: 'tenant-1',
          project_id: null,
          workspace_id: null,
          instance_id: null,
        },
        authority_revision: 9,
      },
      'tenant-tenant-pool': {
        availability: 'not_applicable',
        reason_code: 'cloud_runtime_pool_not_applicable',
        service_version: null,
        contract_version: null,
        allowed_actions: [],
        scope: {
          tenant_id: 'tenant-1',
          project_id: null,
          workspace_id: null,
          instance_id: null,
        },
        authority_revision: null,
      },
      'project-project-overview': {
        availability: 'degraded',
        reason_code: 'local_project_overview_timeline_projection_only',
        service_version: '0.1.0',
        contract_version: '3.0.0',
        allowed_actions: ['view'],
        scope: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          workspace_id: null,
          instance_id: null,
        },
        authority_revision: 7,
      },
    },
  });

  assert.deepEqual(
    desktopCapability(snapshot, 'project-project-overview'),
    declaredExpected({
      availability: 'degraded',
      reason_code: 'local_project_overview_timeline_projection_only',
      service_version: '0.1.0',
      contract_version: '3.0.0',
      allowed_actions: ['view'],
      scope: {
        tenant_id: 'tenant-1',
        project_id: 'project-1',
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: 7,
      status: 'degraded',
      available: false,
    }),
  );
  assert.deepEqual(
    desktopCapability(snapshot, 'tenant-tenant-overview'),
    declaredExpected({
      availability: 'degraded',
      reason_code: 'local_tenant_overview_memory_projection_unavailable',
      service_version: '0.1.0',
      contract_version: '3.0.0',
      allowed_actions: ['view'],
      scope: {
        tenant_id: 'tenant-1',
        project_id: null,
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: 9,
      status: 'degraded',
      available: false,
    }),
  );
  assert.deepEqual(
    desktopCapability(snapshot, 'tenant-tenant-pool'),
    declaredExpected({
      availability: 'not_applicable',
      reason_code: 'cloud_runtime_pool_not_applicable',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: {
        tenant_id: 'tenant-1',
        project_id: null,
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: null,
      status: 'not_applicable',
      available: false,
    }),
  );
  assert.deepEqual(
    desktopCapability(snapshot, 'project-project-graph'),
    declaredExpected({
      availability: 'unavailable',
      reason_code: 'capability_not_declared',
      service_version: null,
      contract_version: null,
      allowed_actions: [],
      scope: nullScope,
      authority_revision: null,
      status: 'unavailable',
      available: false,
    }),
  );
});

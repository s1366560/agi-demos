import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  createProjectSearchRouteBindingProviderV2,
  ProjectSearchRouteBindingProviderErrorV2,
} from '/tmp/agistack-desktop-test-dist/src/features/search/projectSearchRouteBindingProviderV2.js';

const tenantId = 'tenant-1';
const projectId = 'project-1';

function capabilityEntry(overrides = {}) {
  return Object.freeze({
    availability: 'available',
    reason_code: null,
    service_version: '2.0.0',
    contract_version: '5.0.0',
    allowed_actions: Object.freeze(['search']),
    scope: Object.freeze({
      tenant_id: tenantId,
      project_id: projectId,
      workspace_id: null,
      instance_id: null,
    }),
    authority_revision: 7,
    retryable: false,
    authority_source: 'sidecar',
    supporting_authority_sources: Object.freeze(['sidecar']),
    provenance: 'observed',
    ...overrides,
  });
}

function capabilitySnapshot(entry = capabilityEntry()) {
  return Object.freeze({
    version: '5.0.0',
    runtime_state: 'local_online',
    capabilities: Object.freeze({
      'project-project-search': entry,
    }),
  });
}

function input(overrides = {}) {
  const api = Object.freeze({
    async searchProject() {
      return Object.freeze({ results: Object.freeze([]) });
    },
  });
  return {
    api,
    scope: Object.freeze({ tenantId, projectId }),
    projects: Object.freeze([
      Object.freeze({ id: projectId, tenant_id: 'tenant-other', name: 'Wrong tenant' }),
      Object.freeze({ id: projectId, tenant_id: tenantId, name: 'Project One' }),
    ]),
    capabilitySnapshot: capabilitySnapshot(),
    capabilityLoading: false,
    onRetryCapability: () => undefined,
    ...overrides,
  };
}

function providerError(reasonCode) {
  return (error) => {
    assert.equal(error instanceof ProjectSearchRouteBindingProviderErrorV2, true);
    assert.equal(error.reasonCode, reasonCode);
    assert.equal(error.message, reasonCode);
    return true;
  };
}

test('project search binding provider fails closed before a publication exists', () => {
  const provider = createProjectSearchRouteBindingProviderV2();

  assert.throws(
    () => provider.resolve({ tenantId, projectId }),
    providerError('project_search_route_binding_unpublished'),
  );
});

test('project search binding provider resolves one frozen exact-scope publication', () => {
  const provider = createProjectSearchRouteBindingProviderV2();
  const current = input();
  provider.publish(current);

  const binding = provider.resolve({ tenantId, projectId });

  assert.equal(Object.isFrozen(binding), true);
  assert.equal(Object.isFrozen(binding.scope), true);
  assert.equal(Object.isFrozen(binding.capability), true);
  assert.equal(binding.api, current.api);
  assert.deepEqual(binding.scope, { tenantId, projectId });
  assert.equal(binding.projectName, 'Project One');
  assert.equal(binding.capability.availability, 'available');
  assert.equal(binding.capability.status, 'available');
  assert.equal(binding.capability.available, true);
  assert.equal(binding.capabilityLoading, false);
  assert.equal(binding.onRetryCapability, current.onRetryCapability);
});

test('project search binding provider rejects a mismatched scope without exposing authority', () => {
  const provider = createProjectSearchRouteBindingProviderV2();
  provider.publish(input());

  assert.throws(
    () => provider.resolve({ tenantId, projectId: 'project-other' }),
    providerError('project_search_route_binding_scope_mismatch'),
  );
  assert.throws(
    () => provider.resolve({ tenantId: 'tenant-other', projectId }),
    providerError('project_search_route_binding_scope_mismatch'),
  );
});

test('republishing a new scope invalidates the previous project binding', () => {
  const provider = createProjectSearchRouteBindingProviderV2();
  provider.publish(input());
  const nextApi = Object.freeze({
    async searchProject() {
      return Object.freeze({ results: Object.freeze([]) });
    },
  });
  provider.publish(
    input({
      api: nextApi,
      scope: Object.freeze({ tenantId: 'tenant-2', projectId: 'project-2' }),
      projects: Object.freeze([]),
    }),
  );

  assert.throws(
    () => provider.resolve({ tenantId, projectId }),
    providerError('project_search_route_binding_scope_mismatch'),
  );
  const nextBinding = provider.resolve({ tenantId: 'tenant-2', projectId: 'project-2' });
  assert.equal(nextBinding.api, nextApi);
  assert.equal(nextBinding.projectName, 'project-2');
});

test('capability loading and unavailable evidence propagate without fallback synthesis', () => {
  const provider = createProjectSearchRouteBindingProviderV2();
  provider.publish(
    input({
      capabilitySnapshot: capabilitySnapshot(
        capabilityEntry({
          availability: 'unavailable',
          reason_code: 'sidecar_offline',
          authority_revision: null,
          retryable: true,
        }),
      ),
      capabilityLoading: true,
    }),
  );

  const binding = provider.resolve({ tenantId, projectId });
  assert.equal(binding.capabilityLoading, true);
  assert.equal(binding.capability.availability, 'unavailable');
  assert.equal(binding.capability.reason_code, 'sidecar_offline');
  assert.equal(binding.capability.available, false);
});

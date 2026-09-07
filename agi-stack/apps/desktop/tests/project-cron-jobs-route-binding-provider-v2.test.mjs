import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  createProjectCronJobsRouteBindingProviderV2,
  ProjectCronJobsRouteBindingProviderErrorV2,
} from '/tmp/agistack-desktop-test-dist/src/features/automations/projectCronJobsRouteBindingProviderV2.js';

const tenantId = 'tenant-1';
const projectId = 'project-1';

function capabilityEntry(overrides = {}) {
  return Object.freeze({
    availability: 'available',
    reason_code: null,
    service_version: '2.0.0',
    contract_version: '5.0.0',
    allowed_actions: Object.freeze(['run']),
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
    capabilities: Object.freeze({ automation_run: entry }),
  });
}

function input(overrides = {}) {
  const api = Object.freeze({});
  return {
    api,
    scope: Object.freeze({ tenantId, projectId }),
    projects: Object.freeze([
      Object.freeze({ id: projectId, tenant_id: 'tenant-other', name: 'Wrong tenant' }),
      Object.freeze({ id: projectId, tenant_id: tenantId, name: 'Project One' }),
    ]),
    capabilitySnapshot: capabilitySnapshot(),
    onOpenProjectSettings: () => undefined,
    onOpenConnection: () => undefined,
    ...overrides,
  };
}

function providerError(reasonCode) {
  return (error) => {
    assert.equal(error instanceof ProjectCronJobsRouteBindingProviderErrorV2, true);
    assert.equal(error.reasonCode, reasonCode);
    assert.equal(error.message, reasonCode);
    return true;
  };
}

test('cron jobs binding provider fails closed before a publication exists', () => {
  const provider = createProjectCronJobsRouteBindingProviderV2();

  assert.throws(
    () => provider.resolve({ tenantId, projectId }),
    providerError('project_cron_jobs_route_binding_unpublished'),
  );
});

test('cron jobs binding provider resolves one frozen exact-scope publication', () => {
  const provider = createProjectCronJobsRouteBindingProviderV2();
  const current = input();
  provider.publish(current);

  const binding = provider.resolve({ tenantId, projectId });

  assert.equal(Object.isFrozen(binding), true);
  assert.equal(Object.isFrozen(binding.scope), true);
  assert.equal(Object.isFrozen(binding.runCapability), true);
  assert.equal(binding.api, current.api);
  assert.deepEqual(binding.scope, { tenantId, projectId });
  assert.equal(binding.projectName, 'Project One');
  assert.equal(binding.runCapability.availability, 'available');
  assert.equal(binding.runCapability.status, 'available');
  assert.equal(binding.runCapability.available, true);
  assert.equal(binding.onOpenProjectSettings, current.onOpenProjectSettings);
  assert.equal(binding.onOpenConnection, current.onOpenConnection);
});

test('cron jobs binding provider rejects scope drift without exposing authority', () => {
  const provider = createProjectCronJobsRouteBindingProviderV2();
  provider.publish(input());

  assert.throws(
    () => provider.resolve({ tenantId, projectId: 'project-other' }),
    providerError('project_cron_jobs_route_binding_scope_mismatch'),
  );
  assert.throws(
    () => provider.resolve({ tenantId: 'tenant-other', projectId }),
    providerError('project_cron_jobs_route_binding_scope_mismatch'),
  );
});

test('republishing a new scope invalidates the previous cron jobs binding', () => {
  const provider = createProjectCronJobsRouteBindingProviderV2();
  provider.publish(input());
  const nextApi = Object.freeze({});
  provider.publish(
    input({
      api: nextApi,
      scope: Object.freeze({ tenantId: 'tenant-2', projectId: 'project-2' }),
      projects: Object.freeze([]),
    }),
  );

  assert.throws(
    () => provider.resolve({ tenantId, projectId }),
    providerError('project_cron_jobs_route_binding_scope_mismatch'),
  );
  const nextBinding = provider.resolve({ tenantId: 'tenant-2', projectId: 'project-2' });
  assert.equal(nextBinding.api, nextApi);
  assert.equal(nextBinding.projectName, 'project-2');
});

test('unavailable automation evidence propagates without fallback synthesis', () => {
  const provider = createProjectCronJobsRouteBindingProviderV2();
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
    }),
  );

  const binding = provider.resolve({ tenantId, projectId });
  assert.equal(binding.runCapability.availability, 'unavailable');
  assert.equal(binding.runCapability.reason_code, 'sidecar_offline');
  assert.equal(binding.runCapability.available, false);
});

test('cron jobs bindings publish only detached workspace conversations from the exact scope', () => {
  const provider = createProjectCronJobsRouteBindingProviderV2();
  const conversation = { id: 'conversation', title: 'Review', tenant_id: tenantId,
    project_id: projectId, workspace_id: 'workspace' };
  provider.publish(input({ conversations: [conversation,
    { ...conversation, id: 'other', tenant_id: 'other' },
    { ...conversation, id: 'no-workspace', workspace_id: null },
  ] }));
  conversation.title = 'Changed';
  const binding = provider.resolve({ tenantId, projectId });
  assert.deepEqual(binding.conversations, [
    { id: 'conversation', title: 'Review', workspaceId: 'workspace' },
  ]);
  assert.ok(Object.isFrozen(binding.conversations));
  assert.ok(Object.isFrozen(binding.conversations[0]));
});

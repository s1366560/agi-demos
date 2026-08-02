import assert from 'node:assert/strict';
import { test } from 'node:test';

const { unifiedRuntimesCapability } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/unified-runtimes/unifiedRuntimesCapability.js'
);

function runtimeConfig(mode, overrides = {}) {
  return {
    mode,
    apiBaseUrl: 'https://api.example.test',
    deviceAuthorizationBaseUrl: 'https://api.example.test',
    apiKey: 'test-token',
    localApiToken: 'local-token',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

test('Unified Runtimes declares tenant-scoped Cloud degradation and Local native projection', () => {
  const cloud = unifiedRuntimesCapability(runtimeConfig('cloud'));
  assert.equal(cloud.availability, 'degraded');
  assert.equal(cloud.reason_code, 'global_pool_capacity_not_available_in_tenant_scope');
  assert.ok(cloud.allowed_actions.includes('inspect-pool'));
  assert.ok(cloud.allowed_actions.includes('inspect-sandbox'));
  assert.equal(cloud.scope.tenant_id, 'tenant-1');

  const local = unifiedRuntimesCapability(runtimeConfig('local'));
  assert.equal(local.availability, 'degraded');
  assert.equal(local.reason_code, 'local_pool_not_applicable_sidecar_projection');
  assert.deepEqual(local.allowed_actions, [
    'view',
    'refresh',
    'inspect-sidecar',
    'inspect-sandbox-capabilities',
  ]);
  assert.equal(local.scope.tenant_id, 'tenant-1');
  assert.equal(local.scope.project_id, 'project-1');
});

test('Unified Runtimes fails closed when its tenant or Local project scope is absent', () => {
  const cloud = unifiedRuntimesCapability(runtimeConfig('cloud', { tenantId: '' }));
  assert.equal(cloud.availability, 'unavailable');
  assert.equal(cloud.reason_code, 'unified_runtimes_tenant_scope_unavailable');

  const local = unifiedRuntimesCapability(runtimeConfig('local', { projectId: '' }));
  assert.equal(local.availability, 'unavailable');
  assert.equal(local.reason_code, 'unified_runtimes_project_scope_unavailable');
});

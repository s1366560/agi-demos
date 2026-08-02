import assert from 'node:assert/strict';
import { test } from 'node:test';

const { runtimeInstancesCapability } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/runtime-instances/runtimeInstancesCapability.js'
);

function config(mode, tenantId = 'tenant-1') {
  return {
    mode,
    apiBaseUrl: 'https://api.example.test',
    deviceAuthorizationBaseUrl: 'https://api.example.test',
    apiKey: 'token',
    localApiToken: 'local-token',
    tenantId,
    projectId: 'project-1',
    workspaceId: 'workspace-1',
    workspaceRoot: '/workspace',
  };
}

test('Runtime Instances capability declares honest Cloud and Local partial actions', () => {
  const cloud = runtimeInstancesCapability(config('cloud'));
  assert.equal(cloud.availability, 'degraded');
  assert.equal(cloud.reason_code, 'runtime_instances_nested_routes_partial');
  assert.ok(cloud.allowed_actions.includes('restart'));
  assert.ok(cloud.allowed_actions.includes('delete'));
  assert.equal(cloud.allowed_actions.includes('create'), false);

  const local = runtimeInstancesCapability(config('local'));
  assert.equal(local.availability, 'degraded');
  assert.equal(local.reason_code, 'local_instance_sidecar_projection_partial');
  assert.deepEqual(local.allowed_actions, [
    'view',
    'list',
    'refresh',
    'search',
    'filter-status',
  ]);
  assert.equal(local.scope.tenant_id, 'tenant-1');
});
test('Runtime Instances capability fails closed without a tenant scope', () => {
  const result = runtimeInstancesCapability(config('cloud', ''));
  assert.equal(result.availability, 'unavailable');
  assert.equal(result.reason_code, 'runtime_instances_tenant_scope_unavailable');
  assert.deepEqual(result.allowed_actions, []);
});

import assert from 'node:assert/strict';
import { test } from 'node:test';

const { runtimeDeploymentsCapability } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/runtime-deployments/runtimeDeploymentsCapability.js'
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

test('Runtime Deployments capability declares the safe Cloud read and progress slice', () => {
  const cloud = runtimeDeploymentsCapability(config('cloud'));
  assert.equal(cloud.availability, 'degraded');
  assert.equal(
    cloud.reason_code,
    'runtime_deployments_mutations_and_instance_discovery_partial',
  );
  assert.deepEqual(cloud.allowed_actions, [
    'view',
    'list',
    'refresh',
    'paginate',
    'inspect-progress',
    'reconnect-progress',
  ]);
  assert.equal(cloud.allowed_actions.includes('create'), false);
  assert.equal(cloud.allowed_actions.includes('cancel'), false);
  assert.equal(cloud.allowed_actions.includes('mark-success'), false);
  assert.equal(cloud.allowed_actions.includes('mark-failed'), false);
});

test('Runtime Deployments capability keeps Local structurally cloud-only', () => {
  const local = runtimeDeploymentsCapability(config('local'));
  assert.equal(local.availability, 'not_applicable');
  assert.equal(
    local.reason_code,
    'cloud_deployment_authority_not_applicable',
  );
  assert.deepEqual(local.allowed_actions, []);
  assert.equal(local.scope.tenant_id, 'tenant-1');
});

test('Runtime Deployments capability fails closed without tenant scope', () => {
  const result = runtimeDeploymentsCapability(config('cloud', ''));
  assert.equal(result.availability, 'unavailable');
  assert.equal(
    result.reason_code,
    'runtime_deployments_tenant_scope_unavailable',
  );
  assert.deepEqual(result.allowed_actions, []);
});

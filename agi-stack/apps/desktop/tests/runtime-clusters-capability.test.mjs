import assert from 'node:assert/strict';
import { test } from 'node:test';

const { runtimeClustersCapability } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/runtime-clusters/runtimeClustersCapability.js'
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

test('Runtime Clusters capability declares a safe partial Cloud slice', () => {
  const cloud = runtimeClustersCapability(config('cloud'));
  assert.equal(cloud.availability, 'degraded');
  assert.equal(cloud.reason_code, 'runtime_clusters_detail_and_mutations_partial');
  assert.deepEqual(cloud.allowed_actions, [
    'view',
    'list',
    'refresh',
    'search-current-page',
    'filter-status-current-page',
    'paginate',
    'inspect-health',
  ]);
  assert.equal(cloud.allowed_actions.includes('create-registration-token'), false);
});

test('Runtime Clusters capability keeps Local structurally cloud-only', () => {
  const local = runtimeClustersCapability(config('local'));
  assert.equal(local.availability, 'not_applicable');
  assert.equal(local.reason_code, 'cloud_cluster_control_not_applicable');
  assert.deepEqual(local.allowed_actions, []);
  assert.equal(local.scope.tenant_id, 'tenant-1');
});

test('Runtime Clusters capability fails closed without tenant scope', () => {
  const result = runtimeClustersCapability(config('cloud', ''));
  assert.equal(result.availability, 'unavailable');
  assert.equal(result.reason_code, 'runtime_clusters_tenant_scope_unavailable');
  assert.deepEqual(result.allowed_actions, []);
});

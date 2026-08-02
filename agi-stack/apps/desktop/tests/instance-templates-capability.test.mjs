import assert from 'node:assert/strict';
import { test } from 'node:test';

const { instanceTemplatesCapability } = await import(
  '/tmp/agistack-desktop-test-dist/src/features/instance-templates/instanceTemplatesCapability.js'
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

test('Instance Templates capability declares the native Cloud lifecycle slice', () => {
  const cloud = instanceTemplatesCapability(config('cloud'));
  assert.equal(cloud.availability, 'degraded');
  assert.equal(
    cloud.reason_code,
    'instance_templates_nested_deep_link_and_deploy_partial',
  );
  assert.deepEqual(cloud.allowed_actions, [
    'view',
    'list',
    'list-items',
    'create',
    'delete',
    'publish',
    'clone',
    'refresh',
    'paginate',
    'search-current-page',
    'filter-status',
  ]);
  assert.equal(cloud.allowed_actions.includes('deploy-from-template'), false);
});

test('Instance Templates capability keeps Local explicitly unavailable without network authority', () => {
  const local = instanceTemplatesCapability(config('local'));
  assert.equal(local.availability, 'unavailable');
  assert.equal(
    local.reason_code,
    'local_instance_template_authority_unavailable',
  );
  assert.deepEqual(local.allowed_actions, []);
  assert.equal(local.scope.tenant_id, 'tenant-1');
});

test('Instance Templates capability fails closed without tenant scope', () => {
  const result = instanceTemplatesCapability(config('cloud', ''));
  assert.equal(result.availability, 'unavailable');
  assert.equal(
    result.reason_code,
    'instance_templates_tenant_scope_unavailable',
  );
  assert.deepEqual(result.allowed_actions, []);
});

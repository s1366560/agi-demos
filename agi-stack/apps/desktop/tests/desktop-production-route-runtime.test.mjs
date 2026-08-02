import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createProjectOverviewRouteBindingForRuntime,
  createRuntimeClustersRouteBindingForRuntime,
  createRuntimeInstancesRouteBindingForRuntime,
  createRuntimePoolRouteBindingForRuntime,
  createUnifiedRuntimesRouteBindingForRuntime,
  desktopRouteBasePermissionsForAuth,
  desktopRoutePermissionsForContext,
  resolveDesktopRouteCapability,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRuntime.js'
);

const tenantId = 'tenant-1';
const projectId = 'project-1';
const routeContext = Object.freeze({ tenantId, projectId });

test('permission projection requires authenticated exact catalog membership', () => {
  const signedOut = authState({
    status: 'signed_out',
    credentialKind: null,
    user: null,
    tenants: [{ id: tenantId }],
    projects: [{ id: projectId, tenant_id: tenantId }],
  });
  assert.deepEqual(
    [...desktopRoutePermissionsForContext(signedOut, routeContext)],
    [],
  );

  const authenticated = authState();
  assert.deepEqual(
    [...desktopRoutePermissionsForContext(authenticated, routeContext)],
    ['authenticated'],
  );

  const tenantMember = authState({
    tenants: [{ id: tenantId }],
  });
  assert.deepEqual(
    [...desktopRoutePermissionsForContext(tenantMember, routeContext)],
    ['authenticated', 'tenant_member'],
  );

  const projectMember = authState({
    tenants: [{ id: tenantId }],
    projects: [{ id: projectId, tenant_id: tenantId }],
  });
  assert.deepEqual(
    [...desktopRoutePermissionsForContext(projectMember, routeContext)],
    ['authenticated', 'tenant_member', 'project_member'],
  );
});

test('base permission projection carries only authenticated route preflight authority', () => {
  assert.deepEqual(
    [...desktopRouteBasePermissionsForAuth(authState())],
    ['authenticated'],
  );
  assert.deepEqual(
    [
      ...desktopRouteBasePermissionsForAuth(
        authState({
          tenants: [{ id: tenantId }],
          projects: [{ id: projectId, tenant_id: tenantId }],
        }),
      ),
    ],
    ['authenticated'],
  );
});

test('permission projection never trims identifiers or interprets role text', () => {
  const misleadingAuth = authState({
    user: {
      ...currentUser(),
      roles: ['owner', 'admin', 'tenant_member', 'project_member'],
    },
    tenants: [{ id: ` ${tenantId}` }, { id: 'tenant-other' }],
    projects: [
      { id: projectId, tenant_id: 'tenant-other' },
      { id: `${projectId} `, tenant_id: tenantId },
    ],
  });

  assert.deepEqual(
    [...desktopRoutePermissionsForContext(misleadingAuth, routeContext)],
    ['authenticated'],
  );
  assert.deepEqual(
    [
      ...desktopRoutePermissionsForContext(
        authState({
          tenants: [{ id: tenantId }],
          projects: [{ id: 'project-other', tenant_id: tenantId }],
        }),
        routeContext,
      ),
    ],
    ['authenticated', 'tenant_member'],
  );
});

test('capability resolution returns only the exact own snapshot entry', () => {
  const entry = capabilityEntry();
  const snapshot = capabilitySnapshot({
    'project-project-overview': entry,
  });

  assert.equal(
    resolveDesktopRouteCapability(
      snapshot,
      'project-project-overview',
      Object.freeze({ tenantId: 'tenant-other', projectId: 'project-other' }),
    ),
    entry,
  );
  assert.equal(
    resolveDesktopRouteCapability(snapshot, 'missing-capability', routeContext),
    null,
  );
  assert.equal(
    resolveDesktopRouteCapability(null, 'project-project-overview', routeContext),
    null,
  );

  const inheritedCapabilities = Object.create({
    'project-project-overview': entry,
  });
  assert.equal(
    resolveDesktopRouteCapability(
      capabilitySnapshot(inheritedCapabilities),
      'project-project-overview',
      routeContext,
    ),
    null,
  );
});

test('cloud project overview binding constructs only cloud authority', () => {
  const calls = [];
  const cloudClient = Object.freeze({ kind: 'cloud-client' });
  const controller = Object.freeze({ kind: 'controller' });
  const config = runtimeConfig('cloud');

  const binding = createProjectOverviewRouteBindingForRuntime(
    config,
    routeContext,
    {
      createCloudClient(receivedConfig) {
        calls.push(['cloud', receivedConfig]);
        return cloudClient;
      },
      createLocalClient() {
        calls.push(['local']);
        throw new Error('local adapter must not be constructed');
      },
      createController(options) {
        calls.push(['controller', options]);
        return controller;
      },
    },
  );

  assert.equal(binding.controller, controller);
  assert.deepEqual(binding.scope, {
    authority: 'cloud',
    tenantId,
    projectId,
  });
  assert.deepEqual(calls, [
    ['cloud', config],
    [
      'controller',
      {
        authority: 'cloud',
        cloudClient,
        initialScope: binding.scope,
      },
    ],
  ]);
});

test('local project overview binding constructs only local authority', () => {
  const calls = [];
  const localClient = Object.freeze({ kind: 'local-client' });
  const controller = Object.freeze({ kind: 'controller' });
  const config = runtimeConfig('local');

  const binding = createProjectOverviewRouteBindingForRuntime(
    config,
    routeContext,
    {
      createCloudClient() {
        calls.push(['cloud']);
        throw new Error('cloud adapter must not be constructed');
      },
      createLocalClient(receivedConfig) {
        calls.push(['local', receivedConfig]);
        return localClient;
      },
      createController(options) {
        calls.push(['controller', options]);
        return controller;
      },
    },
  );

  assert.equal(binding.controller, controller);
  assert.deepEqual(binding.scope, {
    authority: 'local',
    tenantId,
    projectId,
  });
  assert.deepEqual(calls, [
    ['local', config],
    [
      'controller',
      {
        authority: 'local',
        localClient,
        initialScope: binding.scope,
      },
    ],
  ]);
});

test('project overview scope mismatch fails before constructing any authority', () => {
  for (const [config, context] of [
    [runtimeConfig('cloud', { tenantId: 'tenant-other' }), routeContext],
    [runtimeConfig('cloud', { projectId: 'project-other' }), routeContext],
    [runtimeConfig('local'), { tenantId: ` ${tenantId}`, projectId }],
    [runtimeConfig('local'), { tenantId, projectId: `${projectId} ` }],
  ]) {
    const calls = [];
    assert.throws(
      () =>
        createProjectOverviewRouteBindingForRuntime(config, context, {
          createCloudClient() {
            calls.push('cloud');
            return {};
          },
          createLocalClient() {
            calls.push('local');
            return {};
          },
          createController() {
            calls.push('controller');
            return {};
          },
        }),
      /project_overview_runtime_scope_mismatch/u,
    );
    assert.deepEqual(calls, []);
  }
});

test('Runtime Pool binding preserves exact Cloud and Local tenant authority', async () => {
  const cloud = createRuntimePoolRouteBindingForRuntime(
    runtimeConfig('cloud'),
    { tenantId },
  );
  assert.deepEqual(cloud.scope, { authority: 'cloud', tenantId });
  assert.equal(cloud.controller.getSnapshot().authority, 'cloud');

  const local = createRuntimePoolRouteBindingForRuntime(
    runtimeConfig('local'),
    { tenantId },
  );
  assert.deepEqual(local.scope, { authority: 'local', tenantId });
  await local.controller.load(local.scope);
  assert.equal(local.controller.getSnapshot().statusState, 'unavailable');
  assert.equal(
    local.controller.getSnapshot().statusReasonCode,
    'cloud_runtime_pool_not_applicable',
  );
});

test('Runtime Pool binding rejects tenant scope drift before client authority', () => {
  assert.throws(
    () =>
      createRuntimePoolRouteBindingForRuntime(runtimeConfig('cloud'), {
        tenantId: 'tenant-other',
      }),
    /runtime_pool_runtime_scope_mismatch/u,
  );
});

test('Runtime Instances binding preserves exact Cloud and Local tenant authority', () => {
  const cloud = createRuntimeInstancesRouteBindingForRuntime(
    runtimeConfig('cloud'),
    { tenantId },
  );
  assert.deepEqual(cloud.scope, { authority: 'cloud', tenantId });
  assert.equal(cloud.controller.getSnapshot().authority, 'cloud');

  const local = createRuntimeInstancesRouteBindingForRuntime(
    runtimeConfig('local'),
    { tenantId },
  );
  assert.deepEqual(local.scope, { authority: 'local', tenantId });
  assert.equal(local.controller.getSnapshot().authority, 'local');
});

test('Runtime Instances binding rejects tenant scope drift before client authority', () => {
  assert.throws(
    () =>
      createRuntimeInstancesRouteBindingForRuntime(runtimeConfig('cloud'), {
        tenantId: 'tenant-other',
      }),
    /runtime_instances_runtime_scope_mismatch/u,
  );
});

test('Runtime Clusters binding preserves Cloud and Local tenant authority', async () => {
  const cloud = createRuntimeClustersRouteBindingForRuntime(
    runtimeConfig('cloud'),
    { tenantId },
  );
  assert.deepEqual(cloud.scope, { authority: 'cloud', tenantId });
  assert.equal(cloud.controller.getSnapshot().authority, 'cloud');

  const local = createRuntimeClustersRouteBindingForRuntime(
    runtimeConfig('local'),
    { tenantId },
  );
  assert.deepEqual(local.scope, { authority: 'local', tenantId });
  await local.controller.load(local.scope);
  assert.equal(local.controller.getSnapshot().state, 'unavailable');
  assert.equal(
    local.controller.getSnapshot().reasonCode,
    'cloud_cluster_control_not_applicable',
  );
});

test('Runtime Clusters binding rejects tenant scope drift before client authority', () => {
  assert.throws(
    () =>
      createRuntimeClustersRouteBindingForRuntime(runtimeConfig('cloud'), {
        tenantId: 'tenant-other',
      }),
    /runtime_clusters_runtime_scope_mismatch/u,
  );
});

test('Unified Runtimes binding preserves exact Cloud and Local scope authority', async () => {
  const cloud = createUnifiedRuntimesRouteBindingForRuntime(
    runtimeConfig('cloud'),
    { tenantId },
  );
  assert.deepEqual(cloud.scope, {
    authority: 'cloud',
    tenantId,
    projectId,
  });
  assert.equal(cloud.controller.getSnapshot().authority, 'cloud');

  const local = createUnifiedRuntimesRouteBindingForRuntime(
    runtimeConfig('local'),
    { tenantId },
  );
  assert.deepEqual(local.scope, {
    authority: 'local',
    tenantId,
    projectId,
  });
  await local.controller.load(local.scope);
  assert.equal(local.controller.getSnapshot().authority, 'local');
  assert.equal(
    local.controller.getSnapshot().poolReasonCode,
    'local_pool_not_applicable_sidecar_projection',
  );
});

test('Unified Runtimes binding rejects tenant and project scope drift', () => {
  assert.throws(
    () =>
      createUnifiedRuntimesRouteBindingForRuntime(
        runtimeConfig('cloud', { tenantId: 'tenant-other' }),
        { tenantId },
      ),
    /unified_runtimes_runtime_scope_mismatch/u,
  );
  assert.throws(
    () =>
      createUnifiedRuntimesRouteBindingForRuntime(
        runtimeConfig('local', { projectId: ' ' }),
        { tenantId },
      ),
    /unified_runtimes_runtime_scope_mismatch/u,
  );
});

function authState(overrides = {}) {
  return {
    status: 'signed_in',
    credentialKind: 'cloud_session',
    session: null,
    context: null,
    user: currentUser(),
    tenants: [],
    projects: [],
    mustChangePassword: false,
    error: null,
    ...overrides,
  };
}

function currentUser() {
  return {
    user_id: 'user-1',
    email: 'user@example.com',
    name: 'User',
    roles: [],
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    profile: {},
  };
}

function capabilityEntry() {
  return Object.freeze({
    availability: 'available',
    reason_code: null,
    service_version: '3.0.0',
    contract_version: '3.0.0',
    allowed_actions: Object.freeze(['view']),
    scope: Object.freeze({
      tenant_id: tenantId,
      project_id: projectId,
      workspace_id: null,
      instance_id: null,
    }),
    authority_revision: 7,
  });
}

function capabilitySnapshot(capabilities) {
  return {
    version: '3.0.0',
    mode: 'cloud',
    capabilities,
  };
}

function runtimeConfig(mode, overrides = {}) {
  return {
    apiBaseUrl: mode === 'cloud' ? 'https://api.example.test' : 'http://127.0.0.1:1',
    deviceAuthorizationBaseUrl: 'https://auth.example.test',
    apiKey: mode === 'cloud' ? 'redacted-test-credential' : '',
    localApiToken: mode === 'local' ? 'redacted-local-credential' : '',
    tenantId,
    projectId,
    workspaceId: 'workspace-1',
    mode,
    workspaceRoot: '/workspace',
    ...overrides,
  };
}

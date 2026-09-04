import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

import { projectOverviewOperationsV2Fixture } from './projectOverviewOperationsV2Fixture.mjs';
import { runtimeClustersOperationsV2Fixture } from './runtimeClustersOperationsV2Fixture.mjs';
import { runtimeInstancesOperationsV2Fixture } from './runtimeInstancesOperationsV2Fixture.mjs';
import { runtimeDeploymentsOperationsV2Fixture } from './runtimeDeploymentsOperationsV2Fixture.mjs';
import { tenantTasksOperationsV2Fixture } from './tenantTasksOperationsV2Fixture.mjs';

const require = createRequire(import.meta.url);
const {
  createProjectOverviewRouteBindingForRuntime,
  createInstanceTemplatesRouteBindingForRuntime,
  createRuntimeClustersRouteBindingForRuntime,
  createRuntimeDeploymentsRouteBindingForRuntime,
  createRuntimeInstancesRouteBindingForRuntime,
  createRuntimePoolRouteBindingForRuntime,
  createTenantTasksRouteBindingForRuntime,
  createUnifiedRuntimesRouteBindingForRuntime,
  desktopRouteBasePermissionsForAuth,
  desktopRoutePermissionsForContext,
  resolveDesktopRouteCapability,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopProductionRouteRuntime.js'
);
const {
  RuntimePoolUnavailableError,
} = require('/tmp/agistack-desktop-test-dist/src/features/runtime-pool/runtimePoolClient.js');

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
    ['anonymous'],
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

test('deployment capability resolution binds the optional instance route context', () => {
  const entry = capabilityEntry({
    scope: {
      tenant_id: tenantId,
      project_id: null,
      workspace_id: null,
      instance_id: null,
    },
  });
  const snapshot = capabilitySnapshot({
    'tenant-tenant-deploy': entry,
  });
  const resolved = resolveDesktopRouteCapability(
    snapshot,
    'tenant-tenant-deploy',
    { tenantId, instanceId: 'instance-1' },
  );
  assert.equal(resolved.scope.instance_id, 'instance-1');
  assert.equal(entry.scope.instance_id, null);
});

test('cloud project overview binding injects the V2 authority client', () => {
  const calls = [];
  const cloudClient = Object.freeze({ kind: 'cloud-client' });
  const controller = Object.freeze({ kind: 'controller' });
  const config = runtimeConfig('cloud');
  const operations = projectOverviewOperationsV2Fixture();

  const binding = createProjectOverviewRouteBindingForRuntime(
    config,
    routeContext,
    operations,
    {
      createClient(receivedOperations, receivedConfig) {
        calls.push(['client', receivedOperations, receivedConfig]);
        return cloudClient;
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
    ['client', operations, config],
    [
      'controller',
      {
        authority: 'cloud',
        client: cloudClient,
        initialScope: binding.scope,
      },
    ],
  ]);
});

test('local project overview binding injects the V2 authority client', () => {
  const calls = [];
  const localClient = Object.freeze({ kind: 'local-client' });
  const controller = Object.freeze({ kind: 'controller' });
  const config = runtimeConfig('local');
  const operations = projectOverviewOperationsV2Fixture();

  const binding = createProjectOverviewRouteBindingForRuntime(
    config,
    routeContext,
    operations,
    {
      createClient(receivedOperations, receivedConfig) {
        calls.push(['client', receivedOperations, receivedConfig]);
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
    ['client', operations, config],
    [
      'controller',
      {
        authority: 'local',
        client: localClient,
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
        createProjectOverviewRouteBindingForRuntime(
          config,
          context,
          projectOverviewOperationsV2Fixture(),
          {
          createClient() {
            calls.push('client');
            return {};
          },
          createController() {
            calls.push('controller');
            return {};
          },
          },
        ),
      /project_overview_runtime_scope_mismatch/u,
    );
    assert.deepEqual(calls, []);
  }
});

test('project overview binding fails closed without the V2 authority', () => {
  assert.throws(
    () =>
      createProjectOverviewRouteBindingForRuntime(
        runtimeConfig('cloud'),
        routeContext,
        undefined,
      ),
    /desktop_project_overview_authority_required/u,
  );
});

test('Tenant Tasks binding keeps Cloud tenant-wide and Local project-scoped', () => {
  const cloud = createTenantTasksRouteBindingForRuntime(
    runtimeConfig('cloud', { projectId: '' }),
    { tenantId },
    tenantTasksOperationsV2Fixture(),
  );
  assert.deepEqual(cloud.scope, {
    authority: 'cloud',
    tenantId,
    projectId: null,
  });
  assert.equal(cloud.controller.getSnapshot().authority, 'cloud');

  const local = createTenantTasksRouteBindingForRuntime(
    runtimeConfig('local'),
    { tenantId },
    tenantTasksOperationsV2Fixture(),
  );
  assert.deepEqual(local.scope, {
    authority: 'local',
    tenantId,
    projectId,
  });
  assert.equal(local.controller.getSnapshot().authority, 'local');
});

test('Tenant Tasks binding rejects tenant drift and missing Local project scope', () => {
  const operations = tenantTasksOperationsV2Fixture();
  assert.throws(
    () =>
      createTenantTasksRouteBindingForRuntime(
        runtimeConfig('cloud'),
        { tenantId: 'tenant-other' },
        operations,
      ),
    /tenant_tasks_runtime_scope_mismatch/u,
  );
  assert.throws(
    () =>
      createTenantTasksRouteBindingForRuntime(
        runtimeConfig('local', { projectId: '' }),
        { tenantId },
        operations,
      ),
    /tenant_tasks_runtime_scope_mismatch/u,
  );
});

test('Runtime Pool binding preserves exact Cloud and Local tenant authority', async () => {
  const cloud = createRuntimePoolRouteBindingForRuntime(
    runtimeConfig('cloud'),
    { tenantId },
    runtimePoolOperationsV2Fixture(),
  );
  assert.deepEqual(cloud.scope, { authority: 'cloud', tenantId });
  assert.equal(cloud.controller.getSnapshot().authority, 'cloud');

  const local = createRuntimePoolRouteBindingForRuntime(
    runtimeConfig('local'),
    { tenantId },
    runtimePoolOperationsV2Fixture(),
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
      createRuntimePoolRouteBindingForRuntime(
        runtimeConfig('cloud'),
        { tenantId: 'tenant-other' },
        runtimePoolOperationsV2Fixture(),
      ),
    /runtime_pool_runtime_scope_mismatch/u,
  );
});

test('Runtime Instances binding preserves exact Cloud and Local tenant authority', () => {
  const cloud = createRuntimeInstancesRouteBindingForRuntime(
    runtimeConfig('cloud'),
    { tenantId },
    runtimeInstancesOperationsV2Fixture(),
  );
  assert.deepEqual(cloud.scope, { authority: 'cloud', tenantId });
  assert.equal(cloud.controller.getSnapshot().authority, 'cloud');

  const local = createRuntimeInstancesRouteBindingForRuntime(
    runtimeConfig('local'),
    { tenantId },
    runtimeInstancesOperationsV2Fixture(),
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
    runtimeClustersOperationsV2Fixture(),
  );
  assert.deepEqual(cloud.scope, { authority: 'cloud', tenantId });
  assert.equal(cloud.controller.getSnapshot().authority, 'cloud');

  const local = createRuntimeClustersRouteBindingForRuntime(
    runtimeConfig('local'),
    { tenantId },
    runtimeClustersOperationsV2Fixture(),
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
      createRuntimeClustersRouteBindingForRuntime(
        runtimeConfig('cloud'),
        { tenantId: 'tenant-other' },
        runtimeClustersOperationsV2Fixture(),
      ),
    /runtime_clusters_runtime_scope_mismatch/u,
  );
});

test('Runtime Clusters binding requires the complete V2 operations facade', () => {
  assert.throws(
    () =>
      createRuntimeClustersRouteBindingForRuntime(
        runtimeConfig('cloud'),
        { tenantId },
        {},
      ),
    /desktop_runtime_clusters_authority_required/u,
  );
});

test('Runtime Deployments binding preserves instance scope and keeps Local cloud-only', async () => {
  const cloud = createRuntimeDeploymentsRouteBindingForRuntime(
    runtimeConfig('cloud'),
    { tenantId, instanceId: 'instance-1' },
    runtimeDeploymentsOperationsV2Fixture(),
  );
  assert.deepEqual(cloud.scope, {
    authority: 'cloud',
    tenantId,
    instanceId: 'instance-1',
  });
  assert.equal(cloud.controller.getSnapshot().authority, 'cloud');

  const local = createRuntimeDeploymentsRouteBindingForRuntime(
    runtimeConfig('local'),
    { tenantId, instanceId: 'instance-1' },
    runtimeDeploymentsOperationsV2Fixture(),
  );
  assert.deepEqual(local.scope, {
    authority: 'local',
    tenantId,
    instanceId: 'instance-1',
  });
  await local.controller.load(local.scope);
  assert.equal(local.controller.getSnapshot().state, 'unavailable');
  assert.equal(
    local.controller.getSnapshot().reasonCode,
    'cloud_deployment_authority_not_applicable',
  );
});

test('Runtime Deployments binding rejects tenant drift and preserves missing instance scope', () => {
  assert.throws(
    () =>
      createRuntimeDeploymentsRouteBindingForRuntime(
        runtimeConfig('cloud'),
        { tenantId: 'tenant-other', instanceId: 'instance-1' },
        runtimeDeploymentsOperationsV2Fixture(),
      ),
    /runtime_deployments_runtime_scope_mismatch/u,
  );
  const missing = createRuntimeDeploymentsRouteBindingForRuntime(
    runtimeConfig('cloud'),
    { tenantId },
    runtimeDeploymentsOperationsV2Fixture(),
  );
  assert.equal(missing.scope.instanceId, null);
  assert.equal(missing.controller.getSnapshot().state, 'loading');
});

test('Instance Templates binding preserves exact Cloud and Local tenant authority', async () => {
  const cloud = createInstanceTemplatesRouteBindingForRuntime(
    runtimeConfig('cloud'),
    { tenantId },
  );
  assert.deepEqual(cloud.scope, { authority: 'cloud', tenantId });
  assert.equal(cloud.controller.getSnapshot().authority, 'cloud');

  const local = createInstanceTemplatesRouteBindingForRuntime(
    runtimeConfig('local'),
    { tenantId },
  );
  assert.deepEqual(local.scope, { authority: 'local', tenantId });
  await local.controller.load(local.scope);
  assert.equal(local.controller.getSnapshot().state, 'unavailable');
  assert.equal(
    local.controller.getSnapshot().reasonCode,
    'local_instance_template_authority_unavailable',
  );
});

test('Instance Templates binding rejects tenant scope drift', () => {
  assert.throws(
    () =>
      createInstanceTemplatesRouteBindingForRuntime(runtimeConfig('cloud'), {
        tenantId: 'tenant-other',
      }),
    /instance_templates_runtime_scope_mismatch/u,
  );
});

test('Unified Runtimes binding preserves exact Cloud and Local scope authority', async () => {
  const cloud = createUnifiedRuntimesRouteBindingForRuntime(
    runtimeConfig('cloud'),
    { tenantId },
    unifiedRuntimesOperationsV2Fixture(),
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
    unifiedRuntimesOperationsV2Fixture(),
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
        unifiedRuntimesOperationsV2Fixture(),
      ),
    /unified_runtimes_runtime_scope_mismatch/u,
  );
  assert.throws(
    () =>
      createUnifiedRuntimesRouteBindingForRuntime(
        runtimeConfig('local', { projectId: ' ' }),
        { tenantId },
        unifiedRuntimesOperationsV2Fixture(),
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

function runtimePoolOperationsV2Fixture() {
  const localUnavailable = (input) => {
    if (input.scope.authority === 'local') {
      throw new RuntimePoolUnavailableError('cloud_runtime_pool_not_applicable');
    }
  };
  return {
    async getRuntimePoolStatus(input) {
      localUnavailable(input);
      return {
        enabled: true,
        status: 'running',
        totalInstances: 0,
        hotInstances: 0,
        warmInstances: 0,
        coldInstances: 0,
        readyInstances: 0,
        executingInstances: 0,
        unhealthyInstances: 0,
        prewarmPool: null,
        resourceUsage: null,
        reasonCode: 'global_pool_capacity_not_available_in_tenant_scope',
      };
    },
    async listRuntimePoolInstances(input) {
      localUnavailable(input);
      return { instances: [], total: 0, page: 1, pageSize: 20 };
    },
    async getRuntimePoolMetrics(input) {
      localUnavailable(input);
      return {
        instances: {
          total: 0,
          byTier: { hot: 0, warm: 0, cold: 0 },
          byStatus: { ready: 0, executing: 0, unhealthy: 0 },
        },
        unhealthyCount: 0,
        prewarm: null,
        reasonCode: 'global_pool_capacity_not_available_in_tenant_scope',
      };
    },
    pauseRuntimePoolInstance: async () => undefined,
    resumeRuntimePoolInstance: async () => undefined,
    terminateRuntimePoolInstance: async () => undefined,
    probeRuntimePool: async (input) => ({
      availability: input.scope.authority === 'local' ? 'not_applicable' : 'degraded',
      reason_code:
        input.scope.authority === 'local'
          ? 'cloud_runtime_pool_not_applicable'
          : 'global_pool_capacity_not_available_in_tenant_scope',
      service_version: input.scope.authority === 'local' ? null : '0.1.0',
      contract_version: input.scope.authority === 'local' ? null : '3.0.0',
      allowed_actions: [],
      scope: {
        tenant_id: input.scope.tenantId,
        project_id: null,
        workspace_id: null,
        instance_id: null,
      },
      authority_revision: null,
    }),
  };
}

function unifiedRuntimesOperationsV2Fixture() {
  return {
    async getPoolStatus() { return {}; },
    async listPoolInstances() { return { instances: [], total: 0, page: 1, pageSize: 100 }; },
    async listSandboxes() { return []; },
    async getSandboxStats() { return null; },
    async getLocalSidecar() { return { running: true, toolCount: 0, providerCount: 0 }; },
    async getSandboxCapabilities() {
      const unavailable = { availability: 'unavailable', reasonCode: 'sandbox_capability_unavailable' };
      return { serviceVersion: '1.0.0', contractVersion: '1.0.0', terminalInteractive: unavailable, terminalResume: unavailable, files: unavailable, kasmVnc: unavailable };
    },
    async probe() { throw new Error('not used'); },
  };
}

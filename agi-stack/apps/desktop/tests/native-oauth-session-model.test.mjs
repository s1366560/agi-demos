import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { createDesktopRouteRegistry } = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRouteRegistry.js',
);
const {
  createProjectedCloudSessionState,
  resolveNativeOAuthResumePath,
} = require('/tmp/agistack-desktop-test-dist/src/features/auth/nativeOAuthSessionModel.js');

test('native OAuth projection creates an authenticated state without a renderer credential', () => {
  const result = createProjectedCloudSessionState(projection(), {
    apiBaseUrl: 'https://old.test',
    deviceAuthorizationBaseUrl: 'https://old.test',
    apiKey: 'legacy-renderer-token',
    localApiToken: '',
    tenantId: '',
    projectId: '',
    workspaceId: 'old-workspace',
    mode: 'cloud',
    workspaceRoot: '/workspace',
  });

  assert.equal(result.config.apiKey, '');
  assert.equal(result.config.apiBaseUrl, 'https://cloud.memstack.test');
  assert.equal(result.config.tenantId, 'tenant-1');
  assert.equal(result.config.projectId, 'project-1');
  assert.equal(result.config.workspaceId, '');
  assert.deepEqual(result.auth.user.profile, {});
  assert.equal(JSON.stringify(result).includes('legacy-renderer-token'), false);
  assert.equal(JSON.stringify(result).includes('oauth-subject'), false);
});

test('tenant-only native OAuth projection preserves null project authority', () => {
  const result = createProjectedCloudSessionState(
    projection({ projectId: null, projects: [] }),
    {
      apiBaseUrl: 'https://old.test',
      deviceAuthorizationBaseUrl: 'https://old.test',
      apiKey: 'legacy-renderer-token',
      localApiToken: '',
      tenantId: '',
      projectId: 'stale-project',
      workspaceId: 'old-workspace',
      mode: 'cloud',
      workspaceRoot: '/workspace',
    },
  );

  assert.equal(result.config.tenantId, 'tenant-1');
  assert.equal(result.config.projectId, '');
  assert.equal(result.config.workspaceId, '');
  assert.equal(result.auth.context.project_id, null);
});

test('native OAuth resume accepts only canonical routes bound to the projected scope', () => {
  const registry = routeRegistry();
  assert.equal(
    resolveNativeOAuthResumePath(
      registry,
      '/tenant/tenant-1/project/project-1/overview',
      projection(),
    ),
    '/tenant/tenant-1/project/project-1/overview',
  );
  assert.equal(
    resolveNativeOAuthResumePath(
      registry,
      '/tenant/other/project/project-1/overview',
      projection(),
    ),
    '/tenant/tenant-1/project/project-1/overview',
  );
  assert.equal(
    resolveNativeOAuthResumePath(registry, '/not-registered', projection()),
    '/tenant/tenant-1/project/project-1/overview',
  );
  assert.equal(
    resolveNativeOAuthResumePath(
      registry,
      '/tenant/tenant-1/project/project-1/workspace/workspace-1',
      projection(),
    ),
    '/tenant/tenant-1/project/project-1/overview',
  );
});

test('tenant-only native OAuth resume falls back from project routes to tenant overview', () => {
  const registry = routeRegistry();
  const tenantProjection = projection({ projectId: null, projects: [] });
  assert.equal(
    resolveNativeOAuthResumePath(registry, '/tenant/tenant-1/overview', tenantProjection),
    '/tenant/tenant-1/overview',
  );
  assert.equal(
    resolveNativeOAuthResumePath(
      registry,
      '/tenant/tenant-1/project/project-1/overview',
      tenantProjection,
    ),
    '/tenant/tenant-1/overview',
  );
  assert.equal(
    resolveNativeOAuthResumePath(
      registry,
      '/tenant/tenant-1/project/project-1/workspace/workspace-1',
      tenantProjection,
    ),
    '/tenant/tenant-1/overview',
  );
  assert.equal(
    resolveNativeOAuthResumePath(registry, '/tenant/other/overview', tenantProjection),
    '/tenant/tenant-1/overview',
  );
});

function projection({ projectId = 'project-1', projects } = {}) {
  return {
    status: 'authenticated',
    apiBaseUrl: 'https://cloud.memstack.test',
    expiresAt: null,
    user: {
      userId: 'user-1',
      email: 'user@example.test',
      name: 'User One',
      roles: ['member'],
      globalRoles: [],
      active: true,
      superuser: false,
      createdAt: '2026-08-10T00:00:00Z',
      preferredLanguage: 'zh-CN',
    },
    workspaceContext: {
      tenantId: 'tenant-1',
      projectId,
      revision: 7,
      updatedAt: '2026-08-10T00:01:00Z',
      membershipRole: 'member',
    },
    tenants: [{ id: 'tenant-1', name: 'Tenant One' }],
    projects:
      projects ?? [{ id: 'project-1', tenant_id: 'tenant-1', name: 'Project One' }],
  };
}

function routeRegistry() {
  const loader = async () => null;
  return createDesktopRouteRegistry([
    {
      id: 'tenant-tenant-overview',
      path: '/tenant/:tenantId/overview',
      scope: ['tenant'],
      navGroup: 'tenant',
      capability: 'tenant-overview',
      requiredPermission: [['authenticated']],
      localPolicy: 'cloud_only',
      loader,
    },
    {
      id: 'project-project-overview',
      path: '/tenant/:tenantId/project/:projectId/overview',
      scope: ['tenant', 'project'],
      navGroup: 'project',
      capability: 'project-overview',
      requiredPermission: [['authenticated']],
      localPolicy: 'cloud_only',
      loader,
    },
    {
      id: 'workspace-detail',
      path: '/tenant/:tenantId/project/:projectId/workspace/:workspaceId',
      scope: ['tenant', 'project', 'workspace'],
      navGroup: 'workspace',
      capability: 'workspace-detail',
      requiredPermission: [['authenticated']],
      localPolicy: 'cloud_only',
      loader,
    },
  ]);
}

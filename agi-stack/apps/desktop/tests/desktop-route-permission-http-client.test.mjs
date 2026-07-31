import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  createCloudDesktopRoutePermissionClient,
  createLocalDesktopRoutePermissionClient,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRoutePermissionHttpClient.js'
);

function runtimeConfig(mode) {
  return {
    apiBaseUrl:
      mode === 'cloud' ? 'https://api.example.test' : 'http://127.0.0.1:43123',
    deviceAuthorizationBaseUrl: 'https://auth.example.test',
    apiKey: 'redacted-route-test-credential',
    localApiToken: 'redacted-local-route-test-credential',
    tenantId: 'tenant-current',
    projectId: 'project-current',
    workspaceId: 'workspace-current',
    mode,
    workspaceRoot: '/workspace',
  };
}

test('Cloud permission client uses scoped production APIs and preserves AbortSignal', async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  const controller = new AbortController();
  globalThis.fetch = async (url, init) => {
    calls.push([String(url), init]);
    const path = new URL(String(url)).pathname;
    if (path === '/api/v1/auth/me') {
      return Response.json({
        user_id: 'user-1',
        email: 'user@example.invalid',
        name: 'Route User',
        roles: [],
        global_roles: [],
        is_active: true,
        is_superuser: false,
        created_at: '2026-07-30T00:00:00Z',
        profile: {},
      });
    }
    if (path === '/api/v1/workspace-context') {
      return Response.json({
        context: {
          tenant_id: 'tenant-1',
          project_id: 'project-1',
          revision: 3,
          updated_at: '2026-07-30T00:00:00Z',
        },
        membership_role: 'member',
      });
    }
    if (path.endsWith('/members')) {
      return Response.json([
        {
          id: 'member-1',
          workspace_id: 'workspace-1',
          user_id: 'user-1',
          role: 'viewer',
        },
      ]);
    }
    return Response.json({ detail: 'unexpected route' }, { status: 500 });
  };

  try {
    const client = createCloudDesktopRoutePermissionClient(runtimeConfig('cloud'));
    const context = Object.freeze({
      tenantId: 'tenant-1',
      projectId: 'project-1',
      workspaceId: 'workspace-1',
    });
    await client.getCurrentUser(controller.signal);
    await client.getWorkspaceContext(controller.signal);
    const members = await client.listWorkspaceMembers(context, controller.signal);

    assert.equal(members[0].workspace_id, 'workspace-1');
    assert.equal(calls.every(([, init]) => init.signal === controller.signal), true);
    assert.equal(
      calls.some(([url]) =>
        url.includes(
          '/api/v1/tenants/tenant-1/projects/project-1/workspaces/workspace-1/members?',
        ),
      ),
      true,
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('permission clients reject Cloud and Local mode drift', () => {
  assert.throws(
    () => createCloudDesktopRoutePermissionClient(runtimeConfig('local')),
    /desktop_route_permission_mode_mismatch/u,
  );
  assert.throws(
    () => createLocalDesktopRoutePermissionClient(runtimeConfig('cloud')),
    /desktop_route_permission_mode_mismatch/u,
  );

});

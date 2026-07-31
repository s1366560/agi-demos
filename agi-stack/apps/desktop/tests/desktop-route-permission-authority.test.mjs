import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  DesktopRoutePermissionAuthorityError,
  createCloudDesktopRoutePermissionResolver,
  createLocalDesktopRoutePermissionResolver,
  parseDesktopRoutePermissionSnapshot,
} = require('/tmp/agistack-desktop-test-dist/src/features/navigation/desktopRoutePermissionAuthority.js');

const routeContext = Object.freeze({
  tenantId: 'tenant-1',
  projectId: 'project-1',
  workspaceId: 'workspace-1',
});

function currentUser(overrides = {}) {
  return {
    user_id: 'user-1',
    email: 'user-1@example.invalid',
    name: 'Route User',
    roles: [],
    global_roles: [],
    is_active: true,
    is_superuser: false,
    created_at: '2026-07-30T00:00:00Z',
    profile: {},
    ...overrides,
  };
}

function workspaceContext(overrides = {}) {
  return {
    context: {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      revision: 7,
      updated_at: '2026-07-30T00:00:00Z',
      ...overrides,
    },
    membership_role: 'member',
  };
}

function authorityClient(overrides = {}) {
  return {
    getCurrentUser: async () => currentUser(),
    getWorkspaceContext: async () => workspaceContext(),
    listWorkspaceMembers: async () => [
      {
        id: 'workspace-member-1',
        workspace_id: 'workspace-1',
        user_id: 'user-1',
        role: 'viewer',
      },
    ],
    ...overrides,
  };
}

test('strict snapshot parser freezes the v3 contract and rejects surplus or malformed fields', () => {
  const parsed = parseDesktopRoutePermissionSnapshot({
    contract_version: '3.0.0',
    subject_id: 'user-1',
    scope: {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: null,
      instance_id: null,
      conversation_id: null,
    },
    permissions: ['authenticated', 'tenant_member'],
    authority_revision: 7,
    reason_code: null,
  });

  assert.deepEqual(parsed.permissions, ['authenticated', 'tenant_member']);
  assert.equal(Object.isFrozen(parsed), true);
  assert.equal(Object.isFrozen(parsed.scope), true);
  assert.equal(Object.isFrozen(parsed.permissions), true);

  for (const malformed of [
    { ...parsed, unexpected: true },
    { ...parsed, contract_version: '2.0.0' },
    { ...parsed, authority_revision: -1 },
    { ...parsed, permissions: ['authenticated', 'authenticated'] },
    { ...parsed, permissions: [' authenticated'] },
    { ...parsed, scope: { ...parsed.scope, tenant_id: '' } },
  ]) {
    assert.throws(
      () => parseDesktopRoutePermissionSnapshot(malformed),
      (error) =>
        error instanceof DesktopRoutePermissionAuthorityError &&
        error.reasonCode === 'desktop_route_permission_snapshot_invalid',
    );
  }
});

test('cloud authority projects only route-scoped global, tenant, project, and workspace permissions', async () => {
  const calls = [];
  const resolver = createCloudDesktopRoutePermissionResolver({
    client: authorityClient({
      getCurrentUser: async (signal) => {
        calls.push(['user', signal]);
        return currentUser({
          global_roles: ['system_admin'],
          is_superuser: true,
        });
      },
      getWorkspaceContext: async (signal) => {
        calls.push(['context', signal]);
        return workspaceContext();
      },
      listWorkspaceMembers: async (context, signal) => {
        calls.push(['workspace', context, signal]);
        return authorityClient().listWorkspaceMembers();
      },
    }),
  });
  const controller = new AbortController();

  const snapshot = await resolver(routeContext, controller.signal);

  assert.deepEqual(snapshot, {
    contract_version: '3.0.0',
    subject_id: 'user-1',
    scope: {
      tenant_id: 'tenant-1',
      project_id: 'project-1',
      workspace_id: 'workspace-1',
      instance_id: null,
      conversation_id: null,
    },
    permissions: [
      'authenticated',
      'global_admin',
      'tenant_member',
      'project_member',
      'workspace_member',
    ],
    authority_revision: 7,
    reason_code: null,
  });
  assert.equal(
    calls.every((call) => call.at(-1) === controller.signal),
    true,
  );
});

test('only canonical system_admin gains role-based global authority while tenant owner remains scoped', async () => {
  const ownerResolver = createCloudDesktopRoutePermissionResolver({
    client: authorityClient({
      getCurrentUser: async () =>
        currentUser({ global_roles: ['system_admin'] }),
      getWorkspaceContext: async () => ({
        ...workspaceContext({
          revision: 8,
          updated_at: '2026-07-30T00:01:00Z',
        }),
        membership_role: 'owner',
      }),
    }),
  });

  const snapshot = await ownerResolver(
    Object.freeze({ tenantId: 'tenant-1', projectId: 'project-1' }),
    new AbortController().signal,
  );

  assert.deepEqual(snapshot.permissions, [
    'authenticated',
    'global_admin',
    'tenant_member',
    'tenant_admin',
    'tenant_owner',
    'project_member',
  ]);
  assert.equal(snapshot.reason_code, null);
});

test('tenant landing authority never borrows workspace membership from active UI state', async () => {
  let workspaceMemberCalls = 0;
  const resolver = createCloudDesktopRoutePermissionResolver({
    client: authorityClient({
      getCurrentUser: async () =>
        currentUser({
          roles: ['admin'],
          global_roles: [],
        }),
      listWorkspaceMembers: async () => {
        workspaceMemberCalls += 1;
        return authorityClient().listWorkspaceMembers();
      },
    }),
  });

  const snapshot = await resolver(
    Object.freeze({ tenantId: 'tenant-1' }),
    new AbortController().signal,
  );

  assert.deepEqual(snapshot.scope, {
    tenant_id: 'tenant-1',
    project_id: null,
    workspace_id: null,
    instance_id: null,
    conversation_id: null,
  });
  assert.deepEqual(snapshot.permissions, [
    'authenticated',
    'tenant_member',
    'project_member',
  ]);
  assert.equal(workspaceMemberCalls, 0);
});

test('explicit workspace context gains authority only from exact membership', async () => {
  const resolver = createCloudDesktopRoutePermissionResolver({
    client: authorityClient({
      listWorkspaceMembers: async () => [
        {
          id: 'workspace-member-unrelated',
          workspace_id: 'workspace-other',
          user_id: 'user-1',
          role: 'owner',
        },
        {
          id: 'workspace-member-other-user',
          workspace_id: 'workspace-1',
          user_id: 'user-other',
          role: 'owner',
        },
      ],
    }),
  });

  const snapshot = await resolver(routeContext, new AbortController().signal);

  assert.equal(snapshot.scope.workspace_id, 'workspace-1');
  assert.equal(snapshot.permissions.includes('workspace_member'), false);
});

test('legacy admin aliases do not gain generic global route authority', async () => {
  const resolver = createCloudDesktopRoutePermissionResolver({
    client: authorityClient({
      getCurrentUser: async () =>
        currentUser({ global_roles: ['admin', 'super_admin'] }),
    }),
  });

  const snapshot = await resolver(Object.freeze({}), new AbortController().signal);

  assert.equal(snapshot.scope.tenant_id, null);
  assert.equal(snapshot.permissions.includes('global_admin'), false);
});

test('local authority shares the contract and fails closed on scope mismatch or abort', async () => {
  const localResolver = createLocalDesktopRoutePermissionResolver({
    client: authorityClient(),
  });

  await assert.rejects(
    localResolver(
      Object.freeze({ tenantId: 'tenant-other', projectId: 'project-1' }),
      new AbortController().signal,
    ),
    (error) =>
      error instanceof DesktopRoutePermissionAuthorityError &&
      error.reasonCode === 'desktop_route_permission_scope_mismatch',
  );

  const controller = new AbortController();
  controller.abort(new DOMException('Aborted', 'AbortError'));
  await assert.rejects(
    localResolver(routeContext, controller.signal),
    (error) => error.name === 'AbortError',
  );
});

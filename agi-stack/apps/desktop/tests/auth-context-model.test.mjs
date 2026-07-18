import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  findWorkspaceProject,
  isCurrentContextRevision,
  isCurrentLocalRuntimeAuthority,
  isIdentityAuthenticated,
  isSameDesktopProjectRequestScope,
  isSameDesktopRequestScope,
  isWorkspaceReady,
  resolveSignOutDisposition,
  workspaceContextMatchesSelection,
} = require('/tmp/agistack-desktop-test-dist/src/features/auth/authContextModel.js');

const authenticated = {
  status: 'signed_in',
  credentialKind: 'local_session',
  session: null,
  context: {
    tenant_id: 'northstar',
    project_id: 'desktop-client',
    revision: 3,
    updated_at: '2026-07-13T00:00:00Z',
  },
  user: { user_id: 'user-1' },
  tenants: [{ id: 'northstar' }],
  projects: [{ id: 'desktop-client', tenant_id: 'northstar' }],
  mustChangePassword: false,
  error: null,
};

const authenticatedConfig = {
  tenantId: 'northstar',
  projectId: 'desktop-client',
};

test('a launch capability without a user session never authenticates a workspace', () => {
  const signedOut = {
    ...authenticated,
    status: 'signed_out',
    credentialKind: null,
    context: null,
    user: null,
  };
  assert.equal(isIdentityAuthenticated(signedOut), false);
  assert.equal(isWorkspaceReady(signedOut, authenticatedConfig), false);
});

test('manual mode cannot bypass authenticated identity and workspace context', () => {
  const manual = {
    ...authenticated,
    status: 'manual',
    credentialKind: 'manual_api_key',
    context: null,
    user: null,
  };
  assert.equal(isIdentityAuthenticated(manual), false);
  assert.equal(isWorkspaceReady(manual, authenticatedConfig), false);
  assert.equal(isIdentityAuthenticated(authenticated), true);
  assert.equal(isWorkspaceReady(authenticated, authenticatedConfig), true);
});

test('an authenticated identity without a project enters project selection', () => {
  const withoutProject = {
    ...authenticated,
    context: null,
    projects: [],
  };

  assert.equal(isIdentityAuthenticated(withoutProject), true);
  assert.equal(
    isWorkspaceReady(withoutProject, { ...authenticatedConfig, projectId: '' }),
    false,
  );
});

test('workspace readiness rejects stale or unscoped project context', () => {
  assert.equal(
    isWorkspaceReady(authenticated, { ...authenticatedConfig, projectId: 'other-project' }),
    false,
  );
  assert.equal(
    isWorkspaceReady({ ...authenticated, projects: [] }, authenticatedConfig),
    false,
  );
  assert.equal(
    isWorkspaceReady({ ...authenticated, tenants: [] }, authenticatedConfig),
    false,
  );
  assert.equal(
    isWorkspaceReady(
      {
        ...authenticated,
        projects: [{ id: 'desktop-client', tenant_id: 'other-tenant' }],
      },
      authenticatedConfig,
    ),
    false,
  );
});

test('workspace project resolution keeps duplicate ids inside the selected tenant', () => {
  const projects = [
    { id: 'shared-id', tenant_id: 'tenant-b', name: 'Wrong tenant' },
    { id: 'shared-id', tenant_id: 'tenant-a', name: 'Selected tenant' },
  ];

  assert.equal(findWorkspaceProject(projects, 'tenant-a', 'shared-id')?.name, 'Selected tenant');
  assert.equal(findWorkspaceProject(projects, 'tenant-c', 'shared-id'), undefined);
  assert.equal(findWorkspaceProject(projects, 'tenant-a', ''), undefined);
});

test('workspace context responses must exactly match the requested tenant and project', () => {
  const context = {
    tenant_id: 'tenant-a',
    project_id: 'project-a',
    revision: 4,
    updated_at: '2026-07-13T02:00:00Z',
  };

  assert.equal(workspaceContextMatchesSelection(context, 'tenant-a', 'project-a'), true);
  assert.equal(workspaceContextMatchesSelection(context, 'tenant-b', 'project-a'), false);
  assert.equal(workspaceContextMatchesSelection(context, 'tenant-a', 'project-b'), false);
});

test('context revisions reject stale responses without manufacturing client authority', () => {
  assert.equal(isCurrentContextRevision(3, 3), true);
  assert.equal(isCurrentContextRevision(3, 4), false);
});

test('desktop request scope invalidates every identity and hierarchy boundary', () => {
  const scope = {
    mode: 'cloud',
    apiBaseUrl: 'http://127.0.0.1:8000',
    apiKey: 'session-a',
    localApiToken: '',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
  };

  assert.equal(isSameDesktopRequestScope(scope, { ...scope }), true);
  for (const [field, value] of [
    ['mode', 'local'],
    ['apiBaseUrl', 'http://127.0.0.1:8088'],
    ['apiKey', 'session-b'],
    ['localApiToken', 'launch-b'],
    ['tenantId', 'tenant-2'],
    ['projectId', 'project-2'],
    ['workspaceId', 'workspace-2'],
  ]) {
    assert.equal(isSameDesktopRequestScope(scope, { ...scope, [field]: value }), false, field);
  }
});

test('project request scope survives workspace navigation but not authority changes', () => {
  const scope = {
    mode: 'cloud',
    apiBaseUrl: 'http://127.0.0.1:8000',
    apiKey: 'session-a',
    localApiToken: '',
    tenantId: 'tenant-1',
    projectId: 'project-1',
    workspaceId: 'workspace-1',
  };

  assert.equal(
    isSameDesktopProjectRequestScope(scope, { ...scope, workspaceId: 'workspace-2' }),
    true
  );
  for (const [field, value] of [
    ['mode', 'local'],
    ['apiBaseUrl', 'http://127.0.0.1:8088'],
    ['apiKey', 'session-b'],
    ['localApiToken', 'launch-b'],
    ['tenantId', 'tenant-2'],
    ['projectId', 'project-2'],
  ]) {
    assert.equal(
      isSameDesktopProjectRequestScope(scope, { ...scope, [field]: value }),
      false,
      field
    );
  }
});

test('local session recovery binds the launch capability to the live native endpoint', () => {
  const config = {
    mode: 'local',
    apiBaseUrl: 'http://127.0.0.1:43123',
    localApiToken: 'launch-capability-redacted',
  };
  const status = {
    running: true,
    api_base_url: config.apiBaseUrl,
    api_token: config.localApiToken,
  };

  assert.equal(isCurrentLocalRuntimeAuthority(config, status, true), true);
  assert.equal(
    isCurrentLocalRuntimeAuthority(
      config,
      { ...status, api_base_url: 'http://127.0.0.1:43124' },
      true,
    ),
    false,
  );
  assert.equal(
    isCurrentLocalRuntimeAuthority(config, { ...status, api_token: 'other-capability' }, true),
    false,
  );
  assert.equal(isCurrentLocalRuntimeAuthority(config, status, false), false);
});

test('sign out completes only after a stored credential is cleared or revoked', () => {
  assert.equal(resolveSignOutDisposition(false, true, false), 'blocked');
  assert.equal(resolveSignOutDisposition(true, true, false), 'blocked');
  assert.equal(resolveSignOutDisposition(false, true, true), 'complete');
  assert.equal(resolveSignOutDisposition(true, true, true), 'complete');
  assert.equal(
    resolveSignOutDisposition(true, false, true),
    'complete_with_persistence_warning',
  );
  assert.equal(resolveSignOutDisposition(true, false, false), 'blocked');
});

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  isCurrentContextRevision,
  isSameDesktopRequestScope,
  isWorkspaceAuthenticated,
  nextRemoteWorkspaceContext,
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
  tenants: [],
  projects: [],
  mustChangePassword: false,
  error: null,
};

test('a launch capability without a user session never authenticates a workspace', () => {
  assert.equal(
    isWorkspaceAuthenticated({
      ...authenticated,
      status: 'signed_out',
      credentialKind: null,
      context: null,
      user: null,
    }),
    false,
  );
});

test('manual mode cannot bypass authenticated identity and workspace context', () => {
  assert.equal(
    isWorkspaceAuthenticated({
      ...authenticated,
      status: 'manual',
      credentialKind: 'manual_api_key',
      context: null,
      user: null,
    }),
    false,
  );
  assert.equal(isWorkspaceAuthenticated(authenticated), true);
});

test('context revisions reject stale responses and advance remote context monotonically', () => {
  assert.equal(isCurrentContextRevision(3, 3), true);
  assert.equal(isCurrentContextRevision(3, 4), false);
  assert.deepEqual(
    nextRemoteWorkspaceContext(
      authenticated.context,
      'orbital',
      'agent-evals',
      '2026-07-13T01:00:00Z',
    ),
    {
      tenant_id: 'orbital',
      project_id: 'agent-evals',
      revision: 4,
      updated_at: '2026-07-13T01:00:00Z',
    },
  );
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

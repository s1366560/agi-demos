import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  isCurrentContextRevision,
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

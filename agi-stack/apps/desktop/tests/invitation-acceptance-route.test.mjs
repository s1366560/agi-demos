import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
require.extensions['.css'] = () => {};
const { invitationAcceptanceCapability } = require(
  '/tmp/agistack-desktop-test-dist/src/features/invitation-acceptance/invitationAcceptanceCapability.js',
);
const { createInvitationAcceptanceRouteModuleLoader } = require(
  '/tmp/agistack-desktop-test-dist/src/features/invitation-acceptance/invitationAcceptanceRouteModule.js',
);

test('invitation acceptance route is native Cloud and cloud-only Local', async () => {
  const cloud = invitationAcceptanceCapability({ mode: 'cloud' });
  const local = invitationAcceptanceCapability({ mode: 'local' });
  assert.equal(cloud.availability, 'available');
  assert.deepEqual(cloud.allowed_actions, ['verify', 'sign-in', 'accept', 'open-tenant', 'retry']);
  assert.equal(local.availability, 'not_applicable');
  assert.equal(local.reason_code, 'local_tenant_invitation_not_applicable');

  const loader = createInvitationAcceptanceRouteModuleLoader({
    createBinding: () => ({
      client: {},
      token: 'token',
      authenticated: () => false,
      accountEmail: () => '',
      onRequireSignIn() {},
      onAccepted() {},
      onNavigateHome() {},
    }),
  });
  const module = await loader();
  assert.equal(module.routeId, 'invitation-acceptance');
  assert.equal(module.localPolicy, 'cloud_only');
  assert.equal(module.disposition, 'implemented');
});

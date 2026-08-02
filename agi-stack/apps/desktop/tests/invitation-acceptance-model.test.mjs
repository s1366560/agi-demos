import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  invitationIsExpired,
  readInvitationTokenFromHash,
} = require('/tmp/agistack-desktop-test-dist/src/features/invitation-acceptance/invitationAcceptanceModel.js');

test('invitation deep links accept one bounded opaque query token', () => {
  assert.equal(
    readInvitationTokenFromHash('#/invite?token=invite-token_42'),
    'invite-token_42',
  );
  assert.equal(readInvitationTokenFromHash('#/invite'), '');
  assert.equal(readInvitationTokenFromHash('#/invite?token=a&token=b'), '');
  assert.equal(readInvitationTokenFromHash('#/invite/secret?token=a'), '');
  assert.equal(readInvitationTokenFromHash('#/invite?token=%0Asecret'), '');
  assert.equal(readInvitationTokenFromHash(`#/invite?token=${'a'.repeat(513)}`), '');
});

test('invitation expiration uses the authority timestamp without text heuristics', () => {
  assert.equal(
    invitationIsExpired('2026-08-02T12:00:00.000Z', Date.parse('2026-08-02T12:00:00.001Z')),
    true,
  );
  assert.equal(
    invitationIsExpired('2026-08-02T12:00:00.000Z', Date.parse('2026-08-02T11:59:59.999Z')),
    false,
  );
  assert.equal(invitationIsExpired('not-a-date', 0), false);
});

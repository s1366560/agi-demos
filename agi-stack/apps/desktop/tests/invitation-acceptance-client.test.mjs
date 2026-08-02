import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  InvitationAcceptanceError,
  createInvitationAcceptanceClient,
} = require('/tmp/agistack-desktop-test-dist/src/features/invitation-acceptance/invitationAcceptanceClient.js');

const cloudConfig = {
  mode: 'cloud',
  apiBaseUrl: 'https://api.example.test',
  apiKey: 'credential',
  tenantId: '',
  projectId: '',
  workspaceId: '',
};

test('verification is anonymous while acceptance uses authenticated Cloud authority', async () => {
  const requests = [];
  const client = createInvitationAcceptanceClient(cloudConfig, {
    fetch: async (input, init) => {
      requests.push({ input: String(input), init });
      if (init?.method === 'POST') {
        return new Response(JSON.stringify({
          id: 'invitation-1',
          tenant_id: 'tenant-1',
          email: 'member@example.test',
          role: 'member',
          status: 'accepted',
          invited_by: 'owner-1',
          expires_at: '2026-08-20T00:00:00Z',
          created_at: '2026-08-01T00:00:00Z',
        }), { status: 200, headers: { 'content-type': 'application/json' } });
      }
      return new Response(JSON.stringify({
        valid: true,
        email: 'member@example.test',
        tenant_id: 'tenant-1',
        role: 'member',
        expires_at: '2026-08-20T00:00:00Z',
      }), { status: 200, headers: { 'content-type': 'application/json' } });
    },
  });

  const verified = await client.verify('opaque token');
  const accepted = await client.accept('opaque token');
  assert.equal(verified.tenant_id, 'tenant-1');
  assert.equal(accepted.status, 'accepted');
  assert.equal(requests[0].input, 'https://api.example.test/api/v1/invitations/verify/opaque%20token');
  assert.equal(new Headers(requests[0].init.headers).has('Authorization'), false);
  assert.equal(requests[1].input, 'https://api.example.test/api/v1/invitations/accept/opaque%20token');
  assert.equal(new Headers(requests[1].init.headers).get('Authorization'), 'Bearer credential');
  assert.equal(requests[1].init.body, '{}');
});

test('Local invitation governance fails before fetch with a stable reason', async () => {
  let calls = 0;
  const client = createInvitationAcceptanceClient(
    { ...cloudConfig, mode: 'local' },
    { fetch: async () => { calls += 1; throw new Error('unexpected'); } },
  );
  await assert.rejects(
    client.verify('token'),
    (error) =>
      error instanceof InvitationAcceptanceError &&
      error.reasonCode === 'local_tenant_invitation_not_applicable',
  );
  assert.equal(calls, 0);
});

test('acceptance maps authority status and rejects malformed success bodies', async () => {
  const forbidden = createInvitationAcceptanceClient(cloudConfig, {
    fetch: async () => new Response('{}', {
      status: 403,
      headers: { 'content-type': 'application/json' },
    }),
  });
  await assert.rejects(
    forbidden.accept('token'),
    (error) => error.reasonCode === 'invitation_acceptance_forbidden',
  );

  const malformed = createInvitationAcceptanceClient(cloudConfig, {
    fetch: async () => new Response(JSON.stringify({ valid: true }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    }),
  });
  await assert.rejects(
    malformed.accept('token'),
    (error) => error.reasonCode === 'invitation_acceptance_contract_invalid',
  );
});

test('acceptance preserves the backend invalid-or-expired semantics for HTTP 400', async () => {
  const invalidOrExpired = createInvitationAcceptanceClient(cloudConfig, {
    fetch: async () => new Response(
      JSON.stringify({ detail: 'Invalid or expired invitation' }),
      {
        status: 400,
        headers: { 'content-type': 'application/json' },
      },
    ),
  });

  await assert.rejects(
    invalidOrExpired.accept('token'),
    (error) =>
      error instanceof InvitationAcceptanceError &&
      error.status === 400 &&
      error.reasonCode === 'invitation_token_invalid_or_expired',
  );
});

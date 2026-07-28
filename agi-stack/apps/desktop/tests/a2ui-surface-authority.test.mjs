import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { a2uiCommandToHitlSubmission, resolveA2UISurfaceAuthority } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/a2uiSurfaceAuthorityModel.js'
);

function asked(overrides = {}) {
  return {
    id: 'asked-1',
    type: 'a2ui_action_asked',
    eventTimeUs: 10,
    eventCounter: 2,
    payload: {
      block_id: 'surface-artifact',
      request_id: 'request-1',
      authority_revision: 7,
      allowed_actions: [
        { source_component_id: 'submit', action_name: 'approve' },
      ],
    },
    ...overrides,
  };
}

test('restores explicit A2UI authority without guessing a missing revision', () => {
  assert.deepEqual(
    resolveA2UISurfaceAuthority('surface-artifact', [asked()], ['request-1']),
    {
      artifactId: 'surface-artifact',
      requestId: 'request-1',
      authorityRevision: 7,
      idempotencyKey: 'request-1:7:a2ui_action',
      allowedActions: [
        { source_component_id: 'submit', action_name: 'approve' },
      ],
      answered: false,
      canRespond: true,
    },
  );

  const unversioned = asked();
  delete unversioned.payload.authority_revision;
  const authority = resolveA2UISurfaceAuthority(
    'surface-artifact',
    [unversioned],
    ['request-1'],
  );
  assert.equal(authority.authorityRevision, null);
  assert.equal(authority.canRespond, false);
});

test('uses the newest matching request and fails closed on malformed allow-lists', () => {
  const older = asked();
  const newer = asked({
    id: 'asked-2',
    eventTimeUs: 11,
    payload: {
      ...asked().payload,
      request_id: 'request-2',
      authority_revision: 8,
      allowed_actions: [{ source_component_id: 'submit' }],
    },
  });
  const unrelated = asked({
    id: 'asked-other',
    eventTimeUs: 12,
    payload: { ...asked().payload, block_id: 'other' },
  });

  const authority = resolveA2UISurfaceAuthority(
    'surface-artifact',
    [older, newer, unrelated],
    ['request-1', 'request-2'],
  );
  assert.equal(authority.requestId, 'request-2');
  assert.deepEqual(authority.allowedActions, []);
  assert.equal(authority.canRespond, false);
});

test('answered and expired authority is restored read-only across clients', () => {
  const answered = asked({ answered: true });
  const answeredAuthority = resolveA2UISurfaceAuthority(
    'surface-artifact',
    [answered],
    ['request-1'],
  );
  assert.equal(answeredAuthority.answered, true);
  assert.equal(answeredAuthority.canRespond, false);

  const expired = asked({
    payload: { ...asked().payload, request_status: 'expired' },
  });
  const expiredAuthority = resolveA2UISurfaceAuthority(
    'surface-artifact',
    [expired],
    ['request-1'],
  );
  assert.equal(expiredAuthority.answered, true);
  assert.equal(expiredAuthority.canRespond, false);
});

test('translates an authority-bound A2UI command to the existing HITL transport', () => {
  assert.deepEqual(
    a2uiCommandToHitlSubmission({
      contract_version: 1,
      request_id: 'request-1',
      surface_id: 'surface-1',
      source_component_id: 'submit',
      action_name: 'approve',
      authority_revision: 7,
      idempotency_key: 'request-1:7:a2ui_action',
      context: { verified: true },
    }),
    {
      requestId: 'request-1',
      hitlType: 'a2ui_action',
      expectedRevision: 7,
      idempotencyKey: 'request-1:7:a2ui_action',
      responseData: {
        surface_id: 'surface-1',
        source_component_id: 'submit',
        action_name: 'approve',
        context: { verified: true },
      },
    },
  );
});

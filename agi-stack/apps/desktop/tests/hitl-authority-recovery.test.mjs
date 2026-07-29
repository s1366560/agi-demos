import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const { DesktopApiError } = require(
  '/tmp/agistack-desktop-test-dist/src/api/client.js',
);
const { classifyHitlAuthorityRecovery } = require(
  '/tmp/agistack-desktop-test-dist/src/features/chat/hitlAuthorityRecovery.js',
);

test('already answered and expired authority settle stale clients after canonical refetch', () => {
  for (const [status, reasonCode] of [
    [409, 'hitl_already_answered'],
    [409, 'hitl_answered_resume_failed'],
    [410, 'hitl_request_expired'],
  ]) {
    assert.deepEqual(
      classifyHitlAuthorityRecovery(
        new DesktopApiError('localized message is ignored', status, {
          detail: { reason_code: reasonCode, authority_revision: 9 },
        }),
      ),
      {
        canonicalRefetch: true,
        settledByAuthority: true,
        reasonCode,
      },
    );
  }
});

test('unknown conflicts refetch but do not masquerade as an answered request', () => {
  assert.deepEqual(
    classifyHitlAuthorityRecovery(
      new DesktopApiError('conflict', 409, {
        detail: { reason_code: 'hitl_claim_conflict' },
      }),
    ),
    {
      canonicalRefetch: true,
      settledByAuthority: false,
      reasonCode: 'hitl_claim_conflict',
    },
  );
});

test('message text and unrelated statuses never drive authority recovery', () => {
  assert.deepEqual(
    classifyHitlAuthorityRecovery(
      new DesktopApiError('HITL already answered', 500, {
        detail: 'HITL already answered',
      }),
    ),
    {
      canonicalRefetch: false,
      settledByAuthority: false,
      reasonCode: null,
    },
  );
});

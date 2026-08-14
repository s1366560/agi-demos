import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  currentWorkspaceAutonomyAttentionResolveAttempt,
  resolveWorkspaceAutonomyAttentionAttempt,
  retainOpenWorkspaceAutonomyAttentionResolveAttempts,
} = require(
  '/tmp/agistack-desktop-test-dist/src/features/workspace/autonomyAttentionResolveAttemptModel.js',
);

const scopeKey = 'tenant-1\u0000project-1\u0000workspace-1';
const actorId = 'editor-1';
const attentionId = 'attention-1';

function candidate(expectedRevision, idempotencyKey) {
  return {
    scopeKey,
    actorId,
    attentionId,
    expectedRevision,
    idempotencyKey,
  };
}

function attention() {
  return {
    attention_id: attentionId,
    root_task_id: 'root-task-1',
    source_kind: 'judge_block',
    source_id: 'audit-1',
    reason: 'Editor decision required',
    status: 'open',
    created_at_ms: 10,
  };
}

test('response-loss retry reuses the original authority revision and idempotency key', () => {
  const attempts = new Map();
  const original = resolveWorkspaceAutonomyAttentionAttempt(
    attempts,
    candidate(7, 'desktop-attention-attempt-1'),
  );
  const retry = resolveWorkspaceAutonomyAttentionAttempt(
    attempts,
    candidate(11, 'desktop-attention-attempt-2'),
  );

  assert.strictEqual(retry, original);
  assert.equal(retry.expectedRevision, 7);
  assert.equal(retry.idempotencyKey, 'desktop-attention-attempt-1');
});

test('canonical open attention retains an uncertain resolve attempt', () => {
  const attempts = new Map();
  const original = resolveWorkspaceAutonomyAttentionAttempt(
    attempts,
    candidate(7, 'desktop-attention-attempt-1'),
  );

  retainOpenWorkspaceAutonomyAttentionResolveAttempts(attempts, scopeKey, actorId, [attention()]);

  assert.strictEqual(
    currentWorkspaceAutonomyAttentionResolveAttempt(
      attempts,
      scopeKey,
      actorId,
      attentionId,
    ),
    original,
  );
});

test('canonical disappearance prunes a committed resolve attempt', () => {
  const attempts = new Map();
  resolveWorkspaceAutonomyAttentionAttempt(
    attempts,
    candidate(7, 'desktop-attention-attempt-1'),
  );

  retainOpenWorkspaceAutonomyAttentionResolveAttempts(attempts, scopeKey, actorId, []);

  assert.equal(
    currentWorkspaceAutonomyAttentionResolveAttempt(
      attempts,
      scopeKey,
      actorId,
      attentionId,
    ),
    null,
  );
});

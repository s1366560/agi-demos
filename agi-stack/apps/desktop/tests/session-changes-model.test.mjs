import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  allowedRunInputDeliveries,
  referenceForChangeLine,
  runInputReferenceLabel,
  snapshotMatchesRun,
  toggleRunInputReference,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionChangesModel.js');

const snapshot = {
  id: 'snapshot-1',
  run_id: 'run-1',
  conversation_id: 'conversation-1',
  run_revision: 7,
  environment_id: 'environment-1',
  status: 'ready',
  additions: 1,
  deletions: 1,
  files_changed: 1,
  truncated: false,
  captured_at: '2026-01-01T00:00:00Z',
  files: [],
};

const file = {
  path: 'src/lib.rs',
  status: 'modified',
  additions: 1,
  deletions: 1,
  binary: false,
  untracked: false,
  patch_digest: 'patch-1',
  hunks: [],
};

test('change lines produce structured snapshot-bound references', () => {
  const added = referenceForChangeLine(snapshot, file, {
    kind: 'addition',
    old_line: null,
    new_line: 12,
    text: 'new line',
  });
  const deleted = referenceForChangeLine(snapshot, file, {
    kind: 'deletion',
    old_line: 9,
    new_line: null,
    text: 'old line',
  });

  assert.deepEqual(added, {
    type: 'code_range',
    snapshot_id: 'snapshot-1',
    environment_id: 'environment-1',
    path: 'src/lib.rs',
    start_line: 12,
    end_line: 12,
    side: 'new',
    patch_digest: 'patch-1',
  });
  assert.equal(deleted.side, 'old');
  assert.equal(deleted.start_line, 9);
  assert.equal(runInputReferenceLabel(added), 'src/lib.rs#L12');
});

test('reference toggling is structural and deduplicated', () => {
  const reference = referenceForChangeLine(snapshot, file, {
    kind: 'context',
    old_line: 11,
    new_line: 12,
    text: 'context',
  });
  const selected = toggleRunInputReference([], reference);
  assert.equal(selected.length, 1);
  assert.deepEqual(toggleRunInputReference(selected, reference), []);
});

test('delivery and snapshot availability follow authoritative run state', () => {
  assert.deepEqual(allowedRunInputDeliveries('running', true), ['steer_now', 'queue_next']);
  assert.deepEqual(allowedRunInputDeliveries('running', false), ['queue_next']);
  assert.deepEqual(allowedRunInputDeliveries('needs_approval', true), []);
  assert.equal(snapshotMatchesRun(snapshot, 'run-1', 7), true);
  assert.equal(snapshotMatchesRun(snapshot, 'run-1', 8), false);
});

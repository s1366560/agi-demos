import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { test } from 'node:test';

const require = createRequire(import.meta.url);
const {
  buildChangeRevertPayload,
  changeRevertAvailable,
  changeRevertNoticeFromError,
  revertRunChanges,
  revertTargetLabel,
} = require('/tmp/agistack-desktop-test-dist/src/features/session/sessionChangesRevertModel.js');
const { DesktopApiError } = require('/tmp/agistack-desktop-test-dist/src/api/client.js');

const cloudConfig = {
  mode: 'cloud',
  apiBaseUrl: 'https://api.example.test',
  projectId: 'project-1',
  tenantId: 'tenant-1',
  workspaceId: '',
};

const snapshot = {
  id: 'cloud-change-abc',
  run_id: 'run-1',
  conversation_id: 'conversation-1',
  run_revision: 4,
  environment_id: 'env-1',
  status: 'ready',
  additions: 2,
  deletions: 1,
  files_changed: 1,
  truncated: false,
  captured_at: '2026-01-01T00:00:00Z',
  files: [{ path: 'src/a.py' }],
  scope: 'run',
  turn_id: null,
  snapshot_revision: 'digest-1',
};

test('revert is available only for ready cloud snapshots with a digest', () => {
  assert.equal(changeRevertAvailable(cloudConfig, snapshot), true);
  assert.equal(
    changeRevertAvailable({ ...cloudConfig, mode: 'local' }, snapshot),
    false,
  );
  assert.equal(changeRevertAvailable(cloudConfig, null), false);
  assert.equal(
    changeRevertAvailable(cloudConfig, { ...snapshot, status: 'unattributed' }),
    false,
  );
  assert.equal(
    changeRevertAvailable(cloudConfig, { ...snapshot, snapshot_revision: null }),
    false,
  );
  assert.equal(
    changeRevertAvailable(cloudConfig, { ...snapshot, files: [] }),
    false,
  );
});

test('revert payload pins selectors to the reviewed snapshot digest', () => {
  const payload = buildChangeRevertPayload(
    snapshot,
    { path: 'src/a.py' },
    'key-1',
  );
  assert.deepEqual(payload, {
    expected_run_revision: 4,
    scope: 'run',
    snapshot_digest: 'digest-1',
    idempotency_key: 'key-1',
    selectors: [{ path: 'src/a.py' }],
  });

  const hunkPayload = buildChangeRevertPayload(
    { ...snapshot, scope: 'session' },
    { path: 'src/a.py', hunkIndices: [2] },
    'key-2',
  );
  assert.equal(hunkPayload.scope, 'session');
  assert.deepEqual(hunkPayload.selectors, [
    { path: 'src/a.py', hunk_indices: [2] },
  ]);

  const turnPayload = buildChangeRevertPayload(
    { ...snapshot, scope: 'turn', turn_id: 'turn-9' },
    { path: 'src/a.py' },
    'key-3',
  );
  assert.equal(turnPayload.turn_id, 'turn-9');
});

test('revert payload rejects invalid selectors and missing digests', () => {
  assert.equal(
    buildChangeRevertPayload({ ...snapshot, snapshot_revision: null }, { path: 'a' }, 'k'),
    null,
  );
  assert.equal(buildChangeRevertPayload(snapshot, { path: ' ' }, 'k'), null);
  assert.equal(buildChangeRevertPayload(snapshot, { path: 'a' }, ' '), null);
  assert.equal(
    buildChangeRevertPayload(snapshot, { path: 'a', hunkIndices: [] }, 'k'),
    null,
  );
  assert.equal(
    buildChangeRevertPayload(snapshot, { path: 'a', hunkIndices: [-1] }, 'k'),
    null,
  );
});

test('revert errors map to honest panel notices', () => {
  const stale = changeRevertNoticeFromError(
    new DesktopApiError('conflict', 409, { reason_code: 'snapshot_digest_mismatch' }),
  );
  assert.equal(stale.kind, 'stale');
  assert.equal(stale.reasonCode, 'snapshot_digest_mismatch');

  const unavailable = changeRevertNoticeFromError(
    new DesktopApiError('down', 503, { reason_code: 'sandbox_write_unavailable' }),
  );
  assert.equal(unavailable.kind, 'unavailable');

  const conflict = changeRevertNoticeFromError(
    new DesktopApiError('conflict', 409, { reason_code: 'revert_patch_conflict' }),
  );
  assert.equal(conflict.kind, 'failed');

  assert.equal(changeRevertNoticeFromError(new Error('boom')).kind, 'failed');
});

test('revert target labels describe file and hunk selections', () => {
  assert.equal(revertTargetLabel({ path: 'src/a.py' }), 'src/a.py');
  assert.equal(
    revertTargetLabel({ path: 'src/a.py', hunkIndices: [1] }),
    'src/a.py hunk #2',
  );
});

test('local mode fails closed before any network call', async () => {
  await assert.rejects(
    revertRunChanges(
      { ...cloudConfig, mode: 'local' },
      'run-1',
      { selectors: [] },
      new AbortController().signal,
    ),
    (error) => error instanceof DesktopApiError && error.status === 501,
  );
});

test('changes canvas wires the destructive confirmation gate', () => {
  const source = readFileSync(
    new URL('../src/features/session/SessionChangesCanvas.tsx', import.meta.url),
    'utf8',
  );
  assert.match(source, /role="alertdialog"/);
  assert.match(source, /revert\.requestRevert\(revertTarget\)/);
  assert.match(source, /t\('session\.revertConfirmBody'/);
  assert.match(source, /t\('session\.revertChangeFile'/);
  assert.match(source, /t\('session\.revertChangeHunk'/);
  assert.match(source, /t\(`session\.revertNotice\.\$\{revert\.notice\.kind\}`\)/);
  assert.match(source, /revert\.notice\.kind === 'stale'[\s\S]*?onRefresh\(\)/);
  assert.match(source, /revert\.available \?/);
});

test('revert copy ships in both locales with destructive semantics', () => {
  const source = readFileSync(new URL('../src/i18n.tsx', import.meta.url), 'utf8');
  for (const key of [
    'session.revertConfirmTitle',
    'session.revertConfirmBody',
    'session.revertConfirmAction',
    'session.revertCancelAction',
    'session.revertNotice.stale',
    'session.revertNotice.unavailable',
    'session.revertNotice.failed',
    'session.revertUnavailableLocal',
  ]) {
    assert.equal(
      source.split(`'${key}':`).length - 1,
      2,
      `${key} must exist exactly twice (en + zh)`,
    );
  }
  assert.match(source, /其余改动保持不变/);
  assert.match(source, /All other changes are kept/);
});

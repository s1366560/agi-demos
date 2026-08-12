import assert from 'node:assert/strict';
import { lstatSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

const { createUpdateRecoveryJournal } = await import(
  'file:///tmp/agistack-desktop-test-dist/electron/main/updateRecoveryJournal.js'
);

const payloads = [
  {
    sha512: Buffer.alloc(64, 9).toString('base64'),
    size: 128,
  },
];
const snapshot = {
  manifestSha512: Buffer.alloc(64, 8).toString('base64'),
  manifestSize: 256,
};

function recoveryRecord(overrides = {}) {
  return {
    schemaVersion: 2,
    phase: 'downloaded',
    currentVersion: '0.1.0',
    candidateVersion: '0.2.0',
    recoveryVersion: '0.1.0',
    nonce: 'a'.repeat(64),
    deadlineAt: '2026-08-11T00:05:00.000Z',
    launchAttempts: 0,
    candidateProcessId: null,
    payloads,
    snapshot,
    recordedAt: '2026-08-11T00:00:00.000Z',
    reasonCode: null,
    retryable: false,
    allowedActions: ['restart_to_apply'],
    ...overrides,
  };
}

function withJournal(run) {
  const root = mkdtempSync(join(tmpdir(), 'agistack-update-recovery-'));
  try {
    return run({
      path: join(root, 'updates', 'recovery-journal.v2.json'),
      root,
    });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

test('update recovery journal is private, atomic, bounded, and contains no transport data', () => {
  withJournal(({ path }) => {
    const journal = createUpdateRecoveryJournal(path);
    assert.equal(journal.load(), null);

    journal.write(recoveryRecord());
    assert.deepEqual(journal.load(), recoveryRecord());
    assert.equal(Object.isFrozen(journal.load().payloads), true);
    assert.equal(lstatSync(path).mode & 0o777, 0o600);
    assert.equal(lstatSync(join(path, '..')).mode & 0o777, 0o700);

    const source = readFileSync(path, 'utf8');
    assert.equal(source.includes('http'), false);
    assert.equal(source.includes('token'), false);
    assert.equal(source.includes('path'), false);

    journal.clear();
    assert.equal(journal.load(), null);
  });
});

test('update recovery journal rejects unknown fields, invalid versions, oversized input, and links', () => {
  withJournal(({ path, root }) => {
    const journal = createUpdateRecoveryJournal(path);
    journal.write(
      recoveryRecord({ phase: 'applying', launchAttempts: 1, allowedActions: [] }),
    );

    writeFileSync(
      path,
      JSON.stringify({
        ...recoveryRecord({ phase: 'applying', launchAttempts: 1, allowedActions: [] }),
        downloadUrl: 'https://example.invalid/?token=secret',
      }),
    );
    assert.throws(() => journal.load(), /update recovery journal is invalid/u);

    writeFileSync(path, 'x'.repeat(33_000));
    assert.throws(() => journal.load(), /update recovery journal is too large/u);

    rmSync(path, { force: true });
    const outside = join(root, 'outside.json');
    writeFileSync(outside, '{}');
    symlinkSync(outside, path);
    assert.throws(() => journal.load(), /regular non-symlink/u);
  });
});

test('update recovery journal rejects foreign ownership and mutable payload contracts', () => {
  withJournal(({ path }) => {
    createUpdateRecoveryJournal(path).write(recoveryRecord());
    const foreignJournal = createUpdateRecoveryJournal(path, {
      currentUserId: () => 501,
      fileOwnerId: () => 502,
    });
    assert.throws(() => foreignJournal.load(), /owned by the current user/u);

    const journal = createUpdateRecoveryJournal(path);
    assert.throws(
      () => journal.write(recoveryRecord({ payloads: [] })),
      /update recovery journal is invalid/u,
    );
  });
});

test('update recovery journal binds a candidate PID only while verifying', () => {
  withJournal(({ path }) => {
    const journal = createUpdateRecoveryJournal(path);
    const verifying = recoveryRecord({
      phase: 'verifying',
      launchAttempts: 1,
      candidateProcessId: 4242,
      allowedActions: [],
    });
    journal.write(verifying);
    assert.equal(journal.load().candidateProcessId, 4242);
    assert.throws(
      () => journal.write({ ...verifying, candidateProcessId: null }),
      /update recovery journal is invalid/u,
    );
    assert.throws(
      () => journal.write(recoveryRecord({ candidateProcessId: 4242 })),
      /update recovery journal is invalid/u,
    );
  });
});

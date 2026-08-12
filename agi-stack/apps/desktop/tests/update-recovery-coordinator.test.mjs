import assert from 'node:assert/strict';
import test from 'node:test';

const { createUpdateRecoveryCoordinator } = await import(
  'file:///tmp/agistack-desktop-test-dist/electron/main/updateRecoveryCoordinator.js'
);

const payloads = [
  {
    sha512: Buffer.alloc(64, 4).toString('base64'),
    size: 64,
  },
];
const snapshot = {
  manifestSha512: Buffer.alloc(64, 3).toString('base64'),
  manifestSize: 256,
};

test('recovery coordinator freezes payload evidence and requires a nonce health handshake', () => {
  let stored = null;
  const launches = [];
  const journal = {
    path: '/tmp/agistack-update-recovery-test.json',
    load: () => stored,
    write: (record) => {
      stored = record;
    },
    clear: () => {
      stored = null;
    },
  };
  const coordinator = createUpdateRecoveryCoordinator(journal, {
    now: () => new Date('2026-08-11T00:00:00.000Z'),
    randomNonce: () => 'c'.repeat(64),
    recoveryWindowMs: 60_000,
    launchRecoveryHelper: (record) => launches.push(record),
  });

  const downloaded = coordinator.recordDownloaded({
    currentVersion: '0.1.0',
    candidateVersion: '0.2.0',
    payloads,
    snapshot,
  });
  assert.equal(downloaded.phase, 'downloaded');
  assert.equal(Object.isFrozen(downloaded.payloads), true);
  const applying = coordinator.restartToApply();
  assert.equal(applying.phase, 'applying');
  assert.equal(applying.launchAttempts, 1);
  assert.equal(launches.length, 1);

  const restarted = createUpdateRecoveryCoordinator(journal, {
    now: () => new Date('2026-08-11T00:00:01.000Z'),
    candidateProcessId: () => 4242,
  });
  assert.equal(restarted.loadForStartup('0.2.0').candidateProcessId, 4242);
  assert.throws(
    () => restarted.confirmHealthy({ currentVersion: '0.2.0', nonce: 'd'.repeat(64) }),
    /health nonce mismatch/u,
  );
  assert.equal(stored.phase, 'verifying');
  assert.equal(
    restarted.confirmHealthy({ currentVersion: '0.2.0', nonce: 'c'.repeat(64) }).phase,
    'recovered',
  );
});

test('recovery coordinator fails closed on deadline without claiming OS rollback', () => {
  let stored = {
    schemaVersion: 2,
    phase: 'applying',
    currentVersion: '0.1.0',
    candidateVersion: '0.2.0',
    recoveryVersion: '0.1.0',
    nonce: 'e'.repeat(64),
    deadlineAt: '2026-08-11T00:00:01.000Z',
    launchAttempts: 1,
    candidateProcessId: null,
    payloads,
    snapshot,
    recordedAt: '2026-08-11T00:00:00.000Z',
    reasonCode: null,
    retryable: false,
    allowedActions: [],
  };
  const coordinator = createUpdateRecoveryCoordinator(
    {
      path: '/tmp/agistack-update-recovery-test.json',
      load: () => stored,
      write: (record) => {
        stored = record;
      },
      clear: () => undefined,
    },
    { now: () => new Date('2026-08-11T00:00:02.000Z') },
  );

  assert.equal(coordinator.loadForStartup('0.1.0').phase, 'failed');
  assert.equal(stored.reasonCode, 'update_recovery_deadline_expired');
  assert.equal(stored.retryable, true);
  assert.deepEqual(stored.allowedActions, ['restart_to_apply']);
  assert.equal(JSON.stringify(stored).includes('rollback_passed'), false);
});

test('recovery coordinator accepts an actual restored N record without claiming N+1', () => {
  const stored = {
    schemaVersion: 2,
    phase: 'recovered',
    currentVersion: '0.1.0',
    candidateVersion: '0.2.0',
    recoveryVersion: '0.1.0',
    nonce: 'f'.repeat(64),
    deadlineAt: '2026-08-11T00:05:00.000Z',
    launchAttempts: 1,
    candidateProcessId: null,
    payloads,
    snapshot,
    recordedAt: '2026-08-11T00:01:00.000Z',
    reasonCode: null,
    retryable: false,
    allowedActions: ['check'],
  };
  const coordinator = createUpdateRecoveryCoordinator({
    path: '/tmp/agistack-update-recovery-test.json',
    load: () => stored,
    write: () => assert.fail('matching recovered N must not be rewritten'),
    clear: () => undefined,
  });
  assert.equal(coordinator.loadForStartup('0.1.0').currentVersion, '0.1.0');
});

test('an expired candidate preserves helper authority instead of overwriting the journal', () => {
  let stored = {
    schemaVersion: 2,
    phase: 'applying',
    currentVersion: '0.1.0',
    candidateVersion: '0.2.0',
    recoveryVersion: '0.1.0',
    nonce: '9'.repeat(64),
    deadlineAt: '2026-08-11T00:00:01.000Z',
    launchAttempts: 1,
    candidateProcessId: null,
    payloads,
    snapshot,
    recordedAt: '2026-08-11T00:00:00.000Z',
    reasonCode: null,
    retryable: false,
    allowedActions: [],
  };
  const coordinator = createUpdateRecoveryCoordinator(
    {
      path: '/tmp/agistack-update-recovery-test.json',
      load: () => stored,
      write: (record) => {
        stored = record;
      },
      clear: () => undefined,
    },
    {
      now: () => new Date('2026-08-11T00:00:02.000Z'),
      candidateProcessId: () => 5151,
    },
  );

  assert.equal(coordinator.loadForStartup('0.2.0').candidateProcessId, 5151);
  assert.throws(
    () => coordinator.confirmHealthy({ currentVersion: '0.2.0', nonce: '9'.repeat(64) }),
    /health deadline expired/u,
  );
  assert.equal(stored.phase, 'verifying');
  assert.equal(stored.candidateProcessId, 5151);
});

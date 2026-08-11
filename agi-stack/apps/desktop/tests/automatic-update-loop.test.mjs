import assert from 'node:assert/strict';
import test from 'node:test';

const { startAutomaticUpdateLoop } = await import(
  'file:///tmp/agistack-desktop-test-dist/electron/main/automaticUpdateLoop.js'
);

const payloads = [
  {
    sha512: Buffer.alloc(64, 7).toString('base64'),
    size: 42,
  },
];
const snapshot = {
  manifestSha512: Buffer.alloc(64, 6).toString('base64'),
  manifestSize: 256,
};

test('automatic updates expose the locked lifecycle and restart-to-apply authority', async () => {
  const listeners = new Map();
  const reports = [];
  const journalRecords = [];
  const helperLaunches = [];
  let journalCurrent = null;
  let checks = 0;
  let installs = 0;
  let scheduledCheck;
  let cancelledHandle = null;
  let unrefCalled = false;
  const intervalHandle = {
    unref: () => {
      unrefCalled = true;
    },
  };
  const updateClient = {
    autoDownload: false,
    autoInstallOnAppQuit: false,
    checkForUpdatesAndNotify: async () => {
      checks += 1;
    },
    quitAndInstall: () => {
      installs += 1;
    },
    on: (event, listener) => listeners.set(event, listener),
    removeListener: (event, listener) => {
      if (listeners.get(event) === listener) listeners.delete(event);
    },
  };

  const controller = startAutomaticUpdateLoop(updateClient, {
    currentVersion: '0.1.0',
    now: () => new Date('2026-08-11T00:00:00.000Z'),
    randomNonce: () => 'a'.repeat(64),
    recoveryWindowMs: 60_000,
    launchRecoveryHelper: (record) => helperLaunches.push(record),
    prepareRecoverySnapshot: async () => snapshot,
    journal: {
      path: '/tmp/agistack-update-recovery-test.json',
      load: () => journalCurrent,
      write: (record) => {
        journalCurrent = record;
        journalRecords.push(record);
      },
      clear: () => {
        journalCurrent = null;
      },
    },
    intervalMs: 42,
    schedule: (callback, intervalMs) => {
      assert.equal(intervalMs, 42);
      scheduledCheck = callback;
      return intervalHandle;
    },
    cancel: (handle) => {
      cancelledHandle = handle;
    },
    report: (message) => reports.push(message),
  });

  await Promise.resolve();
  assert.equal(checks, 1);
  assert.equal(controller.getState().phase, 'checking');
  assert.deepEqual(controller.getState().allowedActions, []);
  assert.equal(updateClient.autoDownload, true);
  assert.equal(updateClient.autoInstallOnAppQuit, false);
  assert.equal(unrefCalled, true);
  assert.equal(typeof listeners.get('error'), 'function');

  listeners.get('update-available')({ version: '0.2.0', files: payloads });
  assert.equal(controller.getState().phase, 'available');
  listeners.get('download-progress')({ percent: 37.5 });
  assert.equal(controller.getState().phase, 'downloading');
  assert.equal(controller.getState().progress, 37.5);
  listeners.get('update-downloaded')({ version: '0.2.0', files: payloads });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(controller.getState().phase, 'downloaded');
  assert.equal(journalRecords.at(-1).phase, 'downloaded');
  assert.deepEqual(controller.getState().allowedActions, ['restart_to_apply']);

  controller.restartToApply();
  assert.equal(controller.getState().phase, 'applying');
  assert.equal(journalRecords.at(-1).phase, 'applying');
  assert.equal(journalRecords.at(-1).launchAttempts, 1);
  assert.equal(helperLaunches.length, 1);
  assert.equal(installs, 1);

  scheduledCheck();
  await Promise.resolve();
  assert.equal(checks, 1);
  listeners.get('error')();
  assert.deepEqual(reports, ['automatic update operation failed']);

  controller.stop();
  controller.stop();
  assert.equal(cancelledHandle, intervalHandle);
  assert.equal(listeners.size, 0);
});

test('automatic update failures are redacted before reporting', async () => {
  const reports = [];
  const updateClient = {
    autoDownload: false,
    autoInstallOnAppQuit: false,
    checkForUpdatesAndNotify: async () => {
      throw new Error('release URL with a sensitive query value');
    },
    quitAndInstall: () => undefined,
    on: () => undefined,
    removeListener: () => undefined,
  };

  const controller = startAutomaticUpdateLoop(updateClient, {
    currentVersion: '0.1.0',
    schedule: () => ({ unref: () => undefined }),
    cancel: () => undefined,
    report: (message) => reports.push(message),
  });
  await new Promise((resolve) => setImmediate(resolve));
  controller.stop();

  assert.deepEqual(reports, ['automatic update check failed']);
  assert.equal(controller.getState().phase, 'failed');
  assert.equal(controller.getState().reasonCode, 'update_check_failed');
  assert.equal(controller.getState().retryable, true);
  assert.deepEqual(controller.getState().allowedActions, ['check']);
  assert.equal(JSON.stringify(controller.getState()).includes('sensitive'), false);
});

test('a restarted candidate verifies nonce-bound health before claiming recovered', () => {
  const listeners = new Map();
  const updateClient = {
    autoDownload: false,
    autoInstallOnAppQuit: false,
    checkForUpdatesAndNotify: async () => undefined,
    quitAndInstall: () => undefined,
    on: (event, listener) => listeners.set(event, listener),
    removeListener: (event, listener) => {
      if (listeners.get(event) === listener) listeners.delete(event);
    },
  };
  let journalCurrent = {
    schemaVersion: 2,
    phase: 'applying',
    currentVersion: '0.1.0',
    candidateVersion: '0.2.0',
    recoveryVersion: '0.1.0',
    nonce: 'b'.repeat(64),
    deadlineAt: '2026-08-11T00:05:00.000Z',
    launchAttempts: 1,
    payloads,
    snapshot,
    recordedAt: '2026-08-11T00:00:00.000Z',
    reasonCode: null,
    retryable: false,
    allowedActions: [],
  };
  const journalRecords = [];
  let cleanupCalls = 0;
  const controller = startAutomaticUpdateLoop(updateClient, {
    currentVersion: '0.2.0',
    now: () => new Date('2026-08-11T00:00:01.000Z'),
    journal: {
      path: '/tmp/agistack-update-recovery-test.json',
      load: () => journalCurrent,
      write: (record) => {
        journalCurrent = record;
        journalRecords.push(record);
      },
      clear: () => {
        journalCurrent = null;
      },
    },
    schedule: () => ({ unref: () => undefined }),
    cancel: () => undefined,
    clearRecoverySnapshot: () => {
      cleanupCalls += 1;
    },
  });

  assert.equal(controller.getState().phase, 'verifying');
  assert.equal(controller.getState().currentVersion, '0.2.0');
  assert.equal(controller.getState().candidateVersion, '0.2.0');
  controller.confirmHealthy();
  assert.equal(controller.getState().phase, 'recovered');
  assert.equal(journalRecords.at(-1).phase, 'recovered');
  assert.equal(cleanupCalls, 1);
  assert.throws(() => controller.restartToApply(), /update is not ready to apply/u);
  controller.stop();
});

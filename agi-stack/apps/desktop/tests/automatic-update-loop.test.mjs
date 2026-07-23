import assert from 'node:assert/strict';
import test from 'node:test';

const { startAutomaticUpdateLoop } = await import(
  'file:///tmp/agistack-desktop-test-dist/electron/main/automaticUpdateLoop.js'
);

test('automatic updates check immediately, repeat, and clean up only owned listeners', async () => {
  const listeners = new Map();
  const reports = [];
  let checks = 0;
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
    on: (event, listener) => listeners.set(event, listener),
    removeListener: (event, listener) => {
      if (listeners.get(event) === listener) listeners.delete(event);
    },
  };

  const stop = startAutomaticUpdateLoop(updateClient, {
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
  assert.equal(updateClient.autoDownload, true);
  assert.equal(updateClient.autoInstallOnAppQuit, true);
  assert.equal(unrefCalled, true);
  assert.equal(typeof listeners.get('error'), 'function');

  scheduledCheck();
  await Promise.resolve();
  assert.equal(checks, 2);
  listeners.get('error')();
  assert.deepEqual(reports, ['automatic update operation failed']);

  stop();
  stop();
  assert.equal(cancelledHandle, intervalHandle);
  assert.equal(listeners.has('error'), false);
});

test('automatic update failures are redacted before reporting', async () => {
  const reports = [];
  const updateClient = {
    autoDownload: false,
    autoInstallOnAppQuit: false,
    checkForUpdatesAndNotify: async () => {
      throw new Error('release URL with a sensitive query value');
    },
    on: () => undefined,
    removeListener: () => undefined,
  };

  const stop = startAutomaticUpdateLoop(updateClient, {
    schedule: () => ({ unref: () => undefined }),
    cancel: () => undefined,
    report: (message) => reports.push(message),
  });
  await new Promise((resolve) => setImmediate(resolve));
  stop();

  assert.deepEqual(reports, ['automatic update check failed']);
});

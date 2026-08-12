import assert from 'node:assert/strict';
import test from 'node:test';

const { resolveUpdateRecoveryInstallation } = await import(
  'file:///tmp/agistack-desktop-test-dist/electron/main/updateRecoveryInstallation.js'
);

test('recovery installation resolves signed macOS bundles and Windows per-user roots', () => {
  assert.deepEqual(
    resolveUpdateRecoveryInstallation({
      platform: 'darwin',
      executablePath: '/Applications/MemStack.app/Contents/MacOS/MemStack',
    }),
    {
      management: 'application',
      targetKind: 'directory',
      targetPath: '/Applications/MemStack.app',
      launchRelativePath: 'Contents/MacOS/MemStack',
    },
  );
  assert.deepEqual(
    resolveUpdateRecoveryInstallation({
      platform: 'win32',
      executablePath: 'C:\\Users\\qa\\AppData\\Local\\Programs\\MemStack\\MemStack.exe',
    }),
    {
      management: 'application',
      targetKind: 'directory',
      targetPath: 'C:\\Users\\qa\\AppData\\Local\\Programs\\MemStack',
      launchRelativePath: 'MemStack.exe',
    },
  );
});

test('recovery installation distinguishes AppImage from externally managed deb', () => {
  assert.deepEqual(
    resolveUpdateRecoveryInstallation({
      platform: 'linux',
      executablePath: '/tmp/.mount_memstack/MemStack',
      appImagePath: '/home/qa/Applications/MemStack.AppImage',
    }),
    {
      management: 'application',
      targetKind: 'file',
      targetPath: '/home/qa/Applications/MemStack.AppImage',
      launchRelativePath: '.',
    },
  );
  assert.deepEqual(
    resolveUpdateRecoveryInstallation({
      platform: 'linux',
      executablePath: '/opt/MemStack/memstack',
    }),
    {
      management: 'externally_managed',
      reasonCode: 'updates_externally_managed',
    },
  );
});

import { spawnSync } from 'node:child_process';
import { chmodSync, copyFileSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join, resolve } from 'node:path';

const helperPath = resolve(
  process.env.AGISTACK_RECOVERY_HELPER_PATH ??
    join(
      import.meta.dirname,
      '..',
      'build',
      'sidecar',
      process.platform === 'win32'
        ? 'agistack-desktop-sidecar.exe'
        : 'agistack-desktop-sidecar',
    ),
);
const root = mkdtempSync(join(tmpdir(), 'agistack-update-recovery-smoke-'));

function privateJson(path, value) {
  writeFileSync(path, `${JSON.stringify(value)}\n`, { encoding: 'utf8', mode: 0o600 });
  chmodSync(path, 0o600);
}

function helperEnvironment(requestPath) {
  return {
    PATH: process.env.PATH ?? '',
    ...(process.platform === 'win32'
      ? {
          SystemRoot: process.env.SystemRoot ?? '',
          ComSpec: process.env.ComSpec ?? '',
        }
      : {}),
    AGISTACK_UPDATE_RECOVERY_REQUEST: requestPath,
  };
}

try {
  const ownedRoot = join(root, 'owned');
  const targetPath = join(root, 'installation');
  const snapshotRoot = join(ownedRoot, 'snapshot');
  const manifestPath = join(snapshotRoot, 'manifest.json');
  const journalPath = join(root, 'recovery-journal.v2.json');
  const executableName = basename(helperPath);
  mkdirSync(ownedRoot, { recursive: true, mode: 0o700 });
  mkdirSync(targetPath, { recursive: true });
  chmodSync(ownedRoot, 0o700);
  copyFileSync(helperPath, join(targetPath, executableName));
  if (process.platform !== 'win32') chmodSync(join(targetPath, executableName), 0o700);
  writeFileSync(join(targetPath, 'version.txt'), '0.1.0');

  const prepareRequest = join(root, 'prepare.json');
  privateJson(prepareRequest, {
    operation: 'prepare',
    schemaVersion: 1,
    targetPath,
    ownedRoot,
    snapshotRoot,
    manifestPath,
  });
  const prepared = spawnSync(helperPath, ['--update-recovery-prepare'], {
    encoding: 'utf8',
    env: helperEnvironment(prepareRequest),
    timeout: 120_000,
    windowsHide: true,
  });
  if (prepared.status !== 0) throw new Error('recovery snapshot preparation failed');
  const snapshot = JSON.parse(prepared.stdout);

  writeFileSync(join(targetPath, 'version.txt'), '0.1.1');
  const now = Date.now();
  const nonce = 'a'.repeat(64);
  privateJson(journalPath, {
    schemaVersion: 2,
    phase: 'applying',
    currentVersion: '0.1.0',
    candidateVersion: '0.1.1',
    recoveryVersion: '0.1.0',
    nonce,
    deadlineAt: new Date(now - 1_000).toISOString(),
    launchAttempts: 1,
    payloads: [{ sha512: Buffer.alloc(64, 7).toString('base64'), size: 64 }],
    snapshot: {
      manifestSha512: snapshot.manifestSha512,
      manifestSize: snapshot.manifestSize,
    },
    recordedAt: new Date(now - 2_000).toISOString(),
    reasonCode: null,
    retryable: false,
    allowedActions: [],
  });
  const monitorRequest = join(root, 'monitor.json');
  privateJson(monitorRequest, {
    operation: 'monitor',
    schemaVersion: 1,
    journalPath,
    expectedNonce: nonce,
    ownedRoot,
    snapshotRoot,
    manifestPath,
    manifestSha512: snapshot.manifestSha512,
    manifestSize: snapshot.manifestSize,
    targetPath,
    launchRelativePath: executableName,
  });
  const recovered = spawnSync(helperPath, ['--update-recovery-helper'], {
    encoding: 'utf8',
    env: helperEnvironment(monitorRequest),
    timeout: 120_000,
    windowsHide: true,
  });
  if (recovered.status !== 0) throw new Error('recovery helper failed');
  const journal = JSON.parse(readFileSync(journalPath, 'utf8'));
  if (
    readFileSync(join(targetPath, 'version.txt'), 'utf8') !== '0.1.0' ||
    journal.phase !== 'recovered' ||
    journal.currentVersion !== '0.1.0'
  ) {
    throw new Error('recovery helper did not restore the verified N snapshot');
  }
  process.stdout.write('update recovery smoke passed\n');
} finally {
  rmSync(root, { recursive: true, force: true });
}

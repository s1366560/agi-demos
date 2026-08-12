import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';

const { clearPreparedUpdateRecovery } = await import(
  'file:///tmp/agistack-desktop-test-dist/electron/main/updateRecoveryProcess.js'
);

test('healthy update cleanup removes only the owned snapshot and plan', () => {
  const ownedRoot = mkdtempSync(join(tmpdir(), 'agistack-update-cleanup-'));
  try {
    const helperPath = join(ownedRoot, 'helpers', '0.1.0', 'digest', 'sidecar');
    const snapshotRoot = join(ownedRoot, 'snapshots', '0.1.0', 'snapshot');
    const manifestPath = join(snapshotRoot, 'manifest.json');
    mkdirSync(dirname(helperPath), { recursive: true });
    mkdirSync(snapshotRoot, { recursive: true });
    writeFileSync(helperPath, 'signed helper fixture');
    writeFileSync(manifestPath, '{}');
    writeFileSync(
      join(ownedRoot, 'recovery-plan.v1.json'),
      JSON.stringify({
        schemaVersion: 1,
        helperPath,
        helperSha512: Buffer.alloc(64, 1).toString('base64'),
        ownedRoot,
        snapshotRoot,
        manifestPath,
        manifestSha512: Buffer.alloc(64, 2).toString('base64'),
        manifestSize: 2,
        targetPath: '/Applications/MemStack.app',
        launchRelativePath: 'Contents/MacOS/MemStack',
      }),
      { mode: 0o600 },
    );

    clearPreparedUpdateRecovery(ownedRoot);

    assert.equal(existsSync(snapshotRoot), false);
    assert.equal(existsSync(join(ownedRoot, 'recovery-plan.v1.json')), false);
    assert.equal(existsSync(helperPath), true);
  } finally {
    rmSync(ownedRoot, { recursive: true, force: true });
  }
});

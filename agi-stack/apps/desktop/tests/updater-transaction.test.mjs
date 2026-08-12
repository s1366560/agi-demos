import assert from 'node:assert/strict';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';

import { applyUpdateWithRollback } from '../scripts/updater-transaction.mjs';

async function seedVersion(root, name, version) {
  const directory = join(root, name);
  await mkdir(directory);
  await writeFile(join(directory, 'version.txt'), version, 'utf8');
  return directory;
}

test('transactional updater applies a staged package and removes the rollback copy after validation', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agistack-updater-apply-'));
  const installed = await seedVersion(root, 'current', '1.0.0');
  const staged = await seedVersion(root, 'staged', '1.1.0');
  try {
    const result = await applyUpdateWithRollback({
      installedPath: installed,
      stagedPath: staged,
      validate: async (path) => (await readFile(join(path, 'version.txt'), 'utf8')) === '1.1.0',
    });

    assert.deepEqual(result, { applied: true, rolledBack: false });
    assert.equal(await readFile(join(installed, 'version.txt'), 'utf8'), '1.1.0');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test('transactional updater restores the previous package when post-apply validation fails', async () => {
  const root = await mkdtemp(join(tmpdir(), 'agistack-updater-rollback-'));
  const installed = await seedVersion(root, 'current', '1.0.0');
  const staged = await seedVersion(root, 'staged', '1.1.0-corrupt');
  try {
    await assert.rejects(
      applyUpdateWithRollback({
        installedPath: installed,
        stagedPath: staged,
        validate: async () => false,
      }),
      /update validation failed; previous installation restored/u,
    );
    assert.equal(await readFile(join(installed, 'version.txt'), 'utf8'), '1.0.0');
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

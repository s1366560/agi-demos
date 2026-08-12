import { randomUUID } from 'node:crypto';
import { lstat, rename, rm } from 'node:fs/promises';
import { basename, dirname, isAbsolute, parse, resolve } from 'node:path';

function assertTransactionalPath(path, label) {
  if (typeof path !== 'string' || !isAbsolute(path)) {
    throw new Error(`${label} must be an absolute path`);
  }
  const normalized = resolve(path);
  if (normalized === parse(normalized).root || basename(normalized) === '') {
    throw new Error(`${label} must not be a filesystem root`);
  }
  return normalized;
}

async function assertRegularDirectory(path, label) {
  const value = await lstat(path);
  if (!value.isDirectory() || value.isSymbolicLink()) {
    throw new Error(`${label} must be a real directory`);
  }
}

async function restorePreviousInstallation({ installed, backup, failed }) {
  await rename(installed, failed);
  try {
    await rename(backup, installed);
  } catch (rollbackError) {
    try {
      await rename(failed, installed);
    } catch {
      // Preserve every remaining path for operator-led recovery.
    }
    throw new AggregateError(
      [rollbackError],
      'update validation failed and automatic rollback could not restore the previous installation',
    );
  }
  await rm(failed, { recursive: true, force: true });
}

/**
 * Apply an already verified update using same-filesystem renames.
 *
 * This primitive is intentionally independent of the update feed. Production
 * metadata/signature verification happens before staging; this function owns
 * only the reversible on-disk transition and post-apply validation.
 */
export async function applyUpdateWithRollback({ installedPath, stagedPath, validate }) {
  if (typeof validate !== 'function') {
    throw new Error('update validation callback is required');
  }
  const installed = assertTransactionalPath(installedPath, 'installed path');
  const staged = assertTransactionalPath(stagedPath, 'staged path');
  if (installed === staged || dirname(installed) !== dirname(staged)) {
    throw new Error('installed and staged paths must be distinct siblings');
  }
  await assertRegularDirectory(installed, 'installed path');
  await assertRegularDirectory(staged, 'staged path');

  const suffix = randomUUID();
  const backup = `${installed}.rollback-${suffix}`;
  const failed = `${installed}.failed-${suffix}`;
  await rename(installed, backup);
  try {
    await rename(staged, installed);
  } catch (applyError) {
    await rename(backup, installed);
    throw new AggregateError([applyError], 'update apply failed; previous installation restored');
  }

  let valid = false;
  try {
    valid = (await validate(installed)) === true;
  } catch {
    valid = false;
  }
  if (!valid) {
    await restorePreviousInstallation({ installed, backup, failed });
    throw new Error('update validation failed; previous installation restored');
  }

  await rm(backup, { recursive: true, force: true });
  return Object.freeze({ applied: true, rolledBack: false });
}

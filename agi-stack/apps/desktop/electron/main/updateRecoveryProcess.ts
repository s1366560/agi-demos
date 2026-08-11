import { execFile, spawn } from 'node:child_process';
import { createHash, randomUUID } from 'node:crypto';
import {
  chmodSync,
  closeSync,
  copyFileSync,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  renameSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { basename, dirname, isAbsolute, join, relative } from 'node:path';

import type { UpdateRecoveryInstallation } from './updateRecoveryInstallation';
import type {
  UpdateRecoveryRecord,
  UpdateRecoverySnapshot,
} from './updateRecoveryJournal';

const REQUEST_ENV = 'AGISTACK_UPDATE_RECOVERY_REQUEST';
const PLAN_SCHEMA_VERSION = 1 as const;
const MAX_HELPER_OUTPUT_BYTES = 8 * 1024;
const MAX_PLAN_BYTES = 32 * 1024;
const HELPER_TIMEOUT_MS = 30 * 60 * 1_000;

type RecoveryPlan = Readonly<{
  schemaVersion: typeof PLAN_SCHEMA_VERSION;
  helperPath: string;
  helperSha512: string;
  ownedRoot: string;
  snapshotRoot: string;
  manifestPath: string;
  manifestSha512: string;
  manifestSize: number;
  targetPath: string;
  launchRelativePath: string;
}>;

export type RecoveryHelperLaunch = Readonly<{ pid: number }>;

function canonicalSha512(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const bytes = Buffer.from(value, 'base64');
  return bytes.byteLength === 64 && bytes.toString('base64') === value;
}

function safeRelativePath(value: unknown): value is string {
  return (
    value === '.' ||
    (typeof value === 'string' &&
      value.length > 0 &&
      !value.includes('\\') &&
      !value.split('/').some((segment) => segment === '' || segment === '.' || segment === '..'))
  );
}

function assertOwnedPath(ownedRoot: string, path: string): void {
  const relativePath = relative(ownedRoot, path);
  if (
    !isAbsolute(ownedRoot) ||
    !isAbsolute(path) ||
    !relativePath ||
    relativePath === '..' ||
    relativePath.startsWith(`..${process.platform === 'win32' ? '\\' : '/'}`) ||
    isAbsolute(relativePath)
  ) {
    throw new Error('update recovery owned path is invalid');
  }
}

function privateDirectory(path: string): void {
  mkdirSync(path, { recursive: true, mode: 0o700 });
  const metadata = lstatSync(path);
  if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
    throw new Error('update recovery directory is invalid');
  }
  chmodSync(path, 0o700);
}

function syncDirectory(path: string): void {
  let descriptor: number | null = null;
  try {
    descriptor = openSync(path, 'r');
    fsyncSync(descriptor);
  } catch {
    // Windows filesystems can reject directory fsync. Each file is fsynced
    // before rename and the physical-machine gate validates Windows ACLs.
  } finally {
    if (descriptor !== null) closeSync(descriptor);
  }
}

function writePrivateJson(path: string, value: unknown): void {
  const directory = dirname(path);
  privateDirectory(directory);
  const source = `${JSON.stringify(value)}\n`;
  if (Buffer.byteLength(source) > MAX_PLAN_BYTES) {
    throw new Error('update recovery private record is too large');
  }
  const temporaryPath = join(directory, `.recovery-record.${randomUUID()}.tmp`);
  let descriptor: number | null = null;
  try {
    descriptor = openSync(temporaryPath, 'wx', 0o600);
    writeFileSync(descriptor, source, 'utf8');
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = null;
    renameSync(temporaryPath, path);
    chmodSync(path, 0o600);
    syncDirectory(directory);
  } finally {
    if (descriptor !== null) closeSync(descriptor);
    rmSync(temporaryPath, { force: true });
  }
}

function digestFile(path: string): string {
  const metadata = lstatSync(path);
  if (!metadata.isFile() || metadata.isSymbolicLink()) {
    throw new Error('update recovery helper must be a regular file');
  }
  return createHash('sha512').update(readFileSync(path)).digest('base64');
}

function helperEnvironment(requestPath: string): NodeJS.ProcessEnv {
  return Object.freeze({
    PATH: process.env.PATH ?? '',
    ...(process.platform === 'win32'
      ? {
          SystemRoot: process.env.SystemRoot ?? '',
          ComSpec: process.env.ComSpec ?? '',
        }
      : {}),
    [REQUEST_ENV]: requestPath,
  });
}

function stableHelperCopy(input: Readonly<{
  sourcePath: string;
  ownedRoot: string;
  currentVersion: string;
}>): Readonly<{ helperPath: string; helperSha512: string }> {
  if (!isAbsolute(input.sourcePath) || !existsSync(input.sourcePath)) {
    throw new Error('update recovery helper source is invalid');
  }
  const helperSha512 = digestFile(input.sourcePath);
  const digestDirectory = Buffer.from(helperSha512, 'base64').toString('hex');
  const helperDirectory = join(
    input.ownedRoot,
    'helpers',
    input.currentVersion,
    digestDirectory,
  );
  assertOwnedPath(input.ownedRoot, helperDirectory);
  privateDirectory(helperDirectory);
  const helperPath = join(helperDirectory, basename(input.sourcePath));
  if (!existsSync(helperPath)) {
    const temporaryPath = join(helperDirectory, `.helper.${randomUUID()}.tmp`);
    try {
      copyFileSync(input.sourcePath, temporaryPath);
      chmodSync(temporaryPath, 0o700);
      if (digestFile(temporaryPath) !== helperSha512) {
        throw new Error('update recovery helper copy digest does not match');
      }
      renameSync(temporaryPath, helperPath);
      syncDirectory(helperDirectory);
    } finally {
      rmSync(temporaryPath, { force: true });
    }
  }
  if (digestFile(helperPath) !== helperSha512) {
    throw new Error('update recovery helper identity does not match');
  }
  chmodSync(helperPath, 0o700);
  return Object.freeze({ helperPath, helperSha512 });
}

function runPreparationHelper(helperPath: string, requestPath: string): Promise<unknown> {
  return new Promise((resolvePromise, reject) => {
    execFile(
      helperPath,
      ['--update-recovery-prepare'],
      {
        encoding: 'utf8',
        env: helperEnvironment(requestPath),
        maxBuffer: MAX_HELPER_OUTPUT_BYTES,
        timeout: HELPER_TIMEOUT_MS,
        windowsHide: true,
      },
      (error, stdout) => {
        rmSync(requestPath, { force: true });
        if (error) {
          reject(new Error('update recovery snapshot helper failed'));
          return;
        }
        try {
          resolvePromise(JSON.parse(stdout));
        } catch {
          reject(new Error('update recovery snapshot helper output is invalid'));
        }
      },
    );
  });
}

function parseSnapshotEvidence(value: unknown): UpdateRecoverySnapshot {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('update recovery snapshot evidence is invalid');
  }
  const record = value as Record<string, unknown>;
  if (
    record.schemaVersion !== PLAN_SCHEMA_VERSION ||
    !canonicalSha512(record.manifestSha512) ||
    !Number.isSafeInteger(record.manifestSize) ||
    (record.manifestSize as number) <= 0
  ) {
    throw new Error('update recovery snapshot evidence is invalid');
  }
  return Object.freeze({
    manifestSha512: record.manifestSha512,
    manifestSize: record.manifestSize as number,
  });
}

export async function prepareUpdateRecoverySnapshot(input: Readonly<{
  helperSourcePath: string;
  journalPath: string;
  ownedRoot: string;
  currentVersion: string;
  installation: Extract<UpdateRecoveryInstallation, { management: 'application' }>;
}>): Promise<UpdateRecoverySnapshot> {
  if (!isAbsolute(input.journalPath) || !isAbsolute(input.ownedRoot)) {
    throw new Error('update recovery preparation path is invalid');
  }
  privateDirectory(input.ownedRoot);
  const helper = stableHelperCopy({
    sourcePath: input.helperSourcePath,
    ownedRoot: input.ownedRoot,
    currentVersion: input.currentVersion,
  });
  const snapshotRoot = join(
    input.ownedRoot,
    'snapshots',
    input.currentVersion,
    randomUUID(),
  );
  const manifestPath = join(snapshotRoot, 'manifest.json');
  assertOwnedPath(input.ownedRoot, snapshotRoot);
  const requestPath = join(input.ownedRoot, 'requests', `${randomUUID()}.json`);
  writePrivateJson(requestPath, {
    operation: 'prepare',
    schemaVersion: PLAN_SCHEMA_VERSION,
    targetPath: input.installation.targetPath,
    ownedRoot: input.ownedRoot,
    snapshotRoot,
    manifestPath,
  });
  const snapshot = parseSnapshotEvidence(
    await runPreparationHelper(helper.helperPath, requestPath),
  );
  const plan: RecoveryPlan = Object.freeze({
    schemaVersion: PLAN_SCHEMA_VERSION,
    helperPath: helper.helperPath,
    helperSha512: helper.helperSha512,
    ownedRoot: input.ownedRoot,
    snapshotRoot,
    manifestPath,
    manifestSha512: snapshot.manifestSha512,
    manifestSize: snapshot.manifestSize,
    targetPath: input.installation.targetPath,
    launchRelativePath: input.installation.launchRelativePath,
  });
  writePrivateJson(join(input.ownedRoot, 'recovery-plan.v1.json'), plan);
  return snapshot;
}

function loadRecoveryPlan(ownedRoot: string): RecoveryPlan {
  const planPath = join(ownedRoot, 'recovery-plan.v1.json');
  const metadata = lstatSync(planPath);
  if (!metadata.isFile() || metadata.isSymbolicLink() || metadata.size > MAX_PLAN_BYTES) {
    throw new Error('update recovery plan identity is invalid');
  }
  chmodSync(planPath, 0o600);
  let value: unknown;
  try {
    value = JSON.parse(readFileSync(planPath, 'utf8'));
  } catch {
    throw new Error('update recovery plan is invalid');
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('update recovery plan is invalid');
  }
  const plan = value as Record<string, unknown>;
  if (
    plan.schemaVersion !== PLAN_SCHEMA_VERSION ||
    typeof plan.helperPath !== 'string' ||
    typeof plan.ownedRoot !== 'string' ||
    plan.ownedRoot !== ownedRoot ||
    typeof plan.snapshotRoot !== 'string' ||
    typeof plan.manifestPath !== 'string' ||
    typeof plan.targetPath !== 'string' ||
    !safeRelativePath(plan.launchRelativePath) ||
    !canonicalSha512(plan.helperSha512) ||
    !canonicalSha512(plan.manifestSha512) ||
    !Number.isSafeInteger(plan.manifestSize) ||
    (plan.manifestSize as number) <= 0
  ) {
    throw new Error('update recovery plan is invalid');
  }
  assertOwnedPath(ownedRoot, plan.helperPath);
  assertOwnedPath(ownedRoot, plan.snapshotRoot);
  assertOwnedPath(ownedRoot, plan.manifestPath);
  if (!isAbsolute(plan.targetPath)) throw new Error('update recovery target path is invalid');
  return Object.freeze(plan as RecoveryPlan);
}

export function launchUpdateRecoveryHelper(input: Readonly<{
  ownedRoot: string;
  journalPath: string;
  record: UpdateRecoveryRecord;
}>): RecoveryHelperLaunch {
  if (!isAbsolute(input.ownedRoot) || !isAbsolute(input.journalPath)) {
    throw new Error('update recovery helper path is invalid');
  }
  const plan = loadRecoveryPlan(input.ownedRoot);
  if (
    digestFile(plan.helperPath) !== plan.helperSha512 ||
    plan.manifestSha512 !== input.record.snapshot.manifestSha512 ||
    plan.manifestSize !== input.record.snapshot.manifestSize
  ) {
    throw new Error('update recovery helper evidence does not match');
  }
  const requestPath = join(input.ownedRoot, 'requests', `${randomUUID()}.json`);
  writePrivateJson(requestPath, {
    operation: 'monitor',
    schemaVersion: PLAN_SCHEMA_VERSION,
    journalPath: input.journalPath,
    expectedNonce: input.record.nonce,
    ownedRoot: plan.ownedRoot,
    snapshotRoot: plan.snapshotRoot,
    manifestPath: plan.manifestPath,
    manifestSha512: plan.manifestSha512,
    manifestSize: plan.manifestSize,
    targetPath: plan.targetPath,
    launchRelativePath: plan.launchRelativePath,
  });
  const child = spawn(plan.helperPath, ['--update-recovery-helper'], {
    detached: true,
    env: helperEnvironment(requestPath),
    stdio: 'ignore',
    windowsHide: true,
  });
  if (!child.pid) {
    rmSync(requestPath, { force: true });
    throw new Error('update recovery helper did not start');
  }
  child.unref();
  return Object.freeze({ pid: child.pid });
}

export function clearPreparedUpdateRecovery(ownedRoot: string): void {
  if (!isAbsolute(ownedRoot)) throw new Error('update recovery root is invalid');
  const planPath = join(ownedRoot, 'recovery-plan.v1.json');
  if (!existsSync(planPath)) return;
  const plan = loadRecoveryPlan(ownedRoot);
  assertOwnedPath(ownedRoot, plan.snapshotRoot);
  if (existsSync(plan.snapshotRoot)) {
    const metadata = lstatSync(plan.snapshotRoot);
    if (!metadata.isDirectory() || metadata.isSymbolicLink()) {
      throw new Error('update recovery snapshot identity is invalid');
    }
    rmSync(plan.snapshotRoot, { recursive: true, force: false });
  }
  rmSync(planPath, { force: false });
  syncDirectory(ownedRoot);
}

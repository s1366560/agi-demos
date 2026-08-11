import { randomUUID } from 'node:crypto';
import {
  chmodSync,
  closeSync,
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
import { dirname, join } from 'node:path';

import {
  validUpdateAction,
  validUpdateReasonCode,
  validUpdateVersion,
  type UpdateLifecycleAction,
} from './updateLifecycle';

export const UPDATE_RECOVERY_JOURNAL_SCHEMA_VERSION = 2 as const;
const MAX_JOURNAL_BYTES = 32 * 1024;
const MAX_PAYLOADS = 8;
const MAX_LAUNCH_ATTEMPTS = 3;
const recordKeys = Object.freeze([
  'schemaVersion',
  'phase',
  'currentVersion',
  'candidateVersion',
  'recoveryVersion',
  'nonce',
  'deadlineAt',
  'launchAttempts',
  'payloads',
  'snapshot',
  'recordedAt',
  'reasonCode',
  'retryable',
  'allowedActions',
]);
const payloadKeys = Object.freeze(['sha512', 'size']);
const snapshotKeys = Object.freeze(['manifestSha512', 'manifestSize']);

export type UpdateRecoveryPhase =
  | 'downloaded'
  | 'applying'
  | 'verifying'
  | 'recovered'
  | 'failed';

export type UpdateRecoveryPayload = Readonly<{
  sha512: string;
  size: number;
}>;

export type UpdateRecoverySnapshot = Readonly<{
  manifestSha512: string;
  manifestSize: number;
}>;

export type UpdateRecoveryRecord = Readonly<{
  schemaVersion: typeof UPDATE_RECOVERY_JOURNAL_SCHEMA_VERSION;
  phase: UpdateRecoveryPhase;
  currentVersion: string;
  candidateVersion: string;
  recoveryVersion: string;
  nonce: string;
  deadlineAt: string;
  launchAttempts: number;
  payloads: readonly UpdateRecoveryPayload[];
  snapshot: UpdateRecoverySnapshot;
  recordedAt: string;
  reasonCode: string | null;
  retryable: boolean;
  allowedActions: readonly UpdateLifecycleAction[];
}>;

export type UpdateRecoveryJournal = Readonly<{
  path: string;
  load(): UpdateRecoveryRecord | null;
  write(record: UpdateRecoveryRecord): void;
  clear(): void;
}>;

type UpdateRecoveryJournalOptions = Readonly<{
  currentUserId?: () => number | undefined;
  fileOwnerId?: (path: string) => number;
}>;

function canonicalSha512(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const bytes = Buffer.from(value, 'base64');
  return bytes.byteLength === 64 && bytes.toString('base64') === value;
}

function validIsoTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length <= 32 &&
    new Date(value).toISOString() === value
  );
}

function parsePayloads(value: unknown): readonly UpdateRecoveryPayload[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > MAX_PAYLOADS) {
    throw new Error('update recovery journal is invalid');
  }
  const payloads = value.map((candidate) => {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
      throw new Error('update recovery journal is invalid');
    }
    const payload = candidate as Record<string, unknown>;
    if (
      Object.keys(payload).length !== payloadKeys.length ||
      Object.keys(payload).some((key) => !payloadKeys.includes(key)) ||
      !canonicalSha512(payload.sha512) ||
      !Number.isSafeInteger(payload.size) ||
      (payload.size as number) <= 0
    ) {
      throw new Error('update recovery journal is invalid');
    }
    return Object.freeze({ sha512: payload.sha512, size: payload.size as number });
  });
  if (new Set(payloads.map(({ sha512 }) => sha512)).size !== payloads.length) {
    throw new Error('update recovery journal is invalid');
  }
  return Object.freeze(payloads);
}

function parseSnapshot(value: unknown): UpdateRecoverySnapshot {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('update recovery journal is invalid');
  }
  const snapshot = value as Record<string, unknown>;
  if (
    Object.keys(snapshot).length !== snapshotKeys.length ||
    Object.keys(snapshot).some((key) => !snapshotKeys.includes(key)) ||
    !canonicalSha512(snapshot.manifestSha512) ||
    !Number.isSafeInteger(snapshot.manifestSize) ||
    (snapshot.manifestSize as number) <= 0
  ) {
    throw new Error('update recovery journal is invalid');
  }
  return Object.freeze({
    manifestSha512: snapshot.manifestSha512,
    manifestSize: snapshot.manifestSize as number,
  });
}

function parseRecord(value: unknown): UpdateRecoveryRecord {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('update recovery journal is invalid');
  }
  const record = value as Record<string, unknown>;
  const phase = record.phase as UpdateRecoveryPhase;
  const allowedActions = record.allowedActions;
  if (
    Object.keys(record).length !== recordKeys.length ||
    Object.keys(record).some((key) => !recordKeys.includes(key)) ||
    record.schemaVersion !== UPDATE_RECOVERY_JOURNAL_SCHEMA_VERSION ||
    !['downloaded', 'applying', 'verifying', 'recovered', 'failed'].includes(phase) ||
    !validUpdateVersion(record.currentVersion) ||
    !validUpdateVersion(record.candidateVersion) ||
    !validUpdateVersion(record.recoveryVersion) ||
    typeof record.nonce !== 'string' ||
    !/^[a-f0-9]{64}$/u.test(record.nonce) ||
    !validIsoTimestamp(record.deadlineAt) ||
    !Number.isSafeInteger(record.launchAttempts) ||
    (record.launchAttempts as number) < 0 ||
    (record.launchAttempts as number) > MAX_LAUNCH_ATTEMPTS ||
    !validIsoTimestamp(record.recordedAt) ||
    (phase !== 'failed' &&
      new Date(record.deadlineAt as string).getTime() <=
        new Date(record.recordedAt as string).getTime()) ||
    !(record.reasonCode === null || validUpdateReasonCode(record.reasonCode)) ||
    typeof record.retryable !== 'boolean' ||
    !Array.isArray(allowedActions) ||
    allowedActions.length > 1 ||
    allowedActions.some((action) => !validUpdateAction(action)) ||
    new Set(allowedActions).size !== allowedActions.length
  ) {
    throw new Error('update recovery journal is invalid');
  }
  if (
    (phase === 'downloaded' &&
      (record.launchAttempts !== 0 ||
        record.reasonCode !== null ||
        record.retryable !== false ||
        JSON.stringify(allowedActions) !== JSON.stringify(['restart_to_apply']))) ||
    ((phase === 'applying' || phase === 'verifying') &&
      ((record.launchAttempts as number) < 1 ||
        record.reasonCode !== null ||
        record.retryable !== false ||
        allowedActions.length !== 0)) ||
    (phase === 'recovered' &&
      ((record.launchAttempts as number) < 1 ||
        record.reasonCode !== null ||
        record.retryable !== false ||
        JSON.stringify(allowedActions) !== JSON.stringify(['check']))) ||
    (phase === 'failed' &&
      (!validUpdateReasonCode(record.reasonCode) ||
        (record.retryable
          ? JSON.stringify(allowedActions) !== JSON.stringify(['restart_to_apply'])
          : allowedActions.length !== 0)))
  ) {
    throw new Error('update recovery journal is invalid');
  }
  return Object.freeze({
    schemaVersion: UPDATE_RECOVERY_JOURNAL_SCHEMA_VERSION,
    phase,
    currentVersion: record.currentVersion,
    candidateVersion: record.candidateVersion,
    recoveryVersion: record.recoveryVersion,
    nonce: record.nonce,
    deadlineAt: record.deadlineAt as string,
    launchAttempts: record.launchAttempts as number,
    payloads: parsePayloads(record.payloads),
    snapshot: parseSnapshot(record.snapshot),
    recordedAt: record.recordedAt as string,
    reasonCode: record.reasonCode as string | null,
    retryable: record.retryable,
    allowedActions: Object.freeze([...(allowedActions as UpdateLifecycleAction[])]),
  });
}

function currentUserId(options: UpdateRecoveryJournalOptions): number | undefined {
  return options.currentUserId?.() ?? process.getuid?.();
}

function assertCurrentUserOwner(path: string, options: UpdateRecoveryJournalOptions): void {
  const expected = currentUserId(options);
  if (expected === undefined) return;
  const actual = options.fileOwnerId?.(path) ?? lstatSync(path).uid;
  if (actual !== expected) {
    throw new Error('update recovery journal must be owned by the current user');
  }
}

function ensurePrivateDirectory(path: string, options: UpdateRecoveryJournalOptions): void {
  mkdirSync(path, { recursive: true, mode: 0o700 });
  const stats = lstatSync(path);
  if (!stats.isDirectory() || stats.isSymbolicLink()) {
    throw new Error('update recovery journal directory must be a regular directory');
  }
  assertCurrentUserOwner(path, options);
  chmodSync(path, 0o700);
}

function syncDirectory(path: string): void {
  let descriptor: number | null = null;
  try {
    descriptor = openSync(path, 'r');
    fsyncSync(descriptor);
  } catch {
    // Some Windows filesystems do not allow fsync on a directory. The file was
    // still fsynced before the atomic rename.
  } finally {
    if (descriptor !== null) closeSync(descriptor);
  }
}

export function createUpdateRecoveryJournal(
  path: string,
  options: UpdateRecoveryJournalOptions = {},
): UpdateRecoveryJournal {
  const directory = dirname(path);
  return Object.freeze({
    path,
    load(): UpdateRecoveryRecord | null {
      if (!existsSync(path)) return null;
      const stats = lstatSync(path);
      if (!stats.isFile() || stats.isSymbolicLink()) {
        throw new Error('update recovery journal must be a regular non-symlink');
      }
      assertCurrentUserOwner(path, options);
      if (stats.size > MAX_JOURNAL_BYTES) {
        throw new Error('update recovery journal is too large');
      }
      chmodSync(path, 0o600);
      try {
        return parseRecord(JSON.parse(readFileSync(path, 'utf8')));
      } catch (error) {
        if (error instanceof Error && error.message.startsWith('update recovery journal')) {
          throw error;
        }
        throw new Error('update recovery journal is invalid');
      }
    },
    write(record: UpdateRecoveryRecord): void {
      const validated = parseRecord(record);
      ensurePrivateDirectory(directory, options);
      const source = `${JSON.stringify(validated)}\n`;
      if (Buffer.byteLength(source) > MAX_JOURNAL_BYTES) {
        throw new Error('update recovery journal is too large');
      }
      const temporaryPath = join(directory, `.recovery-journal.${randomUUID()}.tmp`);
      let descriptor: number | null = null;
      try {
        descriptor = openSync(temporaryPath, 'wx', 0o600);
        writeFileSync(descriptor, source, 'utf8');
        fsyncSync(descriptor);
        closeSync(descriptor);
        descriptor = null;
        renameSync(temporaryPath, path);
        assertCurrentUserOwner(path, options);
        chmodSync(path, 0o600);
        syncDirectory(directory);
      } finally {
        if (descriptor !== null) closeSync(descriptor);
        rmSync(temporaryPath, { force: true });
      }
    },
    clear(): void {
      if (!existsSync(path)) return;
      const stats = lstatSync(path);
      if (!stats.isFile() || stats.isSymbolicLink()) {
        throw new Error('update recovery journal must be a regular non-symlink');
      }
      assertCurrentUserOwner(path, options);
      rmSync(path, { force: true });
      syncDirectory(directory);
    },
  });
}

import type {
  ActivityReadEntry,
  ActivityReadRetryStore,
  ActivityAuthorityScope,
} from './agentAuthorityTypes';

type LocalStoragePort = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

const STORAGE_PREFIX = 'memstack.activity.authority-retry.v1';

export function createLocalStorageActivityReadRetryStore(
  storage: LocalStoragePort = requireLocalStorage(),
): ActivityReadRetryStore {
  const store: ActivityReadRetryStore = {
    load(scope) {
      const key = storageKey(scope);
      const raw = storage.getItem(key);
      if (raw === null) return [];
      try {
        const parsed: unknown = JSON.parse(raw);
        const entries = parseEntries(parsed);
        if (entries) return entries;
      } catch {
        // Corrupt offline retry data has no authority and must not be replayed.
      }
      storage.removeItem(key);
      return [];
    },
    save(scope, entries) {
      const merged = mergeActivityReadEntries(this.load(scope), entries);
      if (merged.length === 0) {
        storage.removeItem(storageKey(scope));
        return;
      }
      storage.setItem(storageKey(scope), JSON.stringify(merged));
    },
    clear(scope) {
      storage.removeItem(storageKey(scope));
    },
  };
  return Object.freeze(store);
}

export function mergeActivityReadEntries(
  current: readonly ActivityReadEntry[],
  incoming: readonly ActivityReadEntry[],
): readonly ActivityReadEntry[] {
  const merged = new Map<string, ActivityReadEntry>();
  for (const entry of [...current, ...incoming]) {
    if (!isActivityReadEntry(entry)) continue;
    const previous = merged.get(entry.entry_id);
    if (!previous) {
      merged.set(entry.entry_id, { ...entry });
      continue;
    }
    merged.set(entry.entry_id, {
      entry_id: entry.entry_id,
      entry_revision: Math.max(previous.entry_revision, entry.entry_revision),
      read_at:
        Date.parse(previous.read_at) >= Date.parse(entry.read_at)
          ? previous.read_at
          : entry.read_at,
    });
  }
  return [...merged.values()].sort((left, right) =>
    left.entry_id.localeCompare(right.entry_id),
  );
}

function requireLocalStorage(): LocalStoragePort {
  if (typeof globalThis.localStorage === 'undefined') {
    throw new Error('activity_read_retry_storage_unavailable');
  }
  return globalThis.localStorage;
}

function storageKey(scope: ActivityAuthorityScope): string {
  const principalId = encodeURIComponent(scope.principalId);
  const tenantId = encodeURIComponent(scope.tenantId);
  const projectId = encodeURIComponent(scope.projectId);
  return `${STORAGE_PREFIX}:${principalId}:${tenantId}:${projectId}`;
}

function parseEntries(value: unknown): readonly ActivityReadEntry[] | null {
  if (!Array.isArray(value) || value.length > 500) return null;
  if (!value.every(isActivityReadEntry)) return null;
  const ids = new Set(value.map((entry) => entry.entry_id));
  if (ids.size !== value.length) return null;
  return value.map((entry) => ({ ...entry }));
}

function isActivityReadEntry(value: unknown): value is ActivityReadEntry {
  if (!isRecord(value)) return false;
  return (
    isIdentifier(value.entry_id) &&
    isNonnegativeInteger(value.entry_revision) &&
    isTimestamp(value.read_at)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isIdentifier(value: unknown): value is string {
  return (
    typeof value === 'string' && value.length > 0 && value === value.trim()
  );
}

function isNonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function isTimestamp(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.length > 0 &&
    Number.isFinite(Date.parse(value))
  );
}

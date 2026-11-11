export const NEW_THREAD_SCOPE_STORAGE_KEY = 'agistack.desktop.new-thread-scope';

type NewThreadScopePreference = {
  version: 1;
  projectId: string;
  workspaceId: string;
};

type PreferenceStorage = Pick<Storage, 'getItem' | 'setItem'>;

function storageOrDefault(storage?: PreferenceStorage): PreferenceStorage | null {
  if (storage) return storage;
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function isPreference(value: unknown): value is NewThreadScopePreference {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return (
    Object.keys(record).length === 3 &&
    record.version === 1 &&
    typeof record.projectId === 'string' &&
    typeof record.workspaceId === 'string'
  );
}

/** Remember the last explicit workspace choice for a project. An empty
 * workspaceId is meaningful: it records the deliberate "no workspace" choice. */
export function readNewThreadScopePreference(
  projectId: string,
  storage?: PreferenceStorage,
): { workspaceId: string } | null {
  const target = storageOrDefault(storage);
  const normalizedProjectId = projectId.trim();
  if (!target || !normalizedProjectId) return null;
  try {
    const raw = target.getItem(NEW_THREAD_SCOPE_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return isPreference(parsed) && parsed.projectId === normalizedProjectId
      ? { workspaceId: parsed.workspaceId }
      : null;
  } catch {
    return null;
  }
}

export function writeNewThreadScopePreference(
  projectId: string,
  workspaceId: string,
  storage?: PreferenceStorage,
): void {
  const target = storageOrDefault(storage);
  const normalizedProjectId = projectId.trim();
  if (!target || !normalizedProjectId) return;
  const preference: NewThreadScopePreference = {
    version: 1,
    projectId: normalizedProjectId,
    workspaceId: workspaceId.trim(),
  };
  try {
    target.setItem(NEW_THREAD_SCOPE_STORAGE_KEY, JSON.stringify(preference));
  } catch {
    // The preference is non-essential; ignore an inaccessible store.
  }
}

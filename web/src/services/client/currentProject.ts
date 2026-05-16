/**
 * Current Project singleton.
 *
 * Centralizes the "which project am I acting on" decision across:
 *  - Zustand stores (useProjectStore.currentProject)
 *  - HTTP requests (X-Project-Id header)
 *  - WebSocket subscriptions / Redis channels
 *
 * Borrowed from multica's HANDOFF_ARCHITECTURE_AUDIT.md task-2 pattern:
 * all callers must read + write through this module, and an explicit
 * setCurrentProject(null) must be invoked on logout / project delete /
 * project switch to prevent stale WS events from leaking into a new
 * session context.
 *
 * This module is deliberately dependency-free so it can be imported from
 * any layer (stores, services, hooks) without creating cycles.
 */

type Subscriber = (projectId: string | null) => void;

let currentProjectId: string | null = null;
const subscribers = new Set<Subscriber>();

const STORAGE_KEY = 'memstack.currentProjectId';

const hasStorage = typeof window !== 'undefined' && !!window.localStorage;

// Hydrate from localStorage on module load so a page refresh keeps context.
if (hasStorage) {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored) currentProjectId = stored;
  } catch {
    // localStorage can throw in private mode; ignore.
  }
}

export function getCurrentProject(): string | null {
  return currentProjectId;
}

export function setCurrentProject(id: string | null): void {
  if (currentProjectId === id) return;
  currentProjectId = id;

  if (hasStorage) {
    try {
      if (id) window.localStorage.setItem(STORAGE_KEY, id);
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }

  for (const cb of subscribers) {
    try {
      cb(id);
    } catch (err) {
      console.error('[currentProject] subscriber threw', err);
    }
  }
}

/**
 * Subscribe to project changes. Returns an unsubscribe function.
 */
export function subscribeCurrentProject(cb: Subscriber): () => void {
  subscribers.add(cb);
  return () => {
    subscribers.delete(cb);
  };
}

/**
 * Clear project context. MUST be called on logout, project deletion,
 * or before switching to a new project to prevent cross-tenant leakage.
 */
export function clearCurrentProject(): void {
  setCurrentProject(null);
}

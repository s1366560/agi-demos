import type { AuthSessionDescriptor } from '../../types';

const STORAGE_KEY = 'memstack.desktop.trusted-local-session.v1';

export type TrustedLocalSessionReference = {
  version: 1;
  sessionId: string;
  expiresAt: string;
};

type SessionReferenceStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;

function parseReference(value: unknown, nowMs: number): TrustedLocalSessionReference | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const allowedKeys = new Set(['version', 'sessionId', 'expiresAt']);
  if (Object.keys(record).some((key) => !allowedKeys.has(key))) return null;
  if (record.version !== 1) return null;
  if (typeof record.sessionId !== 'string' || !record.sessionId.trim()) return null;
  if (typeof record.expiresAt !== 'string' || !record.expiresAt.trim()) return null;
  const expiresAtMs = Date.parse(record.expiresAt);
  if (!Number.isFinite(expiresAtMs) || expiresAtMs <= nowMs) return null;
  return {
    version: 1,
    sessionId: record.sessionId.trim(),
    expiresAt: record.expiresAt,
  };
}

export function readTrustedLocalSessionReference(
  storage: SessionReferenceStorage,
  nowMs = Date.now(),
): TrustedLocalSessionReference | null {
  try {
    const serialized = storage.getItem(STORAGE_KEY);
    if (!serialized) return null;
    const reference = parseReference(JSON.parse(serialized), nowMs);
    if (!reference) storage.removeItem(STORAGE_KEY);
    return reference;
  } catch {
    try {
      storage.removeItem(STORAGE_KEY);
    } catch {
      // Storage may be unavailable; callers remain signed out.
    }
    return null;
  }
}

export function writeTrustedLocalSessionReference(
  storage: SessionReferenceStorage,
  session: AuthSessionDescriptor | null | undefined,
  nowMs = Date.now(),
): TrustedLocalSessionReference | null {
  const reference = parseReference(
    session?.trusted_device
      ? {
          version: 1,
          sessionId: session.session_id,
          expiresAt: session.expires_at,
        }
      : null,
    nowMs,
  );
  try {
    if (!reference) {
      storage.removeItem(STORAGE_KEY);
      return null;
    }
    storage.setItem(STORAGE_KEY, JSON.stringify(reference));
    return reference;
  } catch {
    return null;
  }
}

export function clearTrustedLocalSessionReference(storage: SessionReferenceStorage): void {
  try {
    storage.removeItem(STORAGE_KEY);
  } catch {
    // Local sign-out must still complete when storage is unavailable.
  }
}

export const trustedLocalSessionStorageKey = STORAGE_KEY;

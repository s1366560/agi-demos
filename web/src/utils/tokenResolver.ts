/**
 * Token Resolver Utility
 *
 * Provides centralized token resolution and auth state clearing.
 * Single source of truth for auth token access across httpClient, apiFetch, and services.
 */

const ZUSTAND_AUTH_STORAGE_KEY = 'memstack-auth-storage';

type AuthStateClearer = () => void;

let authStateClearer: AuthStateClearer | null = null;

type TokenLookupResult = {
  found: boolean;
  token: string | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readTokenFromRecord(record: Record<string, unknown>): TokenLookupResult {
  if (!Object.prototype.hasOwnProperty.call(record, 'token')) {
    return { found: false, token: null };
  }

  const token = record.token;
  return { found: true, token: typeof token === 'string' ? token : null };
}

/**
 * Get the authentication token from Zustand persist storage.
 *
 * Reads from `memstack-auth-storage` localStorage key (Zustand persist format).
 *
 * @returns The auth token string, or null if not found
 */
export function getAuthToken(): string | null {
  const authStorage = localStorage.getItem(ZUSTAND_AUTH_STORAGE_KEY);

  if (authStorage) {
    try {
      const parsed: unknown = JSON.parse(authStorage);

      if (!isRecord(parsed)) {
        return null;
      }

      // Zustand persist structure: { state: { token: "..." }, version: 0 }
      if (isRecord(parsed.state)) {
        const stateToken = readTokenFromRecord(parsed.state);
        if (stateToken.found) {
          return stateToken.token;
        }
      }

      // Backward compatibility: direct property
      const directToken = readTokenFromRecord(parsed);
      if (directToken.found) {
        return directToken.token;
      }
    } catch {
      // Invalid JSON
    }
  }

  return null;
}

export function registerAuthStateClearer(clearer: AuthStateClearer): () => void {
  authStateClearer = clearer;

  return () => {
    if (authStateClearer === clearer) {
      authStateClearer = null;
    }
  };
}

/**
 * Clear all authentication state.
 *
 * Clears both the Zustand in-memory store AND persisted localStorage.
 * This is the ONLY function that should clear auth state across the app.
 */
export function clearAuthState(): void {
  localStorage.removeItem(ZUSTAND_AUTH_STORAGE_KEY);

  authStateClearer?.();
}

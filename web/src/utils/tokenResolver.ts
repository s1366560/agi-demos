/**
 * Token Resolver Utility
 *
 * Provides centralized token resolution and auth state clearing.
 * Single source of truth for auth token access across httpClient, apiFetch, and services.
 */

const ZUSTAND_AUTH_STORAGE_KEY = 'memstack-auth-storage';

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
      const parsed = JSON.parse(authStorage);

      // Zustand persist structure: { state: { token: "..." }, version: 0 }
      if (parsed.state && 'token' in parsed.state) {
        return parsed.state.token;
      }

      // Backward compatibility: direct property
      if ('token' in parsed) {
        return parsed.token;
      }
    } catch {
      // Invalid JSON
    }
  }

  return null;
}

/**
 * Clear all authentication state.
 *
 * Clears both the Zustand in-memory store AND persisted localStorage.
 * Uses dynamic import to avoid circular dependencies (stores -> services -> tokenResolver).
 * This is the ONLY function that should clear auth state across the app.
 */
export function clearAuthState(): void {
  // Clear Zustand in-memory state (triggers React re-render -> redirect to /login)
  import('@/stores/auth').then(({ useAuthStore }) => {
    useAuthStore.setState({
      user: null,
      token: null,
      isAuthenticated: false,
      isLoading: false,
    });
  }).catch(() => {
    // If dynamic import fails, clear localStorage directly as fallback
    localStorage.removeItem(ZUSTAND_AUTH_STORAGE_KEY);
  });
}

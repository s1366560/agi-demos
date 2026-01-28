/**
 * Token Resolver Utility
 *
 * Provides centralized token resolution from Zustand persist storage.
 * This ensures consistent token reading across httpClient, agentService, and other services.
 *
 * @packageDocumentation
 *
 * @example
 * ```typescript
 * import { getAuthToken } from '@/utils/tokenResolver';
 *
 * const token = getAuthToken();
 * if (token) {
 *   // Use token for authentication
 * }
 * ```
 */

/**
 * Zustand persist storage key
 *
 * The key used by Zustand persist middleware to store auth state.
 */
const ZUSTAND_AUTH_STORAGE_KEY = 'memstack-auth-storage';

/**
 * Legacy token storage key
 *
 * Direct localStorage key for token (backward compatibility).
 */
const LEGACY_TOKEN_KEY = 'token';

/**
 * Get the authentication token from Zustand persist storage
 *
 * Reads token from 'memstack-auth-storage' with the following priority:
 * 1. `state.token` - Current Zustand persist structure
 * 2. `token` - Direct property for backward compatibility
 * 3. Falls back to legacy 'token' key in localStorage
 *
 * @returns The auth token string, or null if not found
 *
 * @example
 * ```typescript
 * const token = getAuthToken();
 * if (!token) {
 *   redirect('/login');
 * }
 * ```
 */
export function getAuthToken(): string | null {
  // Try reading from Zustand persist storage first
  const authStorage = localStorage.getItem(ZUSTAND_AUTH_STORAGE_KEY);

  if (authStorage) {
    try {
      const parsed = JSON.parse(authStorage);

      // Priority 1: state.token (current Zustand persist structure)
      // Use 'in' operator to check property existence, allowing empty string
      if (parsed.state && 'token' in parsed.state) {
        return parsed.state.token;
      }

      // Priority 2: direct token property (backward compatibility)
      if ('token' in parsed) {
        return parsed.token;
      }
    } catch {
      // Invalid JSON, fall through to legacy storage
    }
  }

  // Priority 3: Legacy direct token key
  return localStorage.getItem(LEGACY_TOKEN_KEY);
}

/**
 * Tests for tokenResolver utility
 *
 * Tests the token resolution logic that reads from Zustand persist storage
 * with fallback to legacy localStorage key.
 *
 * @packageDocumentation
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';

import { clearAuthState, getAuthToken, registerAuthStateClearer } from '@/utils/tokenResolver';

describe('tokenResolver', () => {
  beforeEach(() => {
    // Clear all localStorage before each test
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  describe('getAuthToken', () => {
    it('should read token from memstack-auth-storage with state.token structure', () => {
      const expectedToken = 'test-token-from-state';
      const authStorage = JSON.stringify({
        state: {
          token: expectedToken,
          user: { id: '123', name: 'Test User' },
        },
        version: 0,
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      const token = getAuthToken();
      expect(token).toBe(expectedToken);
    });

    it('should read token from memstack-auth-storage with direct token structure', () => {
      const expectedToken = 'test-token-from-direct';
      const authStorage = JSON.stringify({
        token: expectedToken,
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      const token = getAuthToken();
      expect(token).toBe(expectedToken);
    });

    it('should not fallback to direct token key (legacy fallback removed)', () => {
      localStorage.setItem('token', 'legacy-token');

      const token = getAuthToken();
      expect(token).toBeNull();
    });

    it('should prioritize memstack-auth-storage over direct token key', () => {
      const storageToken = 'token-from-storage';
      const legacyToken = 'token-from-legacy';

      const authStorage = JSON.stringify({
        state: { token: storageToken },
      });
      localStorage.setItem('memstack-auth-storage', authStorage);
      localStorage.setItem('token', legacyToken);

      const token = getAuthToken();
      expect(token).toBe(storageToken);
    });

    it('should return null when no token is stored', () => {
      const token = getAuthToken();
      expect(token).toBeNull();
    });

    it('should return null when memstack-auth-storage has invalid JSON even if legacy key exists', () => {
      localStorage.setItem('memstack-auth-storage', 'invalid-json{{{');
      localStorage.setItem('token', 'legacy-token');

      const token = getAuthToken();
      expect(token).toBeNull();
    });

    it('should return null when memstack-auth-storage exists but has no token', () => {
      const authStorage = JSON.stringify({
        state: {
          user: { id: '123', name: 'Test User' },
        },
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      const token = getAuthToken();
      expect(token).toBeNull();
    });

    it('should handle empty memstack-auth-storage', () => {
      localStorage.setItem('memstack-auth-storage', '{}');

      const token = getAuthToken();
      expect(token).toBeNull();
    });

    it('should handle null state in memstack-auth-storage', () => {
      const authStorage = JSON.stringify({
        state: null,
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      const token = getAuthToken();
      expect(token).toBeNull();
    });

    it('should return null when state token is not a string', () => {
      const authStorage = JSON.stringify({
        state: { token: 123 },
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      const token = getAuthToken();
      expect(token).toBeNull();
    });

    it('should not fallback to direct token when state token is invalid', () => {
      const authStorage = JSON.stringify({
        state: { token: null },
        token: 'direct-token',
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      const token = getAuthToken();
      expect(token).toBeNull();
    });

    it('should prefer state.token over direct token property in storage', () => {
      const stateToken = 'token-from-state';
      const directToken = 'token-from-direct';

      const authStorage = JSON.stringify({
        state: { token: stateToken },
        token: directToken,
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      const token = getAuthToken();
      expect(token).toBe(stateToken);
    });

    it('should handle empty string token', () => {
      const authStorage = JSON.stringify({
        state: { token: '' },
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      const token = getAuthToken();
      expect(token).toBe('');
    });

    it('should handle whitespace-only token', () => {
      const authStorage = JSON.stringify({
        state: { token: '   ' },
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      const token = getAuthToken();
      expect(token).toBe('   ');
    });

    it('should handle complex Zustand persist structure with version', () => {
      const expectedToken = 'complex-token';
      const authStorage = JSON.stringify({
        state: {
          token: expectedToken,
          user: { id: '123', name: 'Test' },
          _hasHydrated: true,
        },
        version: 1,
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      const token = getAuthToken();
      expect(token).toBe(expectedToken);
    });
  });

  describe('clearAuthState', () => {
    it('should clear persisted auth storage without a registered store clearer', () => {
      localStorage.setItem(
        'memstack-auth-storage',
        JSON.stringify({ state: { token: 'stale-token' }, version: 0 })
      );

      clearAuthState();

      expect(localStorage.getItem('memstack-auth-storage')).toBeNull();
    });

    it('should invoke a registered store clearer synchronously', () => {
      let cleared = false;
      const unregister = registerAuthStateClearer(() => {
        cleared = true;
      });

      try {
        clearAuthState();

        expect(cleared).toBe(true);
      } finally {
        unregister();
      }
    });
  });
});

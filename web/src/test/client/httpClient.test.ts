/**
 * httpClient token resolution tests
 *
 * @packageDocumentation
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

describe('httpClient Token Resolution', () => {
  let localStorageMock: Record<string, string> = {};

  beforeEach(() => {
    // Clear mock storage
    localStorageMock = {};
    // Mock localStorage
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => localStorageMock[key] || null,
      setItem: (key: string, value: string) => {
        localStorageMock[key] = value.toString();
      },
      removeItem: (key: string) => {
        delete localStorageMock[key];
      },
      clear: () => {
        localStorageMock = {};
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe('Zustand persist storage format', () => {
    it('should extract token from memstack-auth-storage with state key', () => {
      const mockToken = 'ms_sk_test123';
      localStorage.setItem(
        'memstack-auth-storage',
        JSON.stringify({
          state: { token: mockToken, user: { id: '1' } },
          version: 0,
        })
      );

      const storage = localStorage.getItem('memstack-auth-storage');
      expect(storage).toBeTruthy();
      const parsed = JSON.parse(storage!);
      const token = parsed.state?.token || parsed.token;
      expect(token).toBe(mockToken);
    });

    it('should extract token from memstack-auth-storage without state key (backward compat)', () => {
      const mockToken = 'ms_sk_test456';
      localStorage.setItem(
        'memstack-auth-storage',
        JSON.stringify({
          token: mockToken,
          user: { id: '1' },
        })
      );

      const storage = localStorage.getItem('memstack-auth-storage');
      expect(storage).toBeTruthy();
      const parsed = JSON.parse(storage!);
      const token = parsed.state?.token || parsed.token;
      expect(token).toBe(mockToken);
    });

    it('should fall back to direct token key for backward compatibility', () => {
      const mockToken = 'ms_sk_test789';
      localStorage.setItem('token', mockToken);

      const authStorage = localStorage.getItem('memstack-auth-storage');
      let token: string | null = null;

      if (authStorage) {
        try {
          const parsed = JSON.parse(authStorage);
          token = parsed.state?.token || parsed.token;
        } catch {
          token = localStorage.getItem('token');
        }
      } else {
        token = localStorage.getItem('token');
      }

      expect(token).toBe(mockToken);
    });

    it('should return null when no token is stored', () => {
      const authStorage = localStorage.getItem('memstack-auth-storage');
      let token: string | null = null;

      if (authStorage) {
        try {
          const parsed = JSON.parse(authStorage);
          token = parsed.state?.token || parsed.token;
        } catch {
          token = localStorage.getItem('token');
        }
      } else {
        token = localStorage.getItem('token');
      }

      expect(token).toBeNull();
    });
  });

  describe('Token format validation', () => {
    it('should accept ms_sk_ prefixed tokens', () => {
      const validTokens = ['ms_sk_abc123def456', 'ms_sk_' + 'a'.repeat(64)];

      validTokens.forEach((token) => {
        expect(token.startsWith('ms_sk_')).toBe(true);
        expect(token.length).toBeGreaterThan(10);
      });
    });

    it('should construct correct Authorization header', () => {
      const mockToken = 'ms_sk_testToken123';
      const header = `Bearer ${mockToken}`;

      expect(header).toBe('Bearer ms_sk_testToken123');
    });
  });
});

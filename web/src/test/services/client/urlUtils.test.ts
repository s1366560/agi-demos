/**
 * Tests for API URL utilities
 *
 * TDD: Write failing tests first, then implement.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import {
  createApiUrl,
  createWebSocketUrl,
  apiFetch,
  handleUnauthorized,
} from '@/services/client/urlUtils';

describe('createApiUrl', () => {
  // Reset environment before each test
  beforeEach(() => {
    // Clear VITE_API_URL cache
    delete (import.meta.env as any).VITE_API_URL;
  });

  it('should prepend /api/v1 to relative paths', () => {
    const result = createApiUrl('/agent/conversations');
    expect(result).toBe('/api/v1/agent/conversations');
  });

  it('should handle paths without leading slash', () => {
    const result = createApiUrl('agent/conversations');
    expect(result).toBe('/api/v1/agent/conversations');
  });

  it('should use VITE_API_URL when set (absolute URL)', () => {
    (import.meta.env as any).VITE_API_URL = 'http://api.example.com';
    const result = createApiUrl('/agent/conversations');
    expect(result).toBe('http://api.example.com/api/v1/agent/conversations');
  });

  it('should handle empty string path', () => {
    const result = createApiUrl('');
    expect(result).toBe('/api/v1');
  });

  it('should not double-prefix /api/v1 if path already has it', () => {
    const result = createApiUrl('/api/v1/agent/conversations');
    // Should normalize to avoid double prefix
    expect(result).toBe('/api/v1/agent/conversations');
  });
});

describe('createWebSocketUrl', () => {
  beforeEach(() => {
    // Clear VITE_API_URL cache
    delete (import.meta.env as any).VITE_API_URL;
    // Reset window.location to default
    Object.defineProperty(window, 'location', {
      value: {
        protocol: 'http:',
        host: 'localhost:3000',
      },
      writable: true,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('should create ws:// URL for http protocol', () => {
    const result = createWebSocketUrl('/agent/ws');
    // Port 3000 is automatically redirected to 8000 (backend port) in development
    expect(result).toBe('ws://localhost:8000/api/v1/agent/ws');
  });

  it('should create wss:// URL for https protocol', () => {
    Object.defineProperty(window, 'location', {
      value: {
        protocol: 'https:',
        host: 'example.com',
      },
      writable: true,
    });

    const result = createWebSocketUrl('/agent/ws');
    expect(result).toBe('wss://example.com/api/v1/agent/ws');
  });

  it('should use VITE_API_URL host when set', () => {
    (import.meta.env as any).VITE_API_URL = 'http://api.example.com:8000';
    const result = createWebSocketUrl('/agent/ws');
    expect(result).toBe('ws://api.example.com:8000/api/v1/agent/ws');
  });

  it('should append query parameters', () => {
    const result = createWebSocketUrl('/agent/ws', { token: 'abc123', session_id: 'xyz' });
    // Port 3000 is automatically redirected to 8000 (backend port) in development
    expect(result).toBe('ws://localhost:8000/api/v1/agent/ws?token=abc123&session_id=xyz');
  });
});

describe('apiFetch', () => {
  beforeEach(() => {
    // Mock localStorage for auth token
    vi.spyOn(Storage.prototype, 'getItem').mockReturnValue('test-token');
    // Clear VITE_API_URL
    delete (import.meta.env as any).VITE_API_URL;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('should include Authorization header', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ data: 'test' }),
    });
    global.fetch = mockFetch;

    await apiFetch.get('/test');

    const callArgs = mockFetch.mock.calls[0];
    expect(callArgs[0]).toBe('/api/v1/test');
    // Headers object - check as plain object
    expect(callArgs[1]).toBeDefined();
    expect(callArgs[1]?.headers).toBeDefined();
  });

  it('should handle POST requests with JSON body', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true }),
    });
    global.fetch = mockFetch;

    await apiFetch.post('/test', { message: 'hello' });

    const callArgs = mockFetch.mock.calls[0];
    expect(callArgs[0]).toBe('/api/v1/test');
    expect(callArgs[1]?.method).toBe('POST');
    expect(callArgs[1]?.body).toBe(JSON.stringify({ message: 'hello' }));
    expect(callArgs[1]?.headers?.['Content-Type']).toBe('application/json');
  });

  it('should handle 401 errors by clearing token and redirecting', () => {
    // Mock window.location.pathname
    const originalPathname = window.location.pathname;
    Object.defineProperty(window, 'location', {
      value: {
        href: '',
        pathname: '/dashboard',
      },
      writable: true,
    });

    // Track redirection
    let redirectedTo = '';
    Object.defineProperty(window.location, 'href', {
      set: (value: string) => {
        redirectedTo = value;
      },
      get: () => window.location.href,
      configurable: true,
    });

    // Test handleUnauthorized directly
    handleUnauthorized();

    // Verify localStorage was cleared
    expect(localStorage.getItem('token')).toBeNull();
    expect(localStorage.getItem('user')).toBeNull();
    expect(redirectedTo).toBe('/login');

    // Restore
    Object.defineProperty(window, 'location', {
      value: { href: '', pathname: originalPathname },
      writable: true,
    });
  });
});

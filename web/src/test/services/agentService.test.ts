/**
 * Tests for agentService WebSocket token handling
 *
 * Tests that agentService correctly uses getAuthToken for WebSocket connections.
 *
 * @packageDocumentation
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { agentService } from '@/services/agentService';

import { getAuthToken } from '@/utils/tokenResolver';

// Mock WebSocket
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  url: string;
  readyState = MockWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    // Simulate async connection
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      if (this.onopen) {
        this.onopen(new Event('open'));
      }
    }, 0);
  }

  send(_data: string): void {
    if (this.readyState !== MockWebSocket.OPEN) {
      throw new Error('WebSocket is not open');
    }
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose(new CloseEvent('close'));
    }
  }
}

describe('agentService - WebSocket Token Handling', () => {
  beforeEach(() => {
    // Clear localStorage before each test
    localStorage.clear();

    // Disconnect any existing connection
    agentService.disconnect();

    // Mock global WebSocket
    vi.stubGlobal('WebSocket', MockWebSocket);

    // Mock crypto.randomUUID
    vi.stubGlobal('crypto', {
      randomUUID: () => 'test-session-id',
    });
  });

  afterEach(() => {
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  describe('connect() - token resolution', () => {
    it('should use getAuthToken to retrieve token for WebSocket connection', async () => {
      const expectedToken = 'websocket-test-token';
      const authStorage = JSON.stringify({
        state: { token: expectedToken },
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      // Verify getAuthToken returns the token
      expect(getAuthToken()).toBe(expectedToken);

      // Connect should succeed
      await expect(agentService.connect()).resolves.toBeUndefined();

      // Verify connected status
      expect(agentService.getStatus()).toBe('connected');

      // Cleanup
      agentService.disconnect();
    });

    it('should connect successfully with legacy token storage', async () => {
      const expectedToken = 'legacy-websocket-token';
      localStorage.setItem('token', expectedToken);

      // Verify getAuthToken returns the token
      expect(getAuthToken()).toBe(expectedToken);

      // Connect should succeed
      await expect(agentService.connect()).resolves.toBeUndefined();
      expect(agentService.getStatus()).toBe('connected');

      // Cleanup
      agentService.disconnect();
    });

    it('should fail to connect when no token is available', async () => {
      // Ensure no token is stored and disconnect any existing connection
      agentService.disconnect();
      expect(getAuthToken()).toBeNull();

      // Connect should fail
      await expect(agentService.connect()).rejects.toThrow('No authentication token');
      expect(agentService.getStatus()).toBe('error');
    });

    it('should include token in WebSocket URL', async () => {
      const expectedToken = 'url-token-test';
      const authStorage = JSON.stringify({
        state: { token: expectedToken },
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      // Create a spy to capture WebSocket URL
      let capturedWsUrl: string | undefined;
      vi.stubGlobal('WebSocket', class extends MockWebSocket {
        constructor(url: string) {
          super(url);
          capturedWsUrl = url;
        }
      });

      await agentService.connect();

      // Verify token is in URL
      expect(capturedWsUrl).toBeDefined();
      expect(capturedWsUrl).toContain(`token=${encodeURIComponent(expectedToken)}`);

      // Cleanup
      agentService.disconnect();
    });

    it('should prioritize memstack-auth-storage over legacy token', async () => {
      const storageToken = 'storage-priority-token';
      const legacyToken = 'legacy-priority-token';

      const authStorage = JSON.stringify({
        state: { token: storageToken },
      });
      localStorage.setItem('memstack-auth-storage', authStorage);
      localStorage.setItem('token', legacyToken);

      // Verify getAuthToken prioritizes storage
      expect(getAuthToken()).toBe(storageToken);

      // Capture WebSocket URL to verify correct token used
      let capturedWsUrl: string | undefined;
      vi.stubGlobal('WebSocket', class extends MockWebSocket {
        constructor(url: string) {
          super(url);
          capturedWsUrl = url;
        }
      });

      await agentService.connect();

      // Verify storage token is used, not legacy token
      expect(capturedWsUrl).toContain(`token=${encodeURIComponent(storageToken)}`);
      expect(capturedWsUrl).not.toContain(`token=${encodeURIComponent(legacyToken)}`);

      // Cleanup
      agentService.disconnect();
    });
  });

  describe('disconnect and reconnect', () => {
    it('should maintain token after disconnect and reconnect', async () => {
      const expectedToken = 'persistent-token';
      const authStorage = JSON.stringify({
        state: { token: expectedToken },
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      // First connection
      await agentService.connect();
      expect(agentService.getStatus()).toBe('connected');

      // Disconnect
      agentService.disconnect();
      expect(agentService.getStatus()).toBe('disconnected');

      // Reconnect should succeed with same token
      await agentService.connect();
      expect(agentService.getStatus()).toBe('connected');

      // Cleanup
      agentService.disconnect();
    });
  });
});

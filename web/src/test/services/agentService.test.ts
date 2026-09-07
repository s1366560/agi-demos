import { installResourceOperationFixtureV2 } from './webResourceOperationFixtureV2';
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
  protocols: string | string[] | undefined;

  constructor(url: string, protocols?: string | string[]) {
    this.url = url;
    this.protocols = protocols;
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
  let fixture: ReturnType<typeof installResourceOperationFixtureV2>;
  beforeEach(async () => {
    await agentService.disconnect().catch(() => undefined);
    fixture = installResourceOperationFixtureV2();
    // Clear localStorage before each test
    localStorage.clear();

    // Disconnect any existing connection
    void agentService.disconnect().catch(() => undefined);

    // Clear stale connectingPromise from previous rejected connections
    // (source bug: doConnect rejects without clearing connectingPromise)
    (agentService as any).wsConnection.connectingPromise = null;

    // Mock global WebSocket
    vi.stubGlobal('WebSocket', MockWebSocket);

    // Mock crypto.randomUUID
    vi.stubGlobal('crypto', {
      randomUUID: () => 'test-session-id',
    });
  });

  afterEach(async () => {
    await agentService.disconnect().catch(() => undefined);
    await fixture.close();
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
      void agentService.disconnect().catch(() => undefined);
    });

    it('should reject legacy token storage (only memstack-auth-storage is supported)', async () => {
      const legacyToken = 'legacy-websocket-token';
      localStorage.setItem('token', legacyToken);

      // getAuthToken only reads memstack-auth-storage, not the legacy 'token' key
      expect(getAuthToken()).toBeNull();

      // Connect should fail without a valid token
      await expect(agentService.connect()).rejects.toThrow('No authentication token');

      // Cleanup
      void agentService.disconnect().catch(() => undefined);
    });

    it('should fail to connect when no token is available', async () => {
      // Ensure no token is stored and disconnect any existing connection
      void agentService.disconnect().catch(() => undefined);
      expect(getAuthToken()).toBeNull();

      // Connect should fail
      await expect(agentService.connect()).rejects.toThrow('No authentication token');
      expect(agentService.getStatus()).toBe('error');
    });

    it('should include token in WebSocket auth protocols', async () => {
      const expectedToken = 'url-token-test';
      const authStorage = JSON.stringify({
        state: { token: expectedToken },
      });
      localStorage.setItem('memstack-auth-storage', authStorage);

      // Create a spy to capture WebSocket URL
      let capturedWsUrl: string | undefined;
      let capturedProtocols: string | string[] | undefined;
      vi.stubGlobal(
        'WebSocket',
        class extends MockWebSocket {
          constructor(url: string, protocols?: string | string[]) {
            super(url, protocols);
            capturedWsUrl = url;
            capturedProtocols = protocols;
          }
        }
      );

      await agentService.connect();

      // Verify token is in auth protocols, not the URL query string
      expect(capturedWsUrl).toBeDefined();
      expect(capturedWsUrl).not.toContain(`token=${encodeURIComponent(expectedToken)}`);
      expect(capturedProtocols).toEqual(['memstack.auth', expectedToken]);

      // Cleanup
      void agentService.disconnect().catch(() => undefined);
    });

    it('should prioritize memstack-auth-storage over legacy token in auth protocols', async () => {
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
      let capturedProtocols: string | string[] | undefined;
      vi.stubGlobal(
        'WebSocket',
        class extends MockWebSocket {
          constructor(url: string, protocols?: string | string[]) {
            super(url, protocols);
            capturedWsUrl = url;
            capturedProtocols = protocols;
          }
        }
      );

      await agentService.connect();

      // Verify storage token is used, not legacy token
      expect(capturedProtocols).toEqual(['memstack.auth', storageToken]);
      expect(capturedWsUrl).not.toContain(`token=${encodeURIComponent(storageToken)}`);
      expect(capturedWsUrl).not.toContain(`token=${encodeURIComponent(legacyToken)}`);

      // Cleanup
      void agentService.disconnect().catch(() => undefined);
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
      void agentService.disconnect().catch(() => undefined);
      expect(agentService.getStatus()).toBe('disconnected');

      // Reconnect should succeed with same token
      await agentService.connect();
      expect(agentService.getStatus()).toBe('connected');

      // Cleanup
      void agentService.disconnect().catch(() => undefined);
    });
  });

  describe('chat()', () => {
    beforeEach(async () => {
      localStorage.setItem(
        'memstack-auth-storage',
        JSON.stringify({ state: { token: 'protocol-fixture-token' } })
      );
      await agentService.connectSession();
    });
    it('should include preferred_language in send_message payload', async () => {
      const isConnectedSpy = vi.spyOn(agentService, 'isConnected').mockReturnValue(true);
      const sendSpy = vi
        .spyOn(agentService as any, 'send')
        .mockImplementation((payload: Record<string, unknown>) => {
          queueMicrotask(() => {
            (agentService as any).resolveSendAck({
              type: 'ack',
              action: 'send_message',
              conversation_id: payload.conversation_id,
            });
          });
          return true;
        });

      try {
        await agentService.chat(
          {
            conversation_id: 'conv-1',
            message: '你好',
            project_id: 'proj-1',
            preferred_language: 'zh-CN',
          },
          {}
        );

        expect(sendSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            type: 'send_message',
            conversation_id: 'conv-1',
            preferred_language: 'zh-CN',
          })
        );
      } finally {
        sendSpy.mockRestore();
        isConnectedSpy.mockRestore();
      }
    });
  });

  describe('SubAgent control commands', () => {
    beforeEach(async () => {
      localStorage.setItem(
        'memstack-auth-storage',
        JSON.stringify({ state: { token: 'protocol-fixture-token' } })
      );
      await agentService.connectSession();
    });
    it('resolves kill_run only after the matching structured acknowledgement', async () => {
      const sendSpy = vi
        .spyOn(agentService as any, 'send')
        .mockImplementation((payload: Record<string, unknown>) => {
          queueMicrotask(() => {
            (agentService as any).handleMessage({
              type: 'control_command_ack',
              action: 'kill_run',
              accepted: true,
              duplicate: false,
              reason_code: null,
              conversation_id: payload.conversation_id,
              project_id: 'project-1',
              run_id: payload.run_id,
              run_revision: payload.expected_run_revision,
              idempotency_key: payload.idempotency_key,
              cascade: payload.cascade,
            });
          });
          return true;
        });

      try {
        await expect(
          agentService.killSubAgent('conv-1', 'run-1', {
            expectedRunRevision: 7,
            idempotencyKey: 'kill-idempotency-1',
            cascade: true,
          })
        ).resolves.toEqual(
          expect.objectContaining({
            accepted: true,
            idempotency_key: 'kill-idempotency-1',
            run_revision: 7,
          })
        );
        expect(sendSpy).toHaveBeenCalledWith({
          type: 'kill_run',
          conversation_id: 'conv-1',
          run_id: 'run-1',
          expected_run_revision: 7,
          idempotency_key: 'kill-idempotency-1',
          cascade: true,
        });
      } finally {
        sendSpy.mockRestore();
      }
    });

    it('preserves a structured steer rejection for the caller', async () => {
      const sendSpy = vi
        .spyOn(agentService as any, 'send')
        .mockImplementation((payload: Record<string, unknown>) => {
          queueMicrotask(() => {
            (agentService as any).handleMessage({
              type: 'control_command_ack',
              action: 'steer',
              accepted: false,
              duplicate: false,
              reason_code: 'run_revision_conflict',
              conversation_id: payload.conversation_id,
              project_id: 'project-1',
              run_id: payload.run_id,
              run_revision: 9,
              idempotency_key: payload.idempotency_key,
            });
          });
          return true;
        });

      try {
        await expect(
          agentService.steerSubAgent('conv-1', 'run-1', 'Use the focused tests', {
            expectedRunRevision: 8,
          })
        ).resolves.toEqual(
          expect.objectContaining({
            accepted: false,
            reason_code: 'run_revision_conflict',
            run_revision: 9,
          })
        );
        expect(sendSpy).toHaveBeenCalledWith({
          type: 'steer',
          conversation_id: 'conv-1',
          run_id: 'run-1',
          instruction: 'Use the focused tests',
          expected_run_revision: 8,
          idempotency_key: 'subagent-steer-test-session-id',
        });
      } finally {
        sendSpy.mockRestore();
      }
    });
  });
});

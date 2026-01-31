/**
 * Unit tests for useWebSocket hook.
 *
 * TDD Phase 1 (RED): Tests written before implementation.
 *
 * These tests verify that:
 * 1. WebSocket connection is established correctly
 * 2. Connection status is tracked
 * 3. Messages can be sent
 * 4. Connection can be disconnected
 * 5. Reconnection logic works
 * 6. Event callbacks are invoked
 * 7. Cleanup happens on unmount
 * 8. Edge cases are handled
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';
import { useWebSocket } from '../../hooks/useWebSocket';

// Global tracking for the most recently created WebSocket instance
let lastCreatedWebSocket: MockWebSocket | null = null;
let allCreatedWebSockets: MockWebSocket[] = [];

// Mock WebSocket class
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  url: string;
  readyState: number = MockWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  private sentMessages: string[] = [];

  constructor(url: string) {
    this.url = url;
    // Track instance globally
    // eslint-disable-next-line @typescript-eslint/no-this-alias
    lastCreatedWebSocket = this;
    allCreatedWebSockets.push(this);

    // Simulate async connection
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      this.onopen?.(new Event('open'));
    }, 0);
  }

  send(data: string) {
    this.sentMessages.push(data);
  }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close'));
  }

  // Test helpers
  simulateOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.(new Event('open'));
  }

  simulateMessage(data: string) {
    this.onmessage?.(new MessageEvent('message', { data }));
  }

  simulateError(error: Event) {
    this.onerror?.(error);
  }

  simulateClose(code?: number, reason?: string) {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close', { code, reason }));
  }

  getSentMessages() {
    return [...this.sentMessages];
  }
}

describe('useWebSocket', () => {
  let originalWebSocket: typeof WebSocket;

  beforeEach(() => {
    // Store original WebSocket
    originalWebSocket = global.WebSocket as any;

    // Clear instances
    lastCreatedWebSocket = null;
    allCreatedWebSockets = [];

    // Mock WebSocket global
    global.WebSocket = MockWebSocket as any;

    vi.clearAllMocks();
    vi.useFakeTimers();
  });

  afterEach(() => {
    cleanup();
    vi.runOnlyPendingTimers();
    vi.useRealTimers();

    // Restore original WebSocket
    global.WebSocket = originalWebSocket;

    // Clean up instances
    allCreatedWebSockets.forEach(ws => ws.close());
    lastCreatedWebSocket = null;
    allCreatedWebSockets = [];
  });

  describe('Initial State', () => {
    it('should start with closed status', () => {
      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080' })
      );

      expect(result.current.status).toBe('closed');
      expect(result.current.ws).toBeNull();
    });

    it('should not auto-connect unless connect is called', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
        })
      );

      // Should not have created a WebSocket instance
      expect(result.current.ws).toBeNull();
      expect(result.current.status).toBe('closed');
    });

    it('should accept function for url', () => {
      const getUrl = () => 'ws://localhost:8080';
      const { result } = renderHook(() =>
        useWebSocket({ url: getUrl })
      );

      expect(result.current.status).toBe('closed');
    });
  });

  describe('Connection', () => {
    it('should connect when connect is called', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
        })
      );

      act(() => {
        result.current.connect();
      });

      // Advance timers to trigger async connection
      act(() => {
        vi.advanceTimersByTime(0);
      });

      expect(lastCreatedWebSocket).not.toBeNull();
      expect(result.current.ws).not.toBeNull();
    });

    it('should update status to connecting when connection starts', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
        })
      );

      act(() => {
        result.current.connect();
      });

      // Should be connecting immediately after connect() call
      expect(result.current.status).toBe('connecting');
    });

    it('should update status to open when connection is established', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
        })
      );

      act(() => {
        result.current.connect();
      });

      // Advance timers to trigger async connection
      act(() => {
        vi.advanceTimersByTime(0);
      });

      expect(result.current.status).toBe('open');
    });

    it('should call onOpen callback when connection opens', () => {
      const onOpen = vi.fn();

      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
          onOpen,
        })
      );

      act(() => {
        result.current.connect();
        vi.advanceTimersByTime(0);
      });

      expect(onOpen).toHaveBeenCalled();
    });

    it('should use function url for connection', () => {
      let connectionCount = 0;
      const getUrl = () => {
        connectionCount++;
        return `ws://localhost:8080/${connectionCount}`;
      };

      const { result } = renderHook(() =>
        useWebSocket({
          url: getUrl,
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      expect(connectionCount).toBeGreaterThan(0);
    });
  });

  describe('Sending Messages', () => {
    it('should send string messages', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      act(() => {
        result.current.send('hello world');
      });

      expect(lastCreatedWebSocket?.getSentMessages()).toContain('hello world');
    });

    it('should send object messages as JSON string', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      const message = { type: 'greeting', content: 'hello' };
      act(() => {
        result.current.send(message);
      });

      expect(lastCreatedWebSocket?.getSentMessages()).toContain(JSON.stringify(message));
    });

    it('should not send message when not connected', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
        })
      );

      expect(() => {
        result.current.send('test');
      }).not.toThrow();

      expect(lastCreatedWebSocket).toBeNull();
    });
  });

  describe('Disconnection', () => {
    it('should disconnect when disconnect is called', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      act(() => {
        result.current.disconnect();
      });

      expect(result.current.status).toBe('closed');
    });

    it('should call onClose callback when disconnected', () => {
      const onClose = vi.fn();

      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
          onClose,
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      act(() => {
        result.current.disconnect();
      });

      expect(onClose).toHaveBeenCalled();
    });

    it('should handle server-initiated close', () => {
      const onClose = vi.fn();

      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
          onClose,
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      act(() => {
        lastCreatedWebSocket?.simulateClose(1000, 'Normal closure');
      });

      expect(result.current.status).toBe('closed');
      expect(onClose).toHaveBeenCalled();
    });
  });

  describe('Message Handling', () => {
    it('should call onMessage callback when message received', () => {
      const onMessage = vi.fn();

      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
          onMessage,
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      act(() => {
        lastCreatedWebSocket?.simulateMessage('hello from server');
      });

      expect(onMessage).toHaveBeenCalledWith(
        expect.objectContaining({ data: 'hello from server' })
      );
    });

    it('should handle multiple messages', () => {
      const onMessage = vi.fn();

      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
          onMessage,
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      act(() => {
        lastCreatedWebSocket?.simulateMessage('message 1');
        lastCreatedWebSocket?.simulateMessage('message 2');
        lastCreatedWebSocket?.simulateMessage('message 3');
      });

      expect(onMessage).toHaveBeenCalledTimes(3);
    });
  });

  describe('Error Handling', () => {
    it('should call onError callback when error occurs', () => {
      const onError = vi.fn();

      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
          onError,
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      act(() => {
        const errorEvent = new Event('error');
        lastCreatedWebSocket?.simulateError(errorEvent);
      });

      expect(onError).toHaveBeenCalled();
    });

    it('should update status to closed after error', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
          reconnect: false,
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      act(() => {
        // Simulate error followed by close (realistic behavior)
        lastCreatedWebSocket?.simulateError(new Event('error'));
        lastCreatedWebSocket?.simulateClose();
      });

      expect(result.current.status).toBe('closed');
    });
  });

  describe('Reconnection', () => {
    it('should reconnect when reconnect is true', () => {
      const onOpen = vi.fn();

      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
          reconnect: true,
          reconnectInterval: 100,
          onOpen,
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      expect(onOpen).toHaveBeenCalledTimes(1);

      // Simulate connection close
      act(() => {
        lastCreatedWebSocket?.simulateClose();
      });

      // Wait for reconnection (past the 100ms reconnectInterval)
      act(() => {
        vi.advanceTimersByTime(150);
      });

      // Should have reconnected
      expect(onOpen).toHaveBeenCalledTimes(2);
    });

    it('should not reconnect when reconnect is false', () => {
      const onOpen = vi.fn();

      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
          reconnect: false,
          onOpen,
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      expect(onOpen).toHaveBeenCalledTimes(1);

      // Simulate connection close
      act(() => {
        lastCreatedWebSocket?.simulateClose();
      });

      // Wait longer than reconnect interval
      act(() => {
        vi.advanceTimersByTime(150);
      });

      // Should NOT have reconnected
      expect(onOpen).toHaveBeenCalledTimes(1);
    });

    it('should respect maxReconnectAttempts', () => {
      const onOpen = vi.fn();

      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
          reconnect: true,
          reconnectInterval: 50,
          maxReconnectAttempts: 2,
          onOpen,
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for initial connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      // Initial connection
      expect(onOpen).toHaveBeenCalledTimes(1);

      // Close connection - will trigger reconnect
      act(() => {
        lastCreatedWebSocket?.simulateClose();
      });

      // Wait for first reconnect (past the 50ms reconnectInterval)
      act(() => {
        vi.advanceTimersByTime(60);
      });

      // Should have first reconnect
      expect(onOpen).toHaveBeenCalledTimes(2);

      // Close first reconnect - will trigger second reconnect
      act(() => {
        lastCreatedWebSocket?.simulateClose();
      });

      // Wait for second reconnect
      act(() => {
        vi.advanceTimersByTime(60);
      });

      // Should have second reconnect (max attempts reached: initial + 2 reconnects)
      expect(onOpen).toHaveBeenCalledTimes(3);
    });
  });

  describe('Cleanup', () => {
    it('should close connection on unmount', () => {
      const { result, unmount } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      const wsBeforeUnmount = result.current.ws;

      unmount();

      // WebSocket should be closed after unmount
      expect(wsBeforeUnmount?.readyState).toBe(MockWebSocket.CLOSED);
    });

    it('should not reconnect after unmount', () => {
      const onOpen = vi.fn();

      const { result, unmount } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
          reconnect: true,
          reconnectInterval: 50,
          onOpen,
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      unmount();

      // Wait for potential reconnect
      act(() => {
        vi.advanceTimersByTime(100);
      });

      // Should only have initial connection, no reconnect
      expect(onOpen).toHaveBeenCalledTimes(1);
    });
  });

  describe('Edge Cases', () => {
    it('should handle multiple connect calls', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
        })
      );

      act(() => {
        result.current.connect();
        result.current.connect();
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      // Should have one connection
      expect(result.current.ws).not.toBeNull();
      expect(allCreatedWebSockets.length).toBe(1);
    });

    it('should handle disconnect before connection completes', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
        })
      );

      act(() => {
        result.current.connect();
        result.current.disconnect();
      });

      expect(result.current.status).toBe('closed');
    });

    it('should handle connect after disconnect', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
        })
      );

      // First connection
      act(() => {
        result.current.connect();
      });

      act(() => {
        vi.advanceTimersByTime(10);
      });

      expect(result.current.status).toBe('open');

      // Disconnect
      act(() => {
        result.current.disconnect();
      });

      expect(result.current.status).toBe('closed');

      // Reconnect
      act(() => {
        result.current.connect();
      });

      act(() => {
        vi.advanceTimersByTime(10);
      });

      expect(result.current.status).toBe('open');
    });

    it('should handle empty url', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: '',
        })
      );

      expect(() => {
        result.current.connect();
      }).not.toThrow();
    });

    it('should handle very long messages', () => {
      const { result } = renderHook(() =>
        useWebSocket({
          url: 'ws://localhost:8080',
        })
      );

      act(() => {
        result.current.connect();
      });

      // Wait for connection
      act(() => {
        vi.advanceTimersByTime(10);
      });

      const longMessage = 'x'.repeat(10000);

      act(() => {
        result.current.send(longMessage);
      });

      expect(lastCreatedWebSocket?.getSentMessages()).toContain(longMessage);
    });
  });
});

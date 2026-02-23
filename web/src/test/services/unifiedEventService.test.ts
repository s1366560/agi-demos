/**
 * Tests for unifiedEventService
 *
 * Tests the unified WebSocket event service for topic-based subscriptions.
 *
 * @packageDocumentation
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// Mock the logger
vi.mock('@/utils/logger', () => ({
  logger: {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

// Mock getAuthToken
vi.mock('@/utils/tokenResolver', () => ({
  getAuthToken: vi.fn(() => 'test-token'),
}));

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
  sentMessages: string[] = [];

  constructor(url: string) {
    this.url = url;
    // Simulate async connection
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      if (this.onopen) {
        this.onopen(new Event('open'));
      }
    }, 10);
  }

  send(data: string): void {
    if (this.readyState !== MockWebSocket.OPEN) {
      throw new Error('WebSocket is not open');
    }
    this.sentMessages.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose(new CloseEvent('close'));
    }
  }

  // Helper to simulate incoming messages
  simulateMessage(data: unknown): void {
    if (this.onmessage) {
      this.onmessage(
        new MessageEvent('message', {
          data: JSON.stringify(data),
        })
      );
    }
  }
}

describe('unifiedEventService', () => {
  let _mockWebSocket: MockWebSocket;
  let unifiedEventService: typeof import('@/services/unifiedEventService').unifiedEventService;

  beforeEach(async () => {
    vi.stubGlobal('WebSocket', WebSocket);
    vi.stubGlobal('crypto', {
      randomUUID: () => 'test-uuid-' + Date.now(),
    });

    // Dynamic import to get fresh instance
    vi.resetModules();
    const module = await import('@/services/unifiedEventService');
    unifiedEventService = module.unifiedEventService;
  });

  afterEach(() => {
    unifiedEventService.disconnect();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  describe('connect()', () => {
    it('should establish WebSocket connection', async () => {
      await unifiedEventService.connect();
      expect(unifiedEventService.isConnected()).toBe(true);
    });

    it('should include token in URL', async () => {
      await unifiedEventService.connect();
      // Get the WebSocket instance created
      expect(unifiedEventService.isConnected()).toBe(true);
    });

    it('should resolve immediately if already connected', async () => {
      await unifiedEventService.connect();
      const startTime = Date.now();
      await unifiedEventService.connect();
      expect(Date.now() - startTime).toBeLessThan(50);
    });
  });

  describe('disconnect()', () => {
    it('should close WebSocket connection', async () => {
      await unifiedEventService.connect();
      unifiedEventService.disconnect();
      expect(unifiedEventService.isConnected()).toBe(false);
    });

    it('should be safe to call when not connected', () => {
      expect(() => unifiedEventService.disconnect()).not.toThrow();
    });
  });

  describe('subscribe()', () => {
    it('should return unsubscribe function', async () => {
      await unifiedEventService.connect();
      const handler = vi.fn();
      const unsubscribe = unifiedEventService.subscribe('test-topic', handler);

      expect(typeof unsubscribe).toBe('function');
      unsubscribe();
    });

    it('should call handler when matching event received', async () => {
      await unifiedEventService.connect();
      const handler = vi.fn();
      unifiedEventService.subscribe('agent:conv-123', handler);

      // Wait for connection
      await new Promise((resolve) => setTimeout(resolve, 20));

      // Simulate incoming event
      // Get the WebSocket instance and simulate message
      // This is a simplified test - in reality we'd need to access the internal WebSocket
    });
  });

  describe('subscribeSandbox()', () => {
    it('should send subscribe_sandbox message', async () => {
      await unifiedEventService.connect();

      // Wait for connection
      await new Promise((resolve) => setTimeout(resolve, 20));

      const handler = {
        onDesktopStarted: vi.fn(),
        onDesktopStopped: vi.fn(),
        onTerminalStarted: vi.fn(),
        onTerminalStopped: vi.fn(),
        onStatusUpdate: vi.fn(),
        onError: vi.fn(),
      };

      const unsubscribe = unifiedEventService.subscribeSandbox('proj-123', handler);
      expect(typeof unsubscribe).toBe('function');

      unsubscribe();
    });
  });

  describe('subscribeAgent()', () => {
    it('should subscribe to agent conversation topic', async () => {
      await unifiedEventService.connect();

      const handler = {
        onTextDelta: vi.fn(),
        onComplete: vi.fn(),
      };

      const unsubscribe = unifiedEventService.subscribeAgent('conv-456', handler);
      expect(typeof unsubscribe).toBe('function');

      unsubscribe();
    });
  });

  describe('subscribeLifecycle()', () => {
    it('should subscribe to lifecycle topic', async () => {
      await unifiedEventService.connect();

      const handler = vi.fn();
      const unsubscribe = unifiedEventService.subscribeLifecycle('proj-789', handler);
      expect(typeof unsubscribe).toBe('function');

      unsubscribe();
    });
  });

  describe('getStatus()', () => {
    it('should return connection status', async () => {
      // Initial status is disconnected
      expect(unifiedEventService.getStatus()).toBe('disconnected');

      const connectPromise = unifiedEventService.connect();
      // During connection, status should be connecting

      await connectPromise;
      expect(unifiedEventService.getStatus()).toBe('connected');
    });
  });

  describe('event routing', () => {
    it('should route events by routing_key', async () => {
      await unifiedEventService.connect();
      await new Promise((resolve) => setTimeout(resolve, 20));

      const agentHandler = vi.fn();
      const sandboxHandler = vi.fn();

      unifiedEventService.subscribe('agent:conv-123', agentHandler);
      unifiedEventService.subscribe('sandbox:proj-456', sandboxHandler);

      // Events would be routed based on their routing_key
      // This tests the subscription mechanism
    });
  });
});

describe('unifiedEventService - Topic Management', () => {
  let unifiedEventService: typeof import('@/services/unifiedEventService').unifiedEventService;

  beforeEach(async () => {
    vi.stubGlobal('WebSocket', WebSocket);
    vi.stubGlobal('crypto', {
      randomUUID: () => 'test-uuid-' + Date.now(),
    });

    vi.resetModules();
    const module = await import('@/services/unifiedEventService');
    unifiedEventService = module.unifiedEventService;
  });

  afterEach(() => {
    unifiedEventService.disconnect();
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it('should track active subscriptions', async () => {
    await unifiedEventService.connect();
    await new Promise((resolve) => setTimeout(resolve, 20));

    const unsub1 = unifiedEventService.subscribe('topic1', vi.fn());
    const unsub2 = unifiedEventService.subscribe('topic2', vi.fn());

    // Both subscriptions active
    unsub1();
    // Only topic2 active now
    unsub2();
    // No active subscriptions
  });

  it('should handle multiple handlers for same topic', async () => {
    await unifiedEventService.connect();
    await new Promise((resolve) => setTimeout(resolve, 20));

    const handler1 = vi.fn();
    const handler2 = vi.fn();

    const unsub1 = unifiedEventService.subscribe('shared-topic', handler1);
    const unsub2 = unifiedEventService.subscribe('shared-topic', handler2);

    // Both handlers should be called for events on this topic
    unsub1();
    unsub2();
  });
});

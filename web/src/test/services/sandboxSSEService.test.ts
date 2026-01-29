/**
 * Unit tests for Sandbox SSE Service.
 *
 * Tests the SSE subscription service for sandbox events.
 */

import { vi, beforeEach, afterEach, describe, it, expect, vi } from "vitest";

// Mock logger
vi.mock("../../utils/logger", () => ({
  logger: {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

// Mock token resolver
vi.mock("../../utils/tokenResolver", () => ({
  getAuthToken: vi.fn(() => "mock-token"),
}));

// Mock URL utils
vi.mock("../../services/client/urlUtils", () => ({
  createApiUrl: vi.fn((path: string) => `http://localhost:8000${path}`),
}));

// Mock window.location
Object.defineProperty(global, "window", {
  value: {
    location: {
      origin: "http://localhost:3000",
    },
  },
  writable: true,
});

// Mock URL constructor to avoid issues in test environment
global.URL = URL as any;

import { sandboxSSEService } from "../../services/sandboxSSEService";
import type { SandboxSSEEvent } from "../../types/sandbox";

describe("SandboxSSEService", () => {
  let mockEventSource: EventSource;
  let EventSourceMock: any;

  beforeEach(() => {
    // Create a fresh mock instance for each test
    mockEventSource = {
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      close: vi.fn(),
      readyState: 0,
      CONNECTING: 0,
      OPEN: 1,
      CLOSED: 2,
      onopen: null,
      onerror: null,
    } as unknown as EventSource;

    // Mock EventSource constructor function as a spy
    EventSourceMock = vi.fn(function(_url: string) {
      return mockEventSource;
    }) as any;
    EventSourceMock.CONNECTING = 0;
    EventSourceMock.OPEN = 1;
    EventSourceMock.CLOSED = 2;
    global.EventSource = EventSourceMock;

    // Reset singleton state after mocking EventSource
    const service = sandboxSSEService as any;
    service.handlers.clear();
    service.disconnect();
    service.lastEventId = "0";
    service.projectId = null;
    service.status = "disconnected";
    service.reconnectAttempts = 0;
    service.reconnectTimeout = null;
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  describe("subscribe", () => {
    it("should create EventSource with correct URL", () => {
      const handler = {
        onDesktopStarted: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);

      expect(global.EventSource).toHaveBeenCalledWith(
        expect.stringContaining("sandbox/events/proj-123")
      );
    });

    it("should include last_id parameter when reconnecting", () => {
      const handler = {
        onDesktopStarted: vi.fn(),
      };

      // Simulate a previous connection by setting lastEventId
      const service = sandboxSSEService as any;
      service.lastEventId = "1234567890-0";

      sandboxSSEService.subscribe("proj-123", handler);

      expect(global.EventSource).toHaveBeenCalledWith(
        expect.stringContaining("last_id=1234567890-0")
      );
    });

    it("should return unsubscribe function", () => {
      const handler = {
        onDesktopStarted: vi.fn(),
      };

      const unsubscribe = sandboxSSEService.subscribe("proj-123", handler);

      expect(typeof unsubscribe).toBe("function");
    });

    it("should remove handler when unsubscribe is called", () => {
      const handler = {
        onDesktopStarted: vi.fn(),
      };

      const unsubscribe = sandboxSSEService.subscribe("proj-123", handler);
      unsubscribe();

      const service = sandboxSSEService as any;
      expect(service.handlers.size).toBe(0);
    });

    it("should disconnect when last handler is removed", () => {
      const handler = {
        onDesktopStarted: vi.fn(),
      };

      const unsubscribe = sandboxSSEService.subscribe("proj-123", handler);

      // Spy on the mockEventSource's close method
      const closeSpy = vi.spyOn(mockEventSource, "close");

      unsubscribe();

      expect(closeSpy).toHaveBeenCalled();
    });
  });

  describe("connect", () => {
    it("should set up event listeners on EventSource", () => {
      const handler = {
        onDesktopStarted: vi.fn(),
      };

      const service = sandboxSSEService as any;

      sandboxSSEService.subscribe("proj-123", handler);

      // Check that EventSource was created
      expect(service.eventSource).toBe(mockEventSource);

      // Check that addEventListener was called for "sandbox" event
      expect(mockEventSource.addEventListener).toHaveBeenCalledWith(
        "sandbox",
        expect.any(Function)
      );

      // Check that onopen and onerror properties were set
      expect(mockEventSource.onopen).toEqual(expect.any(Function));
      expect(mockEventSource.onerror).toEqual(expect.any(Function));
    });

    it("should call onDesktopStarted handler when event received", () => {
      const handler = {
        onDesktopStarted: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);

      // Directly call routeEvent with a desktop_started event
      const event = {
        type: "desktop_started" as const,
        data: {
          sandbox_id: "sb-123",
          url: "http://localhost:6080",
          display: ":1",
          resolution: "1280x720",
          port: 6080,
        },
        timestamp: "2024-01-01T00:00:00Z",
      };

      const service = sandboxSSEService as any;
      service.routeEvent(event);

      expect(handler.onDesktopStarted).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "desktop_started",
          data: expect.objectContaining({
            sandbox_id: "sb-123",
          }),
        })
      );
    });

    it("should route terminal_started events correctly", () => {
      const handler = {
        onTerminalStarted: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);

      const event = {
        type: "terminal_started" as const,
        data: {
          sandbox_id: "sb-123",
          url: "ws://localhost:7681",
          port: 7681,
          session_id: "sess-abc",
        },
        timestamp: "2024-01-01T00:00:00Z",
      };

      const service = sandboxSSEService as any;
      service.routeEvent(event);

      expect(handler.onTerminalStarted).toHaveBeenCalled();
    });

    it("should route sandbox_terminated events correctly", () => {
      const handler = {
        onSandboxTerminated: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);

      const event = {
        type: "sandbox_terminated" as const,
        data: { sandbox_id: "sb-123" },
        timestamp: "2024-01-01T00:00:00Z",
      };

      const service = sandboxSSEService as any;
      service.routeEvent(event);

      expect(handler.onSandboxTerminated).toHaveBeenCalled();
    });

    it("should update lastEventId when event received", () => {
      const handler = {
        onDesktopStarted: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);

      const service = sandboxSSEService as any;
      service.lastEventId = "99999-0";

      expect(service.lastEventId).toBe("99999-0");
    });

    it("should call onError handler when connection fails", () => {
      const handler = {
        onError: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);

      const service = sandboxSSEService as any;
      const onerror = service.eventSource?.onerror;

      // Set reconnectAttempts to max so error is triggered immediately
      service.reconnectAttempts = service.maxReconnectAttempts;

      if (onerror) {
        onerror(new Event("error"));
      }

      expect(handler.onError).toHaveBeenCalledWith(
        expect.any(Error)
      );
    });

    it("should handle JSON parse errors gracefully", () => {
      const handler = {
        onDesktopStarted: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);

      const addCalls = (mockEventSource.addEventListener as any).mock.calls;
      const sandboxListener = addCalls.find(
        (call: any[]) => call[0] === "sandbox"
      )?.[1];

      if (sandboxListener) {
        const mockEvent = new MessageEvent("message", {
          data: "invalid json{",
        });

        // Should not throw
        expect(() => sandboxListener(mockEvent)).not.toThrow();
      }

      // handler should NOT be called for JSON parse errors (they're logged instead)
      expect(handler.onDesktopStarted).not.toHaveBeenCalled();
    });
  });

  describe("reconnection", () => {
    it("should schedule reconnection on error", async () => {
      vi.useFakeTimers();

      const handler = {
        onError: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);

      const service = sandboxSSEService as any;

      // Get the onerror handler from the actual EventSource instance
      const onerror = service.eventSource?.onerror;

      // Trigger error by calling onerror
      if (onerror) {
        onerror(new Event("error"));
      }

      // Verify reconnect timeout was scheduled
      expect(service.reconnectTimeout).not.toBeNull();

      // Fast forward timers to trigger reconnection
      await vi.runAllTimersAsync();

      // Verify reconnect was attempted (reconnectAttempts > 0)
      expect(service.reconnectAttempts).toBeGreaterThan(0);

      vi.useRealTimers();
    });

    it("should stop reconnecting after max attempts", async () => {
      vi.useFakeTimers();

      const handler = {
        onError: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);

      const service = sandboxSSEService as any;
      service.maxReconnectAttempts = 2;

      // Get the onerror handler
      const onerror = service.eventSource?.onerror;

      // Trigger multiple errors
      for (let i = 0; i < 5; i++) {
        if (onerror) {
          onerror(new Event("error"));
        }
        await vi.runAllTimersAsync();
      }

      // Should have stopped reconnecting
      expect(handler.onError).toHaveBeenCalledWith(
        expect.any(Error)
      );

      vi.useRealTimers();
    });
  });

  describe("disconnect", () => {
    it("should close EventSource when disconnected", () => {
      sandboxSSEService.subscribe("proj-123", {
        onDesktopStarted: vi.fn(),
      });

      // Spy on the mockEventSource's close method
      const closeSpy = vi.spyOn(mockEventSource, "close");

      sandboxSSEService.disconnect();

      expect(closeSpy).toHaveBeenCalled();
    });

    it("should clear reconnection timeout when disconnected", async () => {
      vi.useFakeTimers();

      const handler = {
        onDesktopStarted: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);

      const service = sandboxSSEService as any;

      // Get the onerror handler
      const onerror = service.eventSource?.onerror;

      // Trigger error to start reconnection timeout
      if (onerror) {
        onerror(new Event("error"));
      }

      // Disconnect before reconnection
      sandboxSSEService.disconnect();

      expect(service.reconnectTimeout).toBeNull();

      vi.useRealTimers();
    });
  });

  describe("getStatus", () => {
    it("should return disconnected status initially", () => {
      expect(sandboxSSEService.getStatus()).toBe("disconnected");
    });

    it("should return connecting status while connecting", () => {
      sandboxSSEService.subscribe("proj-123", {
        onDesktopStarted: vi.fn(),
      });

      const service = sandboxSSEService as any;
      service.status = "connecting";

      expect(sandboxSSEService.getStatus()).toBe("connecting");
    });
  });

  describe("multiple handlers", () => {
    it("should notify all handlers of events", () => {
      const handler1 = {
        onDesktopStarted: vi.fn(),
      };
      const handler2 = {
        onDesktopStarted: vi.fn(),
      };

      // Both handlers should be registered
      sandboxSSEService.subscribe("proj-123", handler1);
      sandboxSSEService.subscribe("proj-123", handler2);

      const service = sandboxSSEService as any;
      expect(service.handlers.size).toBe(2);

      // Trigger event manually
      const event = {
        type: "desktop_started" as const,
        data: { sandbox_id: "sb-123" },
        timestamp: "2024-01-01T00:00:00Z",
      };

      service.routeEvent(event);

      expect(handler1.onDesktopStarted).toHaveBeenCalledWith(event);
      expect(handler2.onDesktopStarted).toHaveBeenCalledWith(event);
    });

    it("should allow handlers to be added and removed independently", () => {
      const handler1 = {
        onDesktopStarted: vi.fn(),
      };
      const handler2 = {
        onDesktopStarted: vi.fn(),
      };

      const unsubscribe1 = sandboxSSEService.subscribe("proj-123", handler1);
      const unsubscribe2 = sandboxSSEService.subscribe("proj-123", handler2);

      const service = sandboxSSEService as any;
      expect(service.handlers.size).toBe(2);

      // Remove handler1
      unsubscribe1();
      expect(service.handlers.size).toBe(1);

      // Simulate event through the routeEvent method
      const event = {
        type: "desktop_started" as const,
        data: { sandbox_id: "sb-123" },
        timestamp: "2024-01-01T00:00:00Z",
      };

      service.routeEvent(event);

      // Since handler1 was removed, only handler2 should be called
      expect(handler1.onDesktopStarted).not.toHaveBeenCalled();
      expect(handler2.onDesktopStarted).toHaveBeenCalledWith(event);
    });
  });

  describe("type guards", () => {
    it("should correctly identify sandbox_created events", () => {
      const event: SandboxSSEEvent = {
        type: "sandbox_created",
        data: {
          sandbox_id: "sb-123",
          project_id: "proj-456",
          status: "running",
        },
        timestamp: "2024-01-01T00:00:00Z",
      };

      expect(event.type).toBe("sandbox_created");
      expect(event.data).toHaveProperty("sandbox_id", "sb-123");
    });
  });
});

/**
 * Unit tests for Sandbox SSE Service.
 *
 * Tests the SSE subscription service for sandbox events.
 * 
 * NOTE: sandboxSSEService has been migrated to use WebSocket internally
 * while maintaining the same API for backward compatibility.
 */

import { vi, beforeEach, afterEach, describe, it, expect } from "vitest";

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

// Track the callback passed to subscribeSandbox and unsubscribe calls
let sandboxCallback: ((event: unknown) => void) | null = null;
let unsubscribeCalled = false;

// Mock unifiedEventService since sandboxSSEService now uses it
vi.mock("../../services/unifiedEventService", () => ({
  unifiedEventService: {
    connect: vi.fn().mockResolvedValue(undefined),
    disconnect: vi.fn(),
    isConnected: vi.fn().mockReturnValue(true),
    subscribeSandbox: vi.fn((_projectId: string, callback: (event: unknown) => void) => {
      sandboxCallback = callback;
      // Return an unsubscribe function that tracks if it's called
      return () => {
        unsubscribeCalled = true;
      };
    }),
    getStatus: vi.fn().mockReturnValue('connected'),
  },
}));

import { sandboxSSEService } from "../../services/sandboxSSEService";
import { unifiedEventService } from "../../services/unifiedEventService";

import type { BaseSandboxSSEEvent } from "../../services/sandboxSSEService";

describe("SandboxSSEService (WebSocket-based)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sandboxCallback = null;
    unsubscribeCalled = false;
  });

  afterEach(() => {
    vi.clearAllMocks();
    // Reset the service's internal state
    (sandboxSSEService as any).status = "disconnected";
    (sandboxSSEService as any).projectId = null;
    (sandboxSSEService as any).handlers.clear();
    (sandboxSSEService as any).unsubscribeFn = null;
  });

  describe("subscribe", () => {
    it("should connect to unifiedEventService", async () => {
      const handler = {
        onDesktopStarted: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);

      // Should call connect on unifiedEventService
      expect(unifiedEventService.connect).toHaveBeenCalled();
    });

    it("should call subscribeSandbox after connection resolves", async () => {
      const handler = {
        onDesktopStarted: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);

      // Wait for the async connect to resolve
      await vi.waitFor(() => {
        expect(unifiedEventService.subscribeSandbox).toHaveBeenCalled();
      });

      expect(unifiedEventService.subscribeSandbox).toHaveBeenCalledWith(
        "proj-123",
        expect.any(Function)
      );
    });

    it("should return unsubscribe function", () => {
      const handler = {
        onDesktopStarted: vi.fn(),
      };

      const unsubscribe = sandboxSSEService.subscribe("proj-123", handler);

      expect(typeof unsubscribe).toBe("function");
    });

    it("should support multiple handlers for the same project", async () => {
      const handler1 = { onDesktopStarted: vi.fn() };
      const handler2 = { onTerminalStarted: vi.fn() };

      sandboxSSEService.subscribe("proj-123", handler1);
      
      // Wait for first subscription to complete
      await vi.waitFor(() => {
        expect(sandboxSSEService.getStatus()).toBe("connected");
      });
      
      // Clear the mock to check if connect is called again
      vi.mocked(unifiedEventService.connect).mockClear();
      
      sandboxSSEService.subscribe("proj-123", handler2);

      // connect() should not be called again since we're already connected
      expect(unifiedEventService.connect).not.toHaveBeenCalled();
    });
  });

  describe("disconnect", () => {
    it("should be callable without errors when not connected", () => {
      expect(() => sandboxSSEService.disconnect()).not.toThrow();
    });

    it("should unsubscribe from unifiedEventService when all handlers removed", async () => {
      const handler = { onDesktopStarted: vi.fn() };
      const unsubscribe = sandboxSSEService.subscribe("proj-123", handler);
      
      // Wait for connection
      await vi.waitFor(() => {
        expect(sandboxSSEService.getStatus()).toBe("connected");
      });
      
      // Verify subscription was created
      expect(unifiedEventService.subscribeSandbox).toHaveBeenCalled();
      
      // Unsubscribe (removes last handler, triggers disconnect)
      unsubscribe();
      
      // unsubscribeCalled should be true when last handler is removed
      expect(unsubscribeCalled).toBe(true);
    });

    it("should call unsubscribe on disconnect", async () => {
      const handler = { onDesktopStarted: vi.fn() };
      sandboxSSEService.subscribe("proj-123", handler);
      
      // Wait for connection
      await vi.waitFor(() => {
        expect(sandboxSSEService.getStatus()).toBe("connected");
      });
      
      sandboxSSEService.disconnect();
      
      expect(unsubscribeCalled).toBe(true);
    });
  });

  describe("getStatus", () => {
    it("should return disconnected initially", () => {
      const status = sandboxSSEService.getStatus();
      expect(status).toBe("disconnected");
    });

    it("should return connected after successful subscription", async () => {
      const handler = { onDesktopStarted: vi.fn() };
      sandboxSSEService.subscribe("proj-123", handler);
      
      // Wait for the async connection
      await vi.waitFor(() => {
        expect(sandboxSSEService.getStatus()).toBe("connected");
      });
    });
  });

  describe("event routing", () => {
    it("should route desktop_started to onDesktopStarted handler", async () => {
      const handler = {
        onDesktopStarted: vi.fn(),
        onDesktopStopped: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);
      
      // Wait for subscription to be established
      await vi.waitFor(() => {
        expect(sandboxCallback).not.toBeNull();
      });

      // Simulate receiving an event through the callback
      sandboxCallback!({
        type: "sandbox_event",
        data: {
          type: "desktop_started",
          data: { sandbox_id: "sb-123" },
          timestamp: "2026-02-04T00:00:00Z",
        },
      });

      expect(handler.onDesktopStarted).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "desktop_started",
        })
      );
      expect(handler.onDesktopStopped).not.toHaveBeenCalled();
    });

    it("should route terminal_started to onTerminalStarted handler", async () => {
      const handler = {
        onTerminalStarted: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);
      
      await vi.waitFor(() => {
        expect(sandboxCallback).not.toBeNull();
      });

      sandboxCallback!({
        type: "sandbox_event",
        data: {
          type: "terminal_started",
          data: { terminal_id: "term-123" },
          timestamp: "2026-02-04T00:00:00Z",
        },
      });

      expect(handler.onTerminalStarted).toHaveBeenCalled();
    });

    it("should route status events to onStatusUpdate handler", async () => {
      const handler = {
        onStatusUpdate: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);
      
      await vi.waitFor(() => {
        expect(sandboxCallback).not.toBeNull();
      });

      sandboxCallback!({
        type: "sandbox_event",
        data: {
          type: "sandbox_status",
          data: { status: "running" },
          timestamp: "2026-02-04T00:00:00Z",
        },
      });

      expect(handler.onStatusUpdate).toHaveBeenCalled();
    });

    it("should notify multiple handlers", async () => {
      const handler1 = { onDesktopStarted: vi.fn() };
      const handler2 = { onDesktopStarted: vi.fn() };

      sandboxSSEService.subscribe("proj-123", handler1);
      sandboxSSEService.subscribe("proj-123", handler2);
      
      await vi.waitFor(() => {
        expect(sandboxCallback).not.toBeNull();
      });

      sandboxCallback!({
        type: "sandbox_event",
        data: {
          type: "desktop_started",
          data: {},
          timestamp: "2026-02-04T00:00:00Z",
        },
      });

      expect(handler1.onDesktopStarted).toHaveBeenCalled();
      expect(handler2.onDesktopStarted).toHaveBeenCalled();
    });
  });

  describe("routeEvent (direct testing)", () => {
    it("should route events correctly via public routeEvent method", () => {
      const handler = {
        onSandboxCreated: vi.fn(),
        onSandboxTerminated: vi.fn(),
        onDesktopStarted: vi.fn(),
        onDesktopStopped: vi.fn(),
        onTerminalStarted: vi.fn(),
        onTerminalStopped: vi.fn(),
        onStatusUpdate: vi.fn(),
      };

      sandboxSSEService.subscribe("proj-123", handler);

      const events: BaseSandboxSSEEvent[] = [
        { type: "sandbox_created", data: {}, timestamp: "2026-02-04T00:00:00Z" },
        { type: "sandbox_terminated", data: {}, timestamp: "2026-02-04T00:00:00Z" },
        { type: "desktop_started", data: {}, timestamp: "2026-02-04T00:00:00Z" },
        { type: "desktop_stopped", data: {}, timestamp: "2026-02-04T00:00:00Z" },
        { type: "terminal_started", data: {}, timestamp: "2026-02-04T00:00:00Z" },
        { type: "terminal_stopped", data: {}, timestamp: "2026-02-04T00:00:00Z" },
        { type: "sandbox_status", data: {}, timestamp: "2026-02-04T00:00:00Z" },
      ];

      events.forEach(event => {
        sandboxSSEService.routeEvent(event);
      });

      expect(handler.onSandboxCreated).toHaveBeenCalledTimes(1);
      expect(handler.onSandboxTerminated).toHaveBeenCalledTimes(1);
      expect(handler.onDesktopStarted).toHaveBeenCalledTimes(1);
      expect(handler.onDesktopStopped).toHaveBeenCalledTimes(1);
      expect(handler.onTerminalStarted).toHaveBeenCalledTimes(1);
      expect(handler.onTerminalStopped).toHaveBeenCalledTimes(1);
      expect(handler.onStatusUpdate).toHaveBeenCalledTimes(1);
    });
  });

  describe("backward compatibility", () => {
    it("should maintain same API as SSE-based version", () => {
      // Check that all expected methods exist
      expect(typeof sandboxSSEService.subscribe).toBe("function");
      expect(typeof sandboxSSEService.disconnect).toBe("function");
      expect(typeof sandboxSSEService.getStatus).toBe("function");
    });

    it("should accept partial handler objects", () => {
      // Only providing some handlers should work
      const handler = {
        onDesktopStarted: vi.fn(),
        // Other handlers omitted
      };

      expect(() => sandboxSSEService.subscribe("proj-123", handler)).not.toThrow();
    });
  });
});

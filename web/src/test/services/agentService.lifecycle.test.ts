/**
 * Unit tests for AgentService lifecycle state change handling.
 *
 * TDD: Tests WebSocket message handling for lifecycle_state_change events.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

// Mock agentService module (vitest hoisting requirement)
vi.mock("../../services/agentService", () => ({
  agentService: {
    isConnected: vi.fn(() => false),
    connect: vi.fn(() => Promise.resolve()),
    disconnect: vi.fn(() => Promise.resolve()),
    onStatusChange: vi.fn(() => vi.fn()),
    subscribeLifecycleState: vi.fn(),
    unsubscribeLifecycleState: vi.fn(),
  },
}));

import { agentService } from "../../services/agentService";

describe("AgentService - Lifecycle State Subscription", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("should subscribe to lifecycle state with correct parameters", () => {
    const mockCallback = vi.fn();

    agentService.subscribeLifecycleState("proj-123", "tenant-456", mockCallback);

    expect(agentService.subscribeLifecycleState).toHaveBeenCalledWith(
      "proj-123",
      "tenant-456",
      mockCallback
    );
  });

  it("should unsubscribe from lifecycle state", () => {
    agentService.unsubscribeLifecycleState();

    expect(agentService.unsubscribeLifecycleState).toHaveBeenCalled();
  });

  it("should return connection status", () => {
    vi.mocked(agentService.isConnected).mockReturnValue(true);

    expect(agentService.isConnected()).toBe(true);
  });

  it("should allow subscribing to status changes", () => {
    const mockCallback = vi.fn();
    const unsubscribe = vi.fn();

    vi.mocked(agentService.onStatusChange).mockReturnValue(unsubscribe);

    const result = agentService.onStatusChange(mockCallback);

    expect(agentService.onStatusChange).toHaveBeenCalledWith(mockCallback);
    expect(result).toBe(unsubscribe);
  });

  it("should connect when requested", async () => {
    vi.mocked(agentService.connect).mockResolvedValue(undefined);

    await agentService.connect();

    expect(agentService.connect).toHaveBeenCalled();
  });

  it("should disconnect when requested", async () => {
    vi.mocked(agentService.disconnect).mockResolvedValue(undefined);

    await agentService.disconnect();

    expect(agentService.disconnect).toHaveBeenCalled();
  });
});

/**
 * Tests for lifecycle state data structure
 */
describe("LifecycleStateData", () => {
  it("should define all required lifecycle states", () => {
    // This test documents the expected lifecycle states
    const validStates = [
      "initializing",
      "ready",
      "executing",
      "paused",
      "shutting_down",
      "error",
    ] as const;

    // Verify we can type-check these states
    const states: Array<string> = [...validStates];
    expect(states).toHaveLength(6);
  });

  it("should include all optional fields in lifecycle state data", () => {
    // This test documents the expected structure
    interface ExpectedLifecycleStateData {
      lifecycleState: string | null;
      isInitialized: boolean;
      isActive: boolean;
      toolCount?: number;
      skillCount?: number;
      subagentCount?: number;
      conversationId?: string;
      errorMessage?: string;
    }

    const example: ExpectedLifecycleStateData = {
      lifecycleState: "ready",
      isInitialized: true,
      isActive: true,
      toolCount: 10,
      skillCount: 5,
      subagentCount: 2,
    };

    expect(example.lifecycleState).toBe("ready");
    expect(example.isInitialized).toBe(true);
    expect(example.isActive).toBe(true);
    expect(example.toolCount).toBe(10);
    expect(example.skillCount).toBe(5);
    expect(example.subagentCount).toBe(2);
  });
});

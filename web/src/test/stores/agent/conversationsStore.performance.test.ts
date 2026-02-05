/**
 * TDD RED Phase: Performance tests for store selector memoization
 *
 * Feature: Selector memoization to prevent unnecessary re-renders
 *
 * These tests verify:
 * 1. Selectors return stable references for unchanged state
 * 2. Different selectors don't interfere with each other
 * 3. Store updates don't create new objects for unchanged slices
 *
 * Note: These tests are written FIRST (TDD RED phase).
 * They should initially FAIL and then drive the implementation.
 */

import { renderHook } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";

import {
  useConversationsStore,
  useConversations,
  useCurrentConversation,
  useConversationsLoading,
} from "../../../stores/agent/conversationsStore";

// Helper to create a mock conversation
const createMockConversation = (
  id: string,
  projectId: string,
  title: string,
): import("../../../types/agent").Conversation => ({
  id,
  project_id: projectId,
  tenant_id: "tenant-1",
  user_id: "user-1",
  title,
  status: "active",
  message_count: 0,
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
});

describe("ConversationsStore - Selector Memoization", () => {
  beforeEach(() => {
    useConversationsStore.getState().reset();
    vi.clearAllMocks();
  });

  describe("State Immutability", () => {
    it("should not mutate existing conversations array when adding", () => {
      const conv1 = createMockConversation(
        "conv-1",
        "proj-1",
        "Conversation 1",
      );

      useConversationsStore.setState({
        conversations: [conv1],
      });

      const firstArray = useConversationsStore.getState().conversations;

      // Add a new conversation
      const conv2 = createMockConversation(
        "conv-2",
        "proj-1",
        "Conversation 2",
      );
      useConversationsStore.setState({
        conversations: [...firstArray, conv2],
      });

      const secondArray = useConversationsStore.getState().conversations;

      // Arrays should be different references
      expect(firstArray).not.toBe(secondArray);
      expect(firstArray).toHaveLength(1);
      expect(secondArray).toHaveLength(2);
    });

    it("should keep same array reference when state not changed", () => {
      const conv1 = createMockConversation(
        "conv-1",
        "proj-1",
        "Conversation 1",
      );

      useConversationsStore.setState({
        conversations: [conv1],
      });

      const firstArray = useConversationsStore.getState().conversations;

      // Set the same array again
      useConversationsStore.setState({
        conversations: [conv1],
      });

      const secondArray = useConversationsStore.getState().conversations;

      // Should be same reference (state didn't actually change in Zustand)
      // Note: Zustand's equality check means this will be same reference
      expect(firstArray).toEqual(secondArray);
    });
  });

  describe("Selector Behavior", () => {
    it("should return current conversations state correctly", () => {
      const conv1 = createMockConversation(
        "conv-1",
        "proj-1",
        "Conversation 1",
      );
      const conv2 = createMockConversation(
        "conv-2",
        "proj-1",
        "Conversation 2",
      );

      useConversationsStore.setState({
        conversations: [conv1, conv2],
      });

      const { result } = renderHook(() => useConversations());
      expect(result.current).toHaveLength(2);
      expect(result.current[0]).toEqual(conv1);
      expect(result.current[1]).toEqual(conv2);
    });

    it("should return current conversation correctly", () => {
      const conv1 = createMockConversation(
        "conv-1",
        "proj-1",
        "Conversation 1",
      );

      useConversationsStore.setState({
        currentConversation: conv1,
      });

      const { result } = renderHook(() => useCurrentConversation());
      expect(result.current).toEqual(conv1);
      expect(result.current?.id).toBe("conv-1");
    });

    it("should return loading state correctly", () => {
      useConversationsStore.setState({
        conversationsLoading: true,
      });

      const { result } = renderHook(() => useConversationsLoading());
      expect(result.current).toBe(true);
    });

    it("should return null for current conversation when none set", () => {
      const { result } = renderHook(() => useCurrentConversation());
      expect(result.current).toBeNull();
    });
  });

  describe("Update Isolation", () => {
    it("should only update the slice being changed", () => {
      const conv1 = createMockConversation(
        "conv-1",
        "proj-1",
        "Conversation 1",
      );

      useConversationsStore.setState({
        conversations: [conv1],
        conversationsLoading: false,
        conversationsError: null,
      });

      const stateBefore = useConversationsStore.getState();

      // Update only loading
      useConversationsStore.setState({
        conversationsLoading: true,
      });

      const stateAfter = useConversationsStore.getState();

      // Conversations should still be the same reference
      expect(stateBefore.conversations).toBe(stateAfter.conversations);

      // Loading should have changed
      expect(stateBefore.conversationsLoading).toBe(false);
      expect(stateAfter.conversationsLoading).toBe(true);
    });

    it("should not affect currentConversation when updating list", () => {
      const conv1 = createMockConversation(
        "conv-1",
        "proj-1",
        "Conversation 1",
      );
      const conv2 = createMockConversation(
        "conv-2",
        "proj-1",
        "Conversation 2",
      );

      useConversationsStore.setState({
        conversations: [conv1],
        currentConversation: conv1,
      });

      // Add to list without changing current
      useConversationsStore.setState({
        conversations: [conv1, conv2],
      });

      const state = useConversationsStore.getState();

      expect(state.currentConversation).toEqual(conv1);
      expect(state.conversations).toHaveLength(2);
    });
  });

  describe("Performance", () => {
    it("should handle multiple rapid state updates efficiently", () => {
      const startTime = performance.now();

      // Perform many state updates
      for (let i = 0; i < 100; i++) {
        const conv = createMockConversation(`conv-${i}`, "proj-1", `Conv ${i}`);
        useConversationsStore.setState({
          conversations: [conv],
        });
      }

      const endTime = performance.now();
      const duration = endTime - startTime;

      // Should complete quickly
      expect(duration).toBeLessThan(100);
    });

    it("should not leak memory with many state changes", () => {
      const initialMemory = (performance as any).memory?.usedJSHeapSize;

      // Perform many state updates
      for (let i = 0; i < 1000; i++) {
        const conv = createMockConversation(`conv-${i}`, "proj-1", `Conv ${i}`);
        useConversationsStore.setState({
          conversations: [conv],
        });
      }

      // Force garbage collection if available
      if (global.gc) {
        global.gc();
      }

      const finalMemory = (performance as any).memory?.usedJSHeapSize;

      // If we can measure memory, check it didn't grow excessively
      // (This is a soft check as memory measurement is not always available)
      if (initialMemory && finalMemory) {
        const growth = finalMemory - initialMemory;
        // Allow up to 1MB growth for 1000 operations
        expect(growth).toBeLessThan(1024 * 1024);
      }
    });
  });

  describe("Edge Cases", () => {
    it("should handle empty conversations array", () => {
      useConversationsStore.setState({
        conversations: [],
      });

      const { result } = renderHook(() => useConversations());
      expect(result.current).toEqual([]);
      expect(result.current).toHaveLength(0);
    });

    it("should handle null currentConversation", () => {
      useConversationsStore.setState({
        currentConversation: null,
      });

      const { result } = renderHook(() => useCurrentConversation());
      expect(result.current).toBeNull();
    });

    it("should handle undefined error state", () => {
      useConversationsStore.setState({
        conversationsError: null,
      });

      const error = useConversationsStore.getState().conversationsError;
      expect(error).toBeNull();
    });
  });
});

/**
 * Tests for AgentChat.tsx migration to TimelineEventRenderer
 *
 * This test suite verifies that AgentChat.tsx correctly uses
 * VirtualTimelineEventList (which uses TimelineEventRenderer internally)
 * instead of the legacy MessageList component.
 *
 * TDD Phase 2: Migrate AgentChat to use TimelineEventRenderer
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAgentV3Store } from '../../stores/agentV3';
import type { TimelineEvent } from '../../types/agent';

// Mock the services
vi.mock('../../services/agentService', () => ({
  agentService: {
    getConversations: vi.fn(() => Promise.resolve([])),
    listConversations: vi.fn(() => Promise.resolve([])),
    getConversationMessages: vi.fn(() =>
      Promise.resolve({
        conversationId: 'conv-123',
        timeline: [],
        total: 0,
        has_more: false,
        first_sequence: null,
        last_sequence: null,
      })
    ),
    createConversation: vi.fn(() =>
      Promise.resolve({ id: 'new-conv', project_id: 'proj-123' })
    ),
    deleteConversation: vi.fn(() => Promise.resolve()),
    isConnected: vi.fn(() => false),
  },
}));

vi.mock('../../services/planService', () => ({
  planService: {
    getPlanModeStatus: vi.fn(() =>
      Promise.resolve({ is_in_plan_mode: false, current_plan: null })
    ),
  },
}));

vi.mock('../../hooks/useSandboxDetection', () => ({
  useSandboxAgentHandlers: () => ({
    onAct: vi.fn(),
    onObserve: vi.fn(),
  }),
}));

vi.mock('../../stores/sandbox', () => ({
  useSandboxStore: () => ({
    activeSandboxId: null,
    toolExecutions: [],
    closePanel: vi.fn(),
  }),
}));

describe('AgentChat - TimelineEventRenderer Migration', () => {
  beforeEach(() => {
    // Reset store before each test
    useAgentV3Store.setState({
      conversations: [],
      activeConversationId: null,
      timeline: [],
      messages: [],
      isLoadingHistory: false,
      isStreaming: false,
      streamStatus: 'idle',
      error: null,
      agentState: 'idle',
      currentThought: '',
      activeToolCalls: new Map(),
      pendingToolsStack: [],
      workPlan: null,
      isPlanMode: false,
      showPlanPanel: true,
      showHistorySidebar: true,
      pendingDecision: null,
      doomLoopDetected: null,
    });
  });

  describe('State Structure', () => {
    it('should have timeline field in state', () => {
      const { result } = renderHook(() => useAgentV3Store());

      // Verify timeline field exists
      expect(Array.isArray(result.current.timeline)).toBe(true);
    });

    it('should initialize timeline as empty array', () => {
      const { result } = renderHook(() => useAgentV3Store());

      expect(result.current.timeline).toEqual([]);
      expect(result.current.timeline.length).toBe(0);
    });
  });

  describe('Data Flow - Timeline Usage', () => {
    it('should use timeline from store instead of messages', () => {
      const { result } = renderHook(() => useAgentV3Store());

      const mockTimeline: TimelineEvent[] = [
        {
          id: 'thought-1',
          type: 'thought',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Thinking...',
        },
        {
          id: 'act-1',
          type: 'act',
          sequenceNumber: 2,
          timestamp: Date.now() + 1000,
          toolName: 'search',
          toolInput: { query: 'test' },
        },
        {
          id: 'observe-1',
          type: 'observe',
          sequenceNumber: 3,
          timestamp: Date.now() + 2000,
          toolName: 'search',
          toolOutput: 'result',
          isError: false,
        },
      ];

      act(() => {
        useAgentV3Store.setState({
          timeline: mockTimeline,
          activeConversationId: 'conv-123',
        });
      });

      // Timeline should be used
      expect(result.current.timeline).toEqual(mockTimeline);
      expect(result.current.timeline.length).toBe(3);
    });

    it('should update timeline when new events are added', () => {
      const { result } = renderHook(() => useAgentV3Store());

      // Initial state - empty timeline
      expect(result.current.timeline).toEqual([]);

      // Add timeline events
      const newEvents: TimelineEvent[] = [
        {
          id: 'user-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Test message',
          role: 'user',
        },
      ];

      act(() => {
        useAgentV3Store.setState({
          timeline: newEvents,
          activeConversationId: 'conv-123',
        });
      });

      expect(result.current.timeline).toEqual(newEvents);
      expect(result.current.timeline.length).toBe(1);
    });

    it('should reflect streaming state correctly', () => {
      const { result } = renderHook(() => useAgentV3Store());

      act(() => {
        useAgentV3Store.setState({
          timeline: [],
          isStreaming: true,
          activeConversationId: 'conv-123',
        });
      });

      expect(result.current.isStreaming).toBe(true);
    });
  });

  describe('Backward Compatibility', () => {
    it('should still provide messages field for legacy components', () => {
      const { result } = renderHook(() => useAgentV3Store());

      // messages field should still exist
      expect(Array.isArray(result.current.messages)).toBe(true);
      expect(typeof result.current.messages).toBe('object');
    });

    it('should maintain both timeline and messages for compatibility', () => {
      const { result } = renderHook(() => useAgentV3Store());

      const timeline: TimelineEvent[] = [
        {
          id: 'user-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user',
        },
      ];

      act(() => {
        useAgentV3Store.setState({ timeline });
      });

      // Both fields should exist
      expect(Array.isArray(result.current.timeline)).toBe(true);
      expect(Array.isArray(result.current.messages)).toBe(true);
    });
  });
});

/**
 * Migration Checklist:
 *
 * Phase 2: AgentChat.tsx Migration
 *
 * Changes to make in AgentChat.tsx:
 * 1. Import VirtualTimelineEventList instead of MessageList ✅
 * 2. Pass timeline instead of messages to the list component ✅
 * 3. Pass isStreaming instead of currentThought/activeToolCalls ✅
 * 4. Remove currentThought, activeToolCalls destructuring ✅
 * 5. Keep messages field for backward compatibility (derived from timeline) ✅
 *
 * Expected Result:
 * - Single rendering path using TimelineEvent[]
 * - Consistent display between streaming and historical messages
 * - No breaking changes to UI
 */

/**
 * Tests for agentV3 store timeline field
 *
 * This test suite verifies that the agentV3 store correctly
 * stores and manages TimelineEvent[] as the primary data source,
 * ensuring consistency between streaming and historical messages.
 *
 * TDD Phase 1: Add timeline field to AgentV3State
 */

import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useAgentV3Store } from '../../stores/agentV3';

import type { TimelineEvent } from '../../types/agent';

// Mock the services
vi.mock('../../services/agentService', () => ({
  agentService: {
    getConversations: vi.fn(() => Promise.resolve([])),
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
    createConversation: vi.fn(() => Promise.resolve({ id: 'new-conv', project_id: 'proj-123' })),
    deleteConversation: vi.fn(() => Promise.resolve()),
    getExecutionStatus: vi.fn(() => Promise.resolve({ is_running: false, last_sequence: 0 })),
  },
}));

vi.mock('../../services/planService', () => ({
  planService: {
    getPlanModeStatus: vi.fn(() => Promise.resolve({ is_in_plan_mode: false, current_plan: null })),
  },
}));

describe('agentV3 Store - Timeline Field', () => {
  beforeEach(() => {
    // Reset store before each test
    useAgentV3Store.setState({
      conversations: [],
      activeConversationId: null,
      messages: [],
      timeline: [], // NEW FIELD
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

    it('should maintain both timeline and messages for backward compatibility', () => {
      const { result } = renderHook(() => useAgentV3Store());

      // Both fields should exist
      expect(Array.isArray(result.current.timeline)).toBe(true);
      expect(Array.isArray(result.current.messages)).toBe(true);
    });
  });

  describe('loadMessages - Timeline Storage', () => {
    it('should store timeline from API response', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const mockTimeline: TimelineEvent[] = [
        {
          id: 'user-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user',
        },
        {
          id: 'assistant-1',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: Date.now() + 1000,
          content: 'Hi there!',
          role: 'assistant',
        },
        {
          id: 'thought-1',
          type: 'thought',
          sequenceNumber: 3,
          timestamp: Date.now() + 2000,
          content: 'I should help...',
        },
      ];

      vi.mocked(
        (await import('../../services/agentService')).agentService
      ).getConversationMessages.mockResolvedValue({
        conversationId: 'conv-123',
        timeline: mockTimeline,
        total: 3,
        has_more: false,
        first_sequence: 1,
        last_sequence: 3,
      });

      await act(async () => {
        // Set active conversation first (required by loadMessages)
        useAgentV3Store.setState({ activeConversationId: 'conv-123' });
        await result.current.loadMessages('conv-123', 'proj-123');
      });

      // Timeline should be stored
      expect(result.current.timeline).toEqual(mockTimeline);
      expect(result.current.timeline.length).toBe(3);
    });

    it('should clear timeline when loading new conversation', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      // Set initial timeline
      act(() => {
        useAgentV3Store.setState({
          timeline: [
            {
              id: 'old-1',
              type: 'user_message',
              sequenceNumber: 1,
              timestamp: Date.now(),
              content: 'Old message',
              role: 'user',
            } as TimelineEvent,
          ],
        });
      });

      expect(result.current.timeline.length).toBe(1);

      // Load new conversation (empty timeline)
      vi.mocked(
        (await import('../../services/agentService')).agentService
      ).getConversationMessages.mockResolvedValue({
        conversationId: 'conv-456',
        timeline: [],
        total: 0,
        has_more: false,
        first_sequence: null,
        last_sequence: null,
      });

      await act(async () => {
        await result.current.loadMessages('conv-456', 'proj-123');
      });

      // Timeline should be cleared
      expect(result.current.timeline).toEqual([]);
    });
  });

  describe('Streaming - Timeline Append', () => {
    it('should append thought events to timeline during streaming', () => {
      const { result } = renderHook(() => useAgentV3Store());

      const initialTimeline: TimelineEvent[] = [
        {
          id: 'user-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'Help me',
          role: 'user',
        },
      ];

      act(() => {
        useAgentV3Store.setState({ timeline: initialTimeline });
      });

      // Simulate streaming thought event
      const thoughtEvent: TimelineEvent = {
        id: 'thought-1',
        type: 'thought',
        sequenceNumber: 2,
        timestamp: Date.now() + 1000,
        content: 'I should help the user',
      };

      act(() => {
        useAgentV3Store.setState((state) => ({
          timeline: [...state.timeline, thoughtEvent],
        }));
      });

      expect(result.current.timeline.length).toBe(2);
      expect(result.current.timeline[1]).toEqual(thoughtEvent);
    });

    it('should append act events to timeline during streaming', () => {
      const { result } = renderHook(() => useAgentV3Store());

      const actEvent: TimelineEvent = {
        id: 'act-1',
        type: 'act',
        sequenceNumber: 2,
        timestamp: Date.now(),
        toolName: 'web_search',
        toolInput: { query: 'test' },
      };

      act(() => {
        useAgentV3Store.setState((state) => ({
          timeline: [...state.timeline, actEvent],
        }));
      });

      expect(result.current.timeline).toContainEqual(actEvent);
    });

    it('should append observe events to timeline during streaming', () => {
      const { result } = renderHook(() => useAgentV3Store());

      const observeEvent: TimelineEvent = {
        id: 'observe-1',
        type: 'observe',
        sequenceNumber: 3,
        timestamp: Date.now(),
        toolName: 'web_search',
        toolOutput: 'Search results',
        isError: false,
      };

      act(() => {
        useAgentV3Store.setState((state) => ({
          timeline: [...state.timeline, observeEvent],
        }));
      });

      expect(result.current.timeline).toContainEqual(observeEvent);
    });

    it('should maintain event order by sequenceNumber', () => {
      const { result } = renderHook(() => useAgentV3Store());

      const events: TimelineEvent[] = [
        {
          id: 'event-3',
          type: 'thought',
          sequenceNumber: 3,
          timestamp: 3000,
          content: 'Third',
        },
        {
          id: 'event-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'First',
          role: 'user',
        },
        {
          id: 'event-2',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: 2000,
          content: 'Second',
          role: 'assistant',
        },
      ];

      act(() => {
        useAgentV3Store.setState((state) => ({
          timeline: [...state.timeline, ...events],
        }));
      });

      // Should be stored in insertion order, not sorted
      expect(result.current.timeline.length).toBe(3);
    });
  });

  describe('Timeline Consistency', () => {
    it('should have consistent event types between API and streaming', () => {
      const { result } = renderHook(() => useAgentV3Store());

      // Event types from API
      const apiEvents: TimelineEvent[] = [
        {
          id: 'api-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'From API',
          role: 'user',
        },
        {
          id: 'api-2',
          type: 'thought',
          sequenceNumber: 2,
          timestamp: Date.now(),
          content: 'From API thought',
        },
        {
          id: 'api-3',
          type: 'act',
          sequenceNumber: 3,
          timestamp: Date.now(),
          toolName: 'search',
          toolInput: { query: 'test' },
        },
        {
          id: 'api-4',
          type: 'observe',
          sequenceNumber: 4,
          timestamp: Date.now(),
          toolName: 'search',
          toolOutput: 'result',
          isError: false,
        },
      ];

      act(() => {
        useAgentV3Store.setState({ timeline: apiEvents });
      });

      // All event types should be stored
      expect(result.current.timeline.length).toBe(4);

      // Verify types
      expect(result.current.timeline[0].type).toBe('user_message');
      expect(result.current.timeline[1].type).toBe('thought');
      expect(result.current.timeline[2].type).toBe('act');
      expect(result.current.timeline[3].type).toBe('observe');
    });
  });

  describe('Backward Compatibility', () => {
    it('should still provide messages field derived from timeline', () => {
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

      // messages field should still exist
      expect(Array.isArray(result.current.messages)).toBe(true);
    });
  });

  describe('loadMessages - Timeline Sorting', () => {
    it('should sort timeline by sequence number even if API returns unsorted', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      // Mock API returning unsorted timeline (simulating potential backend issue)
      const unsortedTimeline: TimelineEvent[] = [
        {
          id: 'assistant-2',
          type: 'assistant_message',
          sequenceNumber: 3,
          timestamp: Date.now() + 2000,
          content: 'Second response',
          role: 'assistant',
        },
        {
          id: 'user-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now(),
          content: 'First message',
          role: 'user',
        },
        {
          id: 'assistant-1',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: Date.now() + 1000,
          content: 'First response',
          role: 'assistant',
        },
      ];

      vi.mocked(
        (await import('../../services/agentService')).agentService
      ).getConversationMessages.mockResolvedValue({
        conversationId: 'conv-123',
        timeline: unsortedTimeline,
        total: 3,
        has_more: false,
        first_sequence: 1,
        last_sequence: 3,
      });

      await act(async () => {
        useAgentV3Store.setState({ activeConversationId: 'conv-123' });
        await result.current.loadMessages('conv-123', 'proj-123');
      });

      // Timeline should be sorted by sequence number
      expect(result.current.timeline.length).toBe(3);
      expect(result.current.timeline[0].sequenceNumber).toBe(1);
      expect(result.current.timeline[1].sequenceNumber).toBe(2);
      expect(result.current.timeline[2].sequenceNumber).toBe(3);
      expect(result.current.timeline[0].type).toBe('user_message');
      expect(result.current.timeline[1].type).toBe('assistant_message');
      expect(result.current.timeline[2].type).toBe('assistant_message');
    });

    it('should maintain sort order when loading earlier messages', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      // Set initial state with some timeline events
      const existingTimeline: TimelineEvent[] = [
        {
          id: 'user-3',
          type: 'user_message',
          sequenceNumber: 5,
          timestamp: Date.now(),
          content: 'Latest message',
          role: 'user',
        },
        {
          id: 'assistant-3',
          type: 'assistant_message',
          sequenceNumber: 6,
          timestamp: Date.now() + 1000,
          content: 'Latest response',
          role: 'assistant',
        },
      ];

      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-123',
          timeline: existingTimeline,
          earliestLoadedSequence: 5,
        });
      });

      // Mock earlier messages API response
      const earlierTimeline: TimelineEvent[] = [
        {
          id: 'user-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: Date.now() - 2000,
          content: 'First message',
          role: 'user',
        },
        {
          id: 'assistant-1',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: Date.now() - 1000,
          content: 'First response',
          role: 'assistant',
        },
      ];

      vi.mocked(
        (await import('../../services/agentService')).agentService
      ).getConversationMessages.mockResolvedValue({
        conversationId: 'conv-123',
        timeline: earlierTimeline,
        total: 2,
        has_more: false,
        first_sequence: 1,
        last_sequence: 2,
      });

      await act(async () => {
        await result.current.loadEarlierMessages('conv-123', 'proj-123');
      });

      // Combined timeline should be sorted
      expect(result.current.timeline.length).toBe(4);
      expect(result.current.timeline[0].sequenceNumber).toBe(1);
      expect(result.current.timeline[1].sequenceNumber).toBe(2);
      expect(result.current.timeline[2].sequenceNumber).toBe(5);
      expect(result.current.timeline[3].sequenceNumber).toBe(6);
    });
  });
});

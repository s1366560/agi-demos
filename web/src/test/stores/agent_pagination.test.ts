const ownerFixture = vi.hoisted(() => {
  const owner = {};
  return {
    availability: { owner, available: true },
    operation: { owner, signal: new AbortController().signal, check: () => {} },
  };
});
vi.mock('@/plugins/webOperationAdmissionV2', () => ({
  getWebOperationAvailabilityV2: () => ownerFixture.availability,
}));
/**
 * Unit tests for Agent store pagination functionality (agentV3).
 *
 * Tests verify time-based backward pagination support:
 * 1. loadMessages sets pagination metadata (earliestTimeUs, hasEarlier)
 * 2. loadEarlierMessages fetches older messages before earliestTimeUs
 * 3. Guard conditions prevent redundant loads
 * 4. setActiveConversation resets pagination state
 */

import { act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

import { useAgentV3Store as useAgentStore } from '../../stores/agentV3';
import { useTimelineStore } from '../../stores/agent/timelineStore';
import { useStreamingStore } from '../../stores/agent/streamingStore';
import { useExecutionStore } from '../../stores/agent/executionStore';
import { createDefaultConversationState } from '../../types/conversationState';

import type { TimelineEvent } from '../../types/agent';

// Mock agent service
const mockGetConversationMessages = vi.fn();
vi.mock('../../services/agentService', () => ({
  agentService: {
    connectSession: vi.fn(async () => ownerFixture.operation),
    assertSession: vi.fn(),
    getConversationMessages: (...args: unknown[]) => mockGetConversationMessages(...args),
    chat: vi.fn(),
    createConversation: vi.fn(),
    listConversations: vi.fn(() => Promise.resolve({ items: [], has_more: false, total: 0 })),
    getExecutionStatus: vi.fn().mockResolvedValue({ is_running: false, last_sequence: 0 }),
    connect: vi.fn(() => Promise.resolve()),
    isConnected: vi.fn(() => true),
    subscribe: vi.fn(),
  },
}));

// Mock dynamic imports used by loadMessages
vi.mock('../../stores/contextStore', () => ({
  useContextStore: {
    getState: () => ({
      fetchContextStatus: vi.fn().mockResolvedValue(null),
      reset: vi.fn(),
    }),
  },
}));

vi.mock('../../services/planService', () => ({
  planService: {
    getMode: vi.fn().mockResolvedValue({ mode: 'act' }),
  },
}));

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn().mockResolvedValue({ tasks: [] }),
  },
}));

vi.mock('../../utils/conversationDB', () => ({
  saveConversationState: vi.fn(() => Promise.resolve()),
  loadConversationState: vi.fn(() => Promise.resolve(null)),
  deleteConversationState: vi.fn(() => Promise.resolve()),
}));

describe('Agent Store Pagination (agentV3)', () => {
  beforeEach(() => {
    // Reset store to initial state
    useAgentStore.setState({
      conversations: [],
      activeConversationId: null,
      conversationStates: new Map(),
    });
    useTimelineStore.getState().resetAgentTimeline();
    useStreamingStore.getState().resetAgentStreaming();
    useExecutionStore.getState().resetAgentExecution();
    vi.clearAllMocks();
  });

  describe('loadMessages - initial load', () => {
    it('should set time-based pagination metadata on initial load', async () => {
      // Arrange
      const mockTimeline: TimelineEvent[] = [
        {
          id: '1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'Hello',
          role: 'user',
          eventTimeUs: 1000000,
          eventCounter: 1,
        } as TimelineEvent,
        {
          id: '2',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: 2000,
          content: 'Hi',
          role: 'assistant',
          eventTimeUs: 2000000,
          eventCounter: 2,
        } as TimelineEvent,
        {
          id: '3',
          type: 'user_message',
          sequenceNumber: 3,
          timestamp: 3000,
          content: 'How are you?',
          role: 'user',
          eventTimeUs: 3000000,
          eventCounter: 3,
        } as TimelineEvent,
      ];
      const mockResponse = {
        conversationId: 'conv-1',
        timeline: mockTimeline,
        total: 3,
        has_more: true,
        first_time_us: 1000000,
        first_counter: 1,
        last_time_us: 3000000,
        last_counter: 3,
      };
      mockGetConversationMessages.mockResolvedValue(mockResponse);

      // Set active conversation so loadMessages proceeds
      useAgentStore.setState({ activeConversationId: 'conv-1' });

      // Act
      await act(async () => {
        await useAgentStore.getState().loadMessages('conv-1', 'project-1');
      });

      // Assert
      const tls = useTimelineStore.getState();
      expect(tls.agentTimeline.length).toBeGreaterThanOrEqual(3);
      expect(tls.agentHasEarlier).toBe(true);
      expect(tls.agentEarliestTimeUs).toBe(1000000);
      expect(tls.agentEarliestCounter).toBe(1);
      expect(tls.agentIsLoadingHistory).toBe(false);
    });

    it('should handle empty timeline response', async () => {
      // Arrange
      const mockResponse = {
        conversationId: 'conv-1',
        timeline: [],
        total: 0,
        has_more: false,
        first_time_us: null,
        first_counter: null,
        last_time_us: null,
        last_counter: null,
      };
      mockGetConversationMessages.mockResolvedValue(mockResponse);

      useAgentStore.setState({ activeConversationId: 'conv-1' });

      // Act
      await act(async () => {
        await useAgentStore.getState().loadMessages('conv-1', 'project-1');
      });

      // Assert
      const tls = useTimelineStore.getState();
      expect(tls.agentTimeline).toEqual([]);
      expect(tls.agentEarliestTimeUs).toBeNull();
      expect(tls.agentEarliestCounter).toBeNull();
      expect(tls.agentHasEarlier).toBe(false);
    });
  });

  describe('loadEarlierMessages - backward pagination', () => {
    it('should load messages before earliestTimeUs', async () => {
      // Arrange - Set initial state with time-based pagination
      const existingTimeline: TimelineEvent[] = Array.from(
        { length: 10 },
        (_, i): TimelineEvent =>
          ({
            id: `msg-${i + 11}`,
            type: 'user_message',
            sequenceNumber: i + 11,
            timestamp: (i + 11) * 1000,
            content: `Message ${i + 11}`,
            role: 'user',
            eventTimeUs: (i + 11) * 1000000,
            eventCounter: i + 11,
          }) as TimelineEvent
      );

      useAgentStore.setState({
        activeConversationId: 'conv-1',
      });
      const tls = useTimelineStore.getState();
      tls.setAgentEarliestPointers(11000000, 11);
      tls.setAgentTimeline(existingTimeline);
      tls.setAgentHasEarlier(true);
      tls.setAgentIsLoadingEarlier(false);

      const mockEarlierTimeline: TimelineEvent[] = [
        {
          id: 'msg-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'Msg 1',
          role: 'user',
          eventTimeUs: 1000000,
          eventCounter: 1,
        } as TimelineEvent,
        {
          id: 'msg-2',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: 2000,
          content: 'Msg 2',
          role: 'assistant',
          eventTimeUs: 2000000,
          eventCounter: 2,
        } as TimelineEvent,
        {
          id: 'msg-3',
          type: 'user_message',
          sequenceNumber: 3,
          timestamp: 3000,
          content: 'Msg 3',
          role: 'user',
          eventTimeUs: 3000000,
          eventCounter: 3,
        } as TimelineEvent,
      ];
      const mockEarlierResponse = {
        conversationId: 'conv-1',
        timeline: mockEarlierTimeline,
        total: 3,
        has_more: false,
        first_time_us: 1000000,
        first_counter: 1,
        last_time_us: 3000000,
        last_counter: 3,
      };
      mockGetConversationMessages.mockResolvedValue(mockEarlierResponse);

      // Act
      let result: boolean | undefined;
      await act(async () => {
        result = await useAgentStore.getState().loadEarlierMessages('conv-1', 'project-1');
      });

      // Assert
      const tls2 = useTimelineStore.getState();
      expect(result).toBe(true);
      expect(tls2.agentTimeline.length).toBe(13); // 10 existing + 3 new
      expect(tls2.agentHasEarlier).toBe(false);
      expect(tls2.agentEarliestTimeUs).toBe(1000000);
      expect(tls2.agentEarliestCounter).toBe(1);
      expect(tls2.agentIsLoadingEarlier).toBe(false);

      // Verify API was called with time-based pagination params
      expect(mockGetConversationMessages).toHaveBeenCalledWith(
        'conv-1',
        'project-1',
        200, // limit
        undefined, // fromTimeUs
        undefined, // fromCounter
        11000000, // beforeTimeUs
        11 // beforeCounter
      );
    });

    it('should not load when no earliestTimeUs exists', async () => {
      // Arrange
      useAgentStore.setState({
        activeConversationId: 'conv-1',
      });
      useTimelineStore.getState().setAgentEarliestPointers(null, null);
      useTimelineStore.getState().setAgentHasEarlier(true);
      useTimelineStore.getState().setAgentIsLoadingEarlier(false);

      // Act
      let result: boolean | undefined;
      await act(async () => {
        result = await useAgentStore.getState().loadEarlierMessages('conv-1', 'project-1');
      });

      // Assert
      expect(result).toBe(false);
      expect(mockGetConversationMessages).not.toHaveBeenCalled();
    });

    it('should not load when already loading', async () => {
      // Arrange
      useAgentStore.setState({
        activeConversationId: 'conv-1',
      });
      useTimelineStore.getState().setAgentEarliestPointers(11000000, 11);
      useTimelineStore.getState().setAgentHasEarlier(true);
      useTimelineStore.getState().setAgentIsLoadingEarlier(true); // Already loading

      // Act
      let result: boolean | undefined;
      await act(async () => {
        result = await useAgentStore.getState().loadEarlierMessages('conv-1', 'project-1');
      });

      // Assert
      expect(result).toBe(false);
      expect(mockGetConversationMessages).not.toHaveBeenCalled();
    });

    it('should not load when conversationId does not match active', async () => {
      // Arrange
      useAgentStore.setState({
        activeConversationId: 'conv-other',
      });
      useTimelineStore.getState().setAgentEarliestPointers(11000000, 11);
      useTimelineStore.getState().setAgentHasEarlier(true);
      useTimelineStore.getState().setAgentIsLoadingEarlier(false);

      // Act
      let result: boolean | undefined;
      await act(async () => {
        result = await useAgentStore.getState().loadEarlierMessages('conv-1', 'project-1');
      });

      // Assert
      expect(result).toBe(false);
      expect(mockGetConversationMessages).not.toHaveBeenCalled();
    });

    it('should handle API error gracefully', async () => {
      // Arrange
      useAgentStore.setState({
        activeConversationId: 'conv-1',
      });
      useTimelineStore.getState().setAgentEarliestPointers(11000000, 11);
      useTimelineStore.getState().setAgentHasEarlier(true);
      useTimelineStore.getState().setAgentIsLoadingEarlier(false);
      mockGetConversationMessages.mockRejectedValue(new Error('Network error'));

      // Act
      let result: boolean | undefined;
      await act(async () => {
        result = await useAgentStore.getState().loadEarlierMessages('conv-1', 'project-1');
      });

      // Assert
      expect(result).toBe(false);
      expect(useTimelineStore.getState().agentIsLoadingEarlier).toBe(false);
    });
  });

  describe('Timeline via setState - prepend simulation', () => {
    it('should support prepending events via direct setState', () => {
      // Arrange
      const existingTimeline: TimelineEvent[] = [
        {
          id: 'msg-10',
          type: 'user_message',
          sequenceNumber: 10,
          timestamp: 10000,
          content: 'Msg 10',
          role: 'user',
          eventTimeUs: 10000000,
          eventCounter: 10,
        } as TimelineEvent,
      ];
      useAgentStore.setState({ timeline: existingTimeline });

      const newEvents: TimelineEvent[] = [
        {
          id: 'msg-1',
          type: 'user_message',
          sequenceNumber: 1,
          timestamp: 1000,
          content: 'Msg 1',
          role: 'user',
          eventTimeUs: 1000000,
          eventCounter: 1,
        } as TimelineEvent,
        {
          id: 'msg-2',
          type: 'assistant_message',
          sequenceNumber: 2,
          timestamp: 2000,
          content: 'Msg 2',
          role: 'assistant',
          eventTimeUs: 2000000,
          eventCounter: 2,
        } as TimelineEvent,
      ];

      // Act - prepend via setState (agentV3 has no prependTimelineEvents method)
      act(() => {
        useAgentStore.setState({
          timeline: [...newEvents, ...existingTimeline],
        });
      });

      // Assert
      const state = useAgentStore.getState();
      expect(state.timeline.length).toBe(3);
      expect(state.timeline[0].id).toBe('msg-1');
      expect(state.timeline[1].id).toBe('msg-2');
      expect(state.timeline[2].id).toBe('msg-10');
    });
  });

  describe('setActiveConversation - resets pagination state', () => {
    it('should reset pagination state when switching conversations', () => {
      // Arrange - Set initial pagination state via sub-stores
      useAgentStore.setState({
        activeConversationId: 'conv-1',
        conversations: [
          {
            id: 'conv-1',
            project_id: 'project-1',
            title: 'Conv 1',
          } as any,
          {
            id: 'conv-2',
            project_id: 'project-2',
            title: 'Conv 2',
          } as any,
        ],
      });
      useTimelineStore.getState().setAgentEarliestPointers(10000000, 10);
      useTimelineStore.getState().setAgentHasEarlier(true);
      useTimelineStore.getState().setAgentTimeline([
        {
          id: 'msg-1',
          type: 'user_message',
          sequenceNumber: 10,
          timestamp: 10000,
          content: 'Msg',
          role: 'user',
          eventTimeUs: 10000000,
          eventCounter: 10,
        } as TimelineEvent,
      ]);

      // Act - switch to a different conversation
      act(() => {
        useAgentStore.getState().setActiveConversation('conv-2');
      });

      // Assert
      const state = useAgentStore.getState();
      const tls = useTimelineStore.getState();
      expect(state.activeConversationId).toBe('conv-2');
      // Pagination state should be reset for the new conversation
      // (setActiveConversation restores from conversationStates cache or defaults)
      // Since conv-2 was never loaded, these should be defaults
      expect(tls.agentHasEarlier).toBe(false);
      expect(tls.agentEarliestTimeUs).toBeNull();
      expect(tls.agentEarliestCounter).toBeNull();
    });

    it('should restore cached pagination state for previously visited conversation', () => {
      // Arrange - Set up conversation states cache with full ConversationState
      const cachedState = new Map();
      const conv2State = createDefaultConversationState();
      conv2State.hasEarlier = true;
      conv2State.earliestTimeUs = 5000000;
      conv2State.earliestCounter = 5;
      conv2State.timeline = [
        {
          id: 'cached-msg',
          type: 'user_message',
          content: 'Cached',
          eventTimeUs: 5000000,
          eventCounter: 5,
        } as TimelineEvent,
      ];
      cachedState.set('conv-2', conv2State);

      useAgentStore.setState({
        activeConversationId: 'conv-1',
        conversationStates: cachedState,
        conversations: [
          { id: 'conv-1', project_id: 'p1', title: 'C1' } as any,
          { id: 'conv-2', project_id: 'p2', title: 'C2' } as any,
        ],
      });

      // Act
      act(() => {
        useAgentStore.getState().setActiveConversation('conv-2');
      });

      // Assert
      const state = useAgentStore.getState();
      const tls = useTimelineStore.getState();
      expect(state.activeConversationId).toBe('conv-2');
      expect(tls.agentHasEarlier).toBe(true);
      expect(tls.agentEarliestTimeUs).toBe(5000000);
      expect(tls.agentEarliestCounter).toBe(5);
    });
  });
});

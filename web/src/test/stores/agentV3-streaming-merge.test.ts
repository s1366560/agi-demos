/**
 * Tests for agentV3 store - loadMessages timeline merging during streaming
 *
 * This test suite verifies that timeline updates are correctly merged
 * even when isStreaming is true, preserving local new events.
 *
 * TDD Phase: Fix timeline update skipping during streaming
 */

import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useAgentV3Store } from '../../stores/agentV3';
import { useTimelineStore } from '../../stores/agent/timelineStore';
import { useStreamingStore } from '../../stores/agent/streamingStore';
import { useExecutionStore } from '../../stores/agent/executionStore';

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
        first_time_us: null,
        first_counter: null,
        last_time_us: null,
        last_counter: null,
      })
    ),
    createConversation: vi.fn(() => Promise.resolve({ id: 'new-conv', project_id: 'proj-123' })),
    deleteConversation: vi.fn(() => Promise.resolve()),
    chat: vi.fn(),
    stopChat: vi.fn(),
    getExecutionStatus: vi.fn(() =>
      Promise.resolve({
        is_running: false,
        last_sequence: 0,
      })
    ),
    connect: vi.fn(() => Promise.resolve()),
    isConnected: vi.fn(() => true),
    subscribe: vi.fn(),
    listConversations: vi.fn(() => Promise.resolve({ items: [], has_more: false, total: 0 })),
  },
}));

vi.mock('../../stores/contextStore', () => ({
  useContextStore: {
    getState: vi.fn(() => ({
      fetchContextStatus: vi.fn(() => Promise.resolve()),
      reset: vi.fn(),
    })),
  },
}));

vi.mock('../../services/planService', () => ({
  planService: {
    getMode: vi.fn(() => Promise.resolve({ mode: 'act' })),
  },
}));

vi.mock('../../services/client/httpClient', () => ({
  httpClient: {
    get: vi.fn(() => Promise.resolve({ tasks: [] })),
  },
}));

vi.mock('../../utils/conversationDB', () => ({
  saveConversationState: vi.fn(() => Promise.resolve()),
  loadConversationState: vi.fn(() => Promise.resolve(null)),
  deleteConversationState: vi.fn(() => Promise.resolve()),
}));

function getTimeline() {
  return useTimelineStore.getState().agentTimeline;
}

describe('agentV3 Store - Timeline Merging During Streaming', () => {
  beforeEach(async () => {
    useAgentV3Store.setState({
      conversations: [],
      activeConversationId: null,
      conversationStates: new Map(),
    });

    useTimelineStore.getState().resetAgentTimeline();
    useStreamingStore.getState().resetAgentStreaming();
    useExecutionStore.getState().resetAgentExecution();

    vi.clearAllMocks();
  });

  describe('loadMessages - Timeline Merge During Streaming', () => {
    it('should merge API timeline with local events when isStreaming is true', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const localEvent: TimelineEvent = {
        id: 'local-act-1',
        type: 'act',
        eventTimeUs: Date.now() * 1000 + 100,
        eventCounter: 10,
        timestamp: Date.now(),
        toolName: 'local_tool',
        toolInput: { test: true },
      };

      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-123',
        });
        useStreamingStore.getState().setAgentIsStreaming(true);
        useStreamingStore.getState().setAgentStreamStatus('streaming');
        useTimelineStore.getState().setAgentTimeline([localEvent]);
      });

      const apiEvents: TimelineEvent[] = [
        {
          id: 'api-user-1',
          type: 'user_message',
          eventTimeUs: Date.now() * 1000 - 5000,
          eventCounter: 1,
          timestamp: Date.now() - 5000,
          content: 'Hello from API',
          role: 'user',
        },
        {
          id: 'api-assistant-1',
          type: 'assistant_message',
          eventTimeUs: Date.now() * 1000 - 4000,
          eventCounter: 2,
          timestamp: Date.now() - 4000,
          content: 'Response from API',
          role: 'assistant',
        },
      ];

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.getConversationMessages).mockResolvedValue({
        conversationId: 'conv-123',
        timeline: apiEvents,
        total: 2,
        has_more: false,
        first_time_us: apiEvents[0].eventTimeUs,
        first_counter: apiEvents[0].eventCounter,
        last_time_us: apiEvents[1].eventTimeUs,
        last_counter: apiEvents[1].eventCounter,
      } as any);

      await act(async () => {
        await result.current.loadMessages('conv-123', 'proj-123');
      });

      const timeline = getTimeline();

      expect(timeline.find((e) => e.id === 'api-user-1')).toBeDefined();
      expect(timeline.find((e) => e.id === 'api-assistant-1')).toBeDefined();
      expect(timeline.find((e) => e.id === 'local-act-1')).toBeDefined();
    });

    it('should preserve local events that are newer than API response', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const localTimestamp = Date.now() * 1000;
      const localEvent: TimelineEvent = {
        id: 'local-thought-1',
        type: 'thought',
        eventTimeUs: localTimestamp,
        eventCounter: 100,
        timestamp: Date.now(),
        content: 'Local streaming thought',
      };

      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-456',
        });
        useStreamingStore.getState().setAgentIsStreaming(true);
        useTimelineStore.getState().setAgentTimeline([localEvent]);
      });

      const apiEvents: TimelineEvent[] = [
        {
          id: 'api-old-1',
          type: 'user_message',
          eventTimeUs: localTimestamp - 10000,
          eventCounter: 50,
          timestamp: Date.now() - 10,
          content: 'Old message',
          role: 'user',
        },
      ];

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.getConversationMessages).mockResolvedValue({
        conversationId: 'conv-456',
        timeline: apiEvents,
        total: 1,
        has_more: false,
        first_time_us: apiEvents[0].eventTimeUs,
        first_counter: apiEvents[0].eventCounter,
        last_time_us: apiEvents[0].eventTimeUs,
        last_counter: apiEvents[0].eventCounter,
      } as any);

      await act(async () => {
        await result.current.loadMessages('conv-456', 'proj-123');
      });

      const timeline = getTimeline();

      expect(timeline.length).toBeGreaterThanOrEqual(2);
      expect(timeline.find((e) => e.id === 'api-old-1')).toBeDefined();
      expect(timeline.find((e) => e.id === 'local-thought-1')).toBeDefined();
    });

    it('should deduplicate events by ID when merging', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const sharedEvent: TimelineEvent = {
        id: 'shared-1',
        type: 'user_message',
        eventTimeUs: Date.now() * 1000,
        eventCounter: 1,
        timestamp: Date.now(),
        content: 'Shared message',
        role: 'user',
      };

      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-789',
        });
        useStreamingStore.getState().setAgentIsStreaming(true);
        useTimelineStore.getState().setAgentTimeline([sharedEvent]);
      });

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.getConversationMessages).mockResolvedValue({
        conversationId: 'conv-789',
        timeline: [sharedEvent],
        total: 1,
        has_more: false,
        first_time_us: sharedEvent.eventTimeUs,
        first_counter: sharedEvent.eventCounter,
        last_time_us: sharedEvent.eventTimeUs,
        last_counter: sharedEvent.eventCounter,
      } as any);

      await act(async () => {
        await result.current.loadMessages('conv-789', 'proj-123');
      });

      const timeline = getTimeline();

      const sharedCount = timeline.filter((e) => e.id === 'shared-1').length;
      expect(sharedCount).toBe(1);
    });

    it('should update timeline even when isStreaming is true if there are new server events', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-stream',
        });
        useStreamingStore.getState().setAgentIsStreaming(true);
        useTimelineStore.getState().setAgentTimeline([]);
      });

      const newApiEvents: TimelineEvent[] = [
        {
          id: 'new-api-1',
          type: 'user_message',
          eventTimeUs: Date.now() * 1000,
          eventCounter: 1,
          timestamp: Date.now(),
          content: 'New from API',
          role: 'user',
        },
      ];

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.getConversationMessages).mockResolvedValue({
        conversationId: 'conv-stream',
        timeline: newApiEvents,
        total: 1,
        has_more: false,
        first_time_us: newApiEvents[0].eventTimeUs,
        first_counter: newApiEvents[0].eventCounter,
        last_time_us: newApiEvents[0].eventTimeUs,
        last_counter: newApiEvents[0].eventCounter,
      } as any);

      await act(async () => {
        await result.current.loadMessages('conv-stream', 'proj-123');
      });

      const timeline = getTimeline();
      expect(timeline.length).toBeGreaterThan(0);
      expect(timeline.find((e) => e.id === 'new-api-1')).toBeDefined();
    });

    it('should subscribe active conversation even when execution is idle', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-123',
        });
      });

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.getExecutionStatus).mockResolvedValue({
        is_running: false,
        last_sequence: 0,
      } as any);

      await act(async () => {
        await result.current.loadMessages('conv-123', 'proj-123');
      });

      expect(agentService.subscribe).toHaveBeenCalledWith(
        'conv-123',
        expect.any(Object),
        expect.any(Object)
      );
    });

    it('should let the backend resolve the cursor for a running message subscription', async () => {
      const { result } = renderHook(() => useAgentV3Store());
      const historyEvent: TimelineEvent = {
        id: 'history-event-1',
        type: 'assistant_message',
        eventTimeUs: Date.now() * 1000 - 500,
        eventCounter: 3,
        timestamp: Date.now() - 1,
        content: 'Recovered from history',
        role: 'assistant',
      };

      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-cursor',
        });
      });

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.getConversationMessages).mockResolvedValue({
        conversationId: 'conv-cursor',
        timeline: [historyEvent],
        total: 1,
        has_more: false,
        first_time_us: historyEvent.eventTimeUs,
        first_counter: historyEvent.eventCounter,
        last_time_us: historyEvent.eventTimeUs,
        last_counter: historyEvent.eventCounter,
      } as any);
      vi.mocked(agentService.getExecutionStatus).mockResolvedValue({
        is_running: true,
        current_message_id: 'msg-running',
        last_event_time_us: historyEvent.eventTimeUs + 999,
        last_event_counter: historyEvent.eventCounter + 5,
      } as any);

      await act(async () => {
        await result.current.loadMessages('conv-cursor', 'proj-123');
      });

      expect(agentService.subscribe).toHaveBeenCalledWith(
        'conv-cursor',
        expect.any(Object),
        {
          message_id: 'msg-running',
        }
      );
    });
  });
});

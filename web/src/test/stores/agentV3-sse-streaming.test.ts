/**
 * Tests for agentV3 store SSE streaming with timeline integration
 *
 * This test suite verifies that the agentV3 store correctly
 * uses appendSSEEventToTimeline() to update the timeline state
 * during SSE streaming.
 *
 * TDD Phase: SSE Adapter Integration into agentV3 Store
 */

import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, beforeEach, vi } from 'vitest';

import { useAgentV3Store } from '../../stores/agentV3';
import { useConversationsStore } from '../../stores/agent/conversationsStore';
import { useTimelineStore } from '../../stores/agent/timelineStore';
import { useStreamingStore } from '../../stores/agent/streamingStore';
import { useExecutionStore } from '../../stores/agent/executionStore';
import { createDefaultConversationState } from '../../types/conversationState';
import { timelineToMessages } from '../../stores/agent/timelineUtils';

import type {
  AgentEvent,
  MessageEventData,
  ThoughtEventData,
  ActEventData,
  ObserveEventData,
  CompleteEventData,
} from '../../types/agent';

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
    updateConversationConfig: vi.fn(),
    deleteConversation: vi.fn(() => Promise.resolve()),
    chat: vi.fn(),
    stopChat: vi.fn(),
    getExecutionStatus: vi.fn(() =>
      Promise.resolve({
        is_running: false,
        last_sequence: 0,
      })
    ),
    listConversations: vi.fn(() => Promise.resolve({ items: [], has_more: false, total: 0 })),
  },
}));

/**
 * Helper to read timeline from the bridged sub-store.
 * agentV3 store no longer has top-level timeline/messages fields;
 * they live in conversationStates Map and are bridged to useTimelineStore.
 */
function getTimeline() {
  return useTimelineStore.getState().agentTimeline;
}

function getMessages() {
  // Derive from timeline (matches onComplete flow which uses timelineToMessages)
  const timeline = useTimelineStore.getState().agentTimeline;
  return timelineToMessages(timeline);
}

describe('agentV3 Store - SSE Timeline Integration', () => {
  beforeEach(() => {
    // Reset agentV3 store
    useAgentV3Store.setState({
      conversations: [],
      activeConversationId: null,
      conversationStates: new Map(),
    });

    // Reset sub-stores
    useTimelineStore.getState().resetAgentTimeline();
    useStreamingStore.getState().resetAgentStreaming();
    useExecutionStore.getState().resetAgentExecution();
    useConversationsStore.getState().reset();

    vi.clearAllMocks();
  });

  describe('User Message - Timeline Append', () => {
    it('should append user message event to timeline when sending message', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      // Mock createConversation to return a conversation
      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.createConversation).mockResolvedValue({
        id: 'conv-1',
        project_id: 'proj-123',
        title: 'Test',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      } as any);

      // Mock chat to resolve immediately
      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        // Simulate minimal SSE flow
        handler.onMessage?.({
          type: 'message',
          data: {
            id: 'msg-1',
            role: 'user',
            content: 'Hello',
            created_at: new Date().toISOString(),
          },
        } as AgentEvent<MessageEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Hello', 'proj-123');
      });

      expect(agentService.chat).toHaveBeenCalledWith(
        expect.objectContaining({ preferred_language: 'en-US' }),
        expect.any(Object)
      );

      // Verify timeline has user message (read from bridged sub-store)
      const timeline = getTimeline();
      expect(timeline.length).toBeGreaterThan(0);
      expect(timeline[0].type).toBe('user_message');
      if (timeline[0].type === 'user_message') {
        expect(timeline[0].content).toBe('Hello');
      }
    });

    it('should create new conversation with selected agent id', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.createConversation).mockResolvedValue({
        id: 'conv-1',
        project_id: 'proj-123',
        title: 'Test',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      } as any);
      vi.mocked(agentService.chat).mockResolvedValue();

      await act(async () => {
        await result.current.sendMessage('Hello', 'proj-123', { agentId: 'opencode-agent' });
      });

      expect(agentService.createConversation).toHaveBeenCalledWith({
        project_id: 'proj-123',
        title: 'Hello...',
        agent_config: { selected_agent_id: 'opencode-agent' },
      });
      expect(agentService.chat).toHaveBeenCalledWith(
        expect.objectContaining({ agent_id: 'opencode-agent' }),
        expect.any(Object)
      );
    });

    it('should persist selected agent id before sending to an existing conversation', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const { agentService } = await import('../../services/agentService');
      const existingConversation = {
        id: 'conv-existing',
        project_id: 'proj-123',
        tenant_id: 'tenant-1',
        user_id: 'user-1',
        title: 'Existing',
        status: 'active',
        message_count: 0,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        agent_config: { selected_agent_id: 'builtin:all-access' },
      } as const;
      const updatedConversation = {
        ...existingConversation,
        agent_config: { selected_agent_id: 'opencode-agent' },
      };

      act(() => {
        useAgentV3Store.setState({
          activeConversationId: existingConversation.id,
          conversationStates: new Map([
            [existingConversation.id, createDefaultConversationState()],
          ]),
        });
        useConversationsStore.setState({
          conversations: [existingConversation as any],
          currentConversation: existingConversation as any,
        });
      });
      vi.mocked(agentService.updateConversationConfig).mockResolvedValue(updatedConversation as any);
      vi.mocked(agentService.chat).mockResolvedValue();

      await act(async () => {
        await result.current.sendMessage('Hello', 'proj-123', { agentId: 'opencode-agent' });
      });

      expect(agentService.updateConversationConfig).toHaveBeenCalledWith(
        'conv-existing',
        'proj-123',
        { selected_agent_id: 'opencode-agent' }
      );
      expect(agentService.chat).toHaveBeenCalledWith(
        expect.objectContaining({
          conversation_id: 'conv-existing',
          agent_id: 'opencode-agent',
        }),
        expect.any(Object)
      );
      expect(useConversationsStore.getState().currentConversation?.agent_config).toEqual({
        selected_agent_id: 'opencode-agent',
      });
    });

    it('should set correct sequence number for user message', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.createConversation).mockResolvedValue({
        id: 'conv-1',
        project_id: 'proj-123',
        title: 'Test',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      } as any);

      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        handler.onMessage?.({
          type: 'message',
          data: {
            id: 'msg-1',
            role: 'user',
            content: 'Test',
            created_at: new Date().toISOString(),
          },
        } as AgentEvent<MessageEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Test', 'proj-123');
      });

      const timeline = getTimeline();
      expect(timeline[0].eventTimeUs).toBeDefined();
      expect(timeline[0].eventCounter).toBeDefined();
    });
  });

  describe('SSE Events - Timeline Append During Streaming', () => {
    it('should append thought event to timeline during streaming', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const baseTime = Date.now() * 1000;
      // Start with existing user message in conversation state + sub-store
      const convState = createDefaultConversationState();
      convState.timeline = [
        {
          id: 'user-1',
          type: 'user_message',
          eventTimeUs: baseTime,
          eventCounter: 1,
          timestamp: Date.now(),
          content: 'Help me',
          role: 'user',
        },
      ];
      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-1',
          conversationStates: new Map([['conv-1', convState]]),
        });
        useTimelineStore.getState().setAgentTimeline(convState.timeline);
      });

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        // Simulate thought event
        handler.onThought?.({
          type: 'thought',
          data: {
            thought: 'I should help the user',
            thought_level: 'task',
            step_number: 1,
          },
        } as AgentEvent<ThoughtEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Help me', 'proj-123');
      });

      const timeline = getTimeline();
      // Should have user message + thought
      expect(timeline.length).toBeGreaterThan(1);
      const thoughtEvent = timeline.find((e) => e.type === 'thought');
      expect(thoughtEvent).toBeDefined();
      if (thoughtEvent?.type === 'thought') {
        expect(thoughtEvent.content).toBe('I should help the user');
      }
    });

    it('should append act event to timeline during streaming', async () => {
      vi.useFakeTimers();
      try {
        const { result } = renderHook(() => useAgentV3Store());

        const baseTime = Date.now() * 1000;
        const convState = createDefaultConversationState();
        convState.timeline = [
          {
            id: 'user-1',
            type: 'user_message',
            eventTimeUs: baseTime,
            eventCounter: 1,
            timestamp: Date.now(),
            content: 'Search',
            role: 'user',
          },
        ];
        act(() => {
          useAgentV3Store.setState({
            activeConversationId: 'conv-1',
            conversationStates: new Map([['conv-1', convState]]),
          });
          useTimelineStore.getState().setAgentTimeline(convState.timeline);
        });

        const { agentService } = await import('../../services/agentService');
        vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
          handler.onAct?.({
            type: 'act',
            data: {
              tool_name: 'web_search',
              tool_input: { query: 'test' },
              step_number: 1,
            },
          } as AgentEvent<ActEventData>);
          return Promise.resolve();
        });

        await act(async () => {
          await result.current.sendMessage('Search', 'proj-123');
          // Advance timers to flush the timeline batch buffer (100ms interval)
          vi.advanceTimersByTime(200);
        });

        const timeline = getTimeline();
        const actEvent = timeline.find((e) => e.type === 'act');
        expect(actEvent).toBeDefined();
        if (actEvent?.type === 'act') {
          expect(actEvent.toolName).toBe('web_search');
        }
      } finally {
        vi.useRealTimers();
      }
    });

    it('should append observe event to timeline during streaming', async () => {
      vi.useFakeTimers();
      try {
        const { result } = renderHook(() => useAgentV3Store());

        const baseTime = Date.now() * 1000;
        const convState = createDefaultConversationState();
        convState.timeline = [
          {
            id: 'user-1',
            type: 'user_message',
            eventTimeUs: baseTime,
            eventCounter: 1,
            timestamp: Date.now(),
            content: 'Search',
            role: 'user',
          },
        ];
        act(() => {
          useAgentV3Store.setState({
            activeConversationId: 'conv-1',
            conversationStates: new Map([['conv-1', convState]]),
          });
          useTimelineStore.getState().setAgentTimeline(convState.timeline);
        });

        const { agentService } = await import('../../services/agentService');
        vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
          handler.onAct?.({
            type: 'act',
            data: {
              tool_name: 'web_search',
              tool_input: { query: 'test' },
              step_number: 1,
            },
          } as AgentEvent<ActEventData>);
          handler.onObserve?.({
            type: 'observe',
            data: {
              observation: 'Search completed',
            },
          } as AgentEvent<ObserveEventData>);
          return Promise.resolve();
        });

        await act(async () => {
          await result.current.sendMessage('Search', 'proj-123');
          // Advance timers to flush the timeline batch buffer (100ms interval)
          vi.advanceTimersByTime(200);
        });

        const timeline = getTimeline();
        const observeEvent = timeline.find((e) => e.type === 'observe');
        expect(observeEvent).toBeDefined();
        if (observeEvent?.type === 'observe') {
          expect(observeEvent.toolOutput).toBe('Search completed');
        }
      } finally {
        vi.useRealTimers();
      }
    });

    it('should append assistant_message event on complete', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const baseTime = Date.now() * 1000;
      const convState = createDefaultConversationState();
      convState.timeline = [
        {
          id: 'user-1',
          type: 'user_message',
          eventTimeUs: baseTime,
          eventCounter: 1,
          timestamp: Date.now(),
          content: 'Hello',
          role: 'user',
        },
      ];
      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-1',
          conversationStates: new Map([['conv-1', convState]]),
        });
        useTimelineStore.getState().setAgentTimeline(convState.timeline);
      });

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        handler.onComplete?.({
          type: 'complete',
          data: {
            content: 'Here is the answer',
            id: 'msg-complete',
            trace_url: 'https://trace.com',
            artifacts: [],
          },
        } as AgentEvent<CompleteEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Hello', 'proj-123');
      });

      const timeline = getTimeline();
      const assistantMsg = timeline.find((e) => e.type === 'assistant_message');
      expect(assistantMsg).toBeDefined();
      if (assistantMsg?.type === 'assistant_message') {
        expect(assistantMsg.content).toBe('Here is the answer');
      }
    });
  });

  describe('Sequence Number Management', () => {
    it('should increment eventTimeUs for each appended event', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      // Set up empty conversation state
      const convState = createDefaultConversationState();
      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-1',
          conversationStates: new Map([['conv-1', convState]]),
        });
        useTimelineStore.getState().setAgentTimeline([]);
      });

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        handler.onMessage?.({
          type: 'message',
          data: {
            id: 'msg-1',
            role: 'user',
            content: 'Hello',
            created_at: new Date().toISOString(),
          },
        } as AgentEvent<MessageEventData>);
        handler.onThought?.({
          type: 'thought',
          data: { thought: 'Thinking', thought_level: 'task' },
        } as AgentEvent<ThoughtEventData>);
        handler.onAct?.({
          type: 'act',
          data: { tool_name: 'search', tool_input: {}, step_number: 1 },
        } as AgentEvent<ActEventData>);
        handler.onObserve?.({
          type: 'observe',
          data: { observation: 'Result' },
        } as AgentEvent<ObserveEventData>);
        handler.onComplete?.({
          type: 'complete',
          data: { content: 'Done', id: 'msg-2', artifacts: [] },
        } as AgentEvent<CompleteEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Hello', 'proj-123');
      });

      const timeline = getTimeline();
      const eventTimeUsList = timeline.map((e) => e.eventTimeUs ?? 0);

      // Should have incrementing eventTimeUs
      for (let i = 1; i < eventTimeUsList.length; i++) {
        expect(eventTimeUsList[i]).toBeGreaterThanOrEqual(eventTimeUsList[i - 1]);
      }
    });

    it('should continue sequence from existing timeline', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      // Use a fixed old time for existing events to ensure new events are after
      const oldTime = 1000000000000000; // Fixed past timestamp
      // Start with existing events in conversation state
      const convState = createDefaultConversationState();
      convState.timeline = [
        {
          id: 'existing-1',
          type: 'user_message',
          eventTimeUs: oldTime,
          eventCounter: 1,
          timestamp: Math.floor(oldTime / 1000),
          content: 'Previous',
          role: 'user',
        },
        {
          id: 'existing-2',
          type: 'assistant_message',
          eventTimeUs: oldTime + 1000000,
          eventCounter: 2,
          timestamp: Math.floor((oldTime + 1000000) / 1000),
          content: 'Response',
          role: 'assistant',
        },
      ];
      act(() => {
        useAgentV3Store.setState({
          activeConversationId: 'conv-1',
          conversationStates: new Map([['conv-1', convState]]),
        });
        useTimelineStore.getState().setAgentTimeline(convState.timeline);
      });

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        // SSE returns a thought event (not the user message which was created locally)
        handler.onThought?.({
          type: 'thought',
          data: {
            thought: 'Processing new message',
            thought_level: 'task',
            step_number: 1,
          },
        } as AgentEvent<ThoughtEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('New message', 'proj-123');
      });

      const timeline = getTimeline();
      // Find the user message that was created locally
      const userMessages = timeline.filter((e) => e.type === 'user_message');
      // Should have 2 user messages now (original + new)
      expect(userMessages.length).toBe(2);

      // The new user message should have eventTimeUs defined and greater than old events
      const newUserMessage = userMessages[userMessages.length - 1];
      expect(newUserMessage.eventTimeUs).toBeDefined();
      expect(newUserMessage.eventTimeUs ?? 0).toBeGreaterThan(oldTime);

      // The thought event should also have eventTimeUs defined and greater than old events
      const thoughtEvents = timeline.filter((e) => e.type === 'thought');
      const newThought = thoughtEvents[thoughtEvents.length - 1];
      expect(newThought.eventTimeUs).toBeDefined();
      expect(newThought.eventTimeUs ?? 0).toBeGreaterThan(oldTime);
    });
  });

  describe('Timeline-Messages Consistency', () => {
    it('should keep messages in sync with timeline', async () => {
      const { result } = renderHook(() => useAgentV3Store());

      const { agentService } = await import('../../services/agentService');
      vi.mocked(agentService.createConversation).mockResolvedValue({
        id: 'conv-1',
        project_id: 'proj-123',
        title: 'Test',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      } as any);

      vi.mocked(agentService.chat).mockImplementation(async (_request, handler) => {
        handler.onMessage?.({
          type: 'message',
          data: {
            id: 'msg-1',
            role: 'user',
            content: 'Hello',
            created_at: new Date().toISOString(),
          },
        } as AgentEvent<MessageEventData>);
        handler.onComplete?.({
          type: 'complete',
          data: { content: 'Hi there!', id: 'msg-2', artifacts: [] },
        } as AgentEvent<CompleteEventData>);
        return Promise.resolve();
      });

      await act(async () => {
        await result.current.sendMessage('Hello', 'proj-123');
      });

      const timeline = getTimeline();
      const messages = getMessages();

      // Both should have the same number of message-type events
      const timelineMessages = timeline.filter(
        (e) => e.type === 'user_message' || e.type === 'assistant_message'
      );
      expect(messages.length).toBe(timelineMessages.length);
    });
  });
});

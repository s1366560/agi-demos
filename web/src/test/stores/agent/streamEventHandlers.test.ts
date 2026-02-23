import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { createStreamEventHandlers } from '../../../stores/agent/streamEventHandlers';

import type {
  DeltaBufferState,
  StreamHandlerDeps,
} from '../../../stores/agent/streamEventHandlers';
import type {
  AgentEvent,
  ThoughtEventData,
  ActEventData,
  ObserveEventData,
  TextDeltaEventData,
} from '../../../types/agent';
import type { ConversationState } from '../../../types/conversationState';

describe('streamEventHandlers', () => {
  const conversationId = 'conv-1';
  // Mock state object
  let mockState: ConversationState;

  // Mock dependencies
  let mockUpdateConversationState: ReturnType<typeof vi.fn>;
  let mockGetConversationState: ReturnType<typeof vi.fn>;
  let mockSet: ReturnType<typeof vi.fn>;
  let deltaBuffers: Map<string, DeltaBufferState>;
  let mockDeps: StreamHandlerDeps;

  beforeEach(() => {
    vi.useFakeTimers();

    // Initialize mock state with minimal required fields
    mockState = {
      conversationId,
      messages: [],
      timeline: [],
      isStreaming: false,
      isThinkingStreaming: false,
      agentState: 'idle',
      streamingAssistantContent: '',
      streamingThought: '',
      activeToolCalls: new Map(),
      pendingToolsStack: [],
      tasks: [],
      executionNarrative: [],
      latestToolsetChange: null,
      artifacts: [],
      files: [],
      isPlanMode: false,
      streamStatus: 'idle',
      currentThought: '',
      // ... other fields can be undefined or partial for tests
    } as unknown as ConversationState;

    mockUpdateConversationState = vi.fn((id, updates) => {
      // Apply updates to mockState for subsequent calls
      Object.assign(mockState, updates);
    });

    mockGetConversationState = vi.fn().mockReturnValue(mockState);

    mockSet = vi.fn();

    deltaBuffers = new Map();
    const getDeltaBuffer = (id: string) => {
      if (!deltaBuffers.has(id)) {
        deltaBuffers.set(id, {
          textDeltaBuffer: '',
          textDeltaFlushTimer: null,
          thoughtDeltaBuffer: '',
          thoughtDeltaFlushTimer: null,
          actDeltaBuffer: null,
          actDeltaFlushTimer: null,
        });
      }
      return deltaBuffers.get(id)!;
    };

    mockDeps = {
      get: () => ({
        activeConversationId: conversationId,
        getConversationState: mockGetConversationState,
        updateConversationState: mockUpdateConversationState,
      }),
      set: mockSet,
      getDeltaBuffer,
      clearDeltaBuffers: vi.fn(),
      clearAllDeltaBuffers: vi.fn(),
      timelineToMessages: vi.fn(),
      tokenBatchIntervalMs: 50,
      thoughtBatchIntervalMs: 50,
    };
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.restoreAllMocks();
  });

  it('should handle onTextStart', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    handlers.onTextStart!();

    expect(mockUpdateConversationState).toHaveBeenCalledWith(conversationId, {
      streamStatus: 'streaming',
      streamingAssistantContent: '',
    });
  });

  it('should append channel inbound onMessage event to timeline', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    const convertedMessages = [{ id: 'msg-1', role: 'user', content: 'hello from feishu' }];
    (mockDeps.timelineToMessages as any).mockReturnValue(convertedMessages);

    handlers.onMessage!({
      type: 'message',
      data: {
        id: 'om_1',
        role: 'user',
        content: 'hello from feishu',
        metadata: { source: 'channel_inbound' },
      } as any,
    });

    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        timeline: expect.arrayContaining([
          expect.objectContaining({
            type: 'user_message',
            id: 'om_1',
            content: 'hello from feishu',
          }),
        ]),
      })
    );
    expect(mockSet).toHaveBeenCalledWith({ messages: convertedMessages });
  });

  it('should ignore non-channel onMessage events', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);

    handlers.onMessage!({
      type: 'message',
      data: {
        id: 'msg-regular',
        role: 'user',
        content: 'hello',
      } as any,
    });

    expect(mockUpdateConversationState).not.toHaveBeenCalled();
    expect(mockSet).not.toHaveBeenCalled();
  });

  it('should buffer and flush onTextDelta', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    const event: AgentEvent<TextDeltaEventData> = {
      type: 'text_delta',
      data: { delta: 'Hello' },
    };

    // First chunk
    handlers.onTextDelta!(event);

    // Should not update state yet (buffered)
    expect(mockUpdateConversationState).not.toHaveBeenCalled();

    // Advance timer to trigger flush
    vi.advanceTimersByTime(50);

    expect(mockUpdateConversationState).toHaveBeenCalledWith(conversationId, {
      streamingAssistantContent: 'Hello',
      streamStatus: 'streaming',
    });
  });

  it('should handle onTextEnd and flush remaining buffer', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);

    // Add some data to buffer
    handlers.onTextDelta!({ type: 'text_delta', data: { delta: 'World' } });

    const endEvent: AgentEvent<any> = {
      type: 'text_end',
      data: { full_text: 'Hello World' },
    };

    handlers.onTextEnd!(endEvent);

    // Should clear timer
    const buffer = deltaBuffers.get(conversationId)!;
    expect(buffer.textDeltaFlushTimer).toBeNull();
    expect(buffer.textDeltaBuffer).toBe('');

    // Should update state with timeline event
    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        streamingAssistantContent: '',
        timeline: expect.arrayContaining([
          expect.objectContaining({
            type: 'text_end',
            fullText: 'Hello World',
          }),
        ]),
      })
    );
  });

  it('should keep text_end events stable on onComplete', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    mockState.timeline = [
      {
        id: 'text-start-1',
        type: 'text_start',
        timestamp: Date.now(),
      } as any,
      {
        id: 'text-delta-1',
        type: 'text_delta',
        content: 'partial',
        timestamp: Date.now(),
      } as any,
      {
        id: 'text-end-1',
        type: 'text_end',
        fullText: 'final content',
        timestamp: Date.now(),
      } as any,
    ];
    (mockDeps.timelineToMessages as any).mockReturnValue([
      { id: 'text-end-1', role: 'assistant', content: 'final content' },
    ]);

    handlers.onComplete!({
      type: 'complete',
      data: {
        content: 'final content',
      } as any,
    });

    const completionCall = mockUpdateConversationState.mock.calls.find(
      ([, updates]) => (updates as any).isStreaming === false
    );
    const completionUpdates = completionCall?.[1] as any;

    expect(completionUpdates).toBeDefined();
    expect(
      completionUpdates.timeline.some(
        (e: any) => e.type === 'text_start' || e.type === 'text_delta'
      )
    ).toBe(false);
    expect(
      completionUpdates.timeline.some((e: any) => e.type === 'text_end' && e.id === 'text-end-1')
    ).toBe(true);
    expect(completionUpdates.timeline.some((e: any) => e.type === 'assistant_message')).toBe(false);
  });

  it('should handle onAct (tool call)', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    const event: AgentEvent<ActEventData> = {
      type: 'act',
      data: {
        tool_name: 'search',
        tool_input: { query: 'test' },
        step_number: 1,
      },
    };

    handlers.onAct!(event);

    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        agentState: 'acting',
        activeToolCalls: expect.any(Map),
        pendingToolsStack: ['search'],
      })
    );

    // Verify activeToolCalls map in the update call
    const lastCall = mockUpdateConversationState.mock.calls[0];
    const updates = lastCall[1];
    const calls = updates.activeToolCalls;
    expect(calls.get('search')).toEqual(
      expect.objectContaining({
        name: 'search',
        status: 'running',
      })
    );
  });

  it('should handle onObserve (tool result)', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);

    // Setup initial state with active tool call
    const activeCalls = new Map();
    activeCalls.set('search', { name: 'search', status: 'running' });
    mockState.activeToolCalls = activeCalls;
    mockState.pendingToolsStack = ['search'];

    const event: AgentEvent<ObserveEventData> = {
      type: 'observe',
      data: {
        tool_name: 'search',
        observation: 'Found results',
      },
    };

    handlers.onObserve!(event);

    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        agentState: 'observing',
        pendingToolsStack: [], // Should pop 'search'
        activeToolCalls: expect.any(Map),
      })
    );

    const lastCall = mockUpdateConversationState.mock.calls[0];
    const updates = lastCall[1];
    const calls = updates.activeToolCalls;
    expect(calls.get('search').status).toBe('success');
    expect(calls.get('search').result).toBe('Found results');
  });

  it('should buffer and flush onThoughtDelta', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    const event: AgentEvent<any> = {
      type: 'thought_delta',
      data: { delta: 'Thinking...' },
    };

    handlers.onThoughtDelta!(event);

    expect(mockUpdateConversationState).not.toHaveBeenCalled();

    vi.advanceTimersByTime(50);

    expect(mockUpdateConversationState).toHaveBeenCalledWith(conversationId, {
      streamingThought: 'Thinking...',
      isThinkingStreaming: true,
      agentState: 'thinking',
    });
  });

  it('should handle onThought and add to timeline', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    const event: AgentEvent<ThoughtEventData> = {
      type: 'thought',
      data: {
        thought: 'I should search.',
        thought_level: 'work',
        step_number: 1,
      },
    };

    handlers.onThought!(event);

    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        agentState: 'thinking',
        isThinkingStreaming: false,
        streamingThought: '',
        currentThought: '\nI should search.',
        timeline: expect.arrayContaining([
          expect.objectContaining({
            type: 'thought',
            content: 'I should search.',
          }),
        ]),
      })
    );
  });

  it('should handle onTaskListUpdated', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    const tasks = [{ id: 'task-1', status: 'pending', title: 'Task 1' }];
    const event: AgentEvent<any> = {
      type: 'task_list_updated',
      data: {
        conversation_id: conversationId,
        tasks,
      },
    };

    handlers.onTaskListUpdated!(event);

    expect(mockUpdateConversationState).toHaveBeenCalledWith(conversationId, {
      tasks,
    });
  });

  it('should persist execution insights events in conversation state', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);

    handlers.onExecutionPathDecided!({
      type: 'execution_path_decided',
      data: {
        path: 'react_loop',
        confidence: 0.75,
        reason: 'Standard routing',
        metadata: { domain_lane: 'general' },
      },
    } as any);
    handlers.onSelectionTrace!({
      type: 'selection_trace',
      data: {
        initial_count: 20,
        final_count: 8,
        removed_total: 12,
        stages: [],
      },
    } as any);
    handlers.onPolicyFiltered!({
      type: 'policy_filtered',
      data: {
        removed_total: 12,
        stage_count: 4,
      },
    } as any);

    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        executionPathDecision: expect.objectContaining({ path: 'react_loop' }),
      })
    );
    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        selectionTrace: expect.objectContaining({ final_count: 8 }),
      })
    );
    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        policyFiltered: expect.objectContaining({ removed_total: 12 }),
      })
    );
    expect(mockState.executionNarrative).toHaveLength(3);
  });

  it('should handle onToolsetChanged and append execution narrative', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);

    handlers.onToolsetChanged!({
      type: 'toolset_changed',
      data: {
        source: 'plugin_manager',
        action: 'reload',
        plugin_name: 'demo-plugin',
        trace_id: 'toolset-trace-1',
        refresh_status: 'success',
        refreshed_tool_count: 42,
      },
    } as any);

    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        latestToolsetChange: expect.objectContaining({
          action: 'reload',
          plugin_name: 'demo-plugin',
          refresh_status: 'success',
        }),
      })
    );
    const lastNarrativeEntry =
      mockState.executionNarrative[mockState.executionNarrative.length - 1];
    expect(lastNarrativeEntry).toEqual(
      expect.objectContaining({
        stage: 'toolset',
        trace_id: 'toolset-trace-1',
      })
    );
  });
});

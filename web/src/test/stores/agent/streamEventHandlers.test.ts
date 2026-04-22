import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

import { createStreamEventHandlers } from '../../../stores/agent/streamEventHandlers';
import { useCanvasStore } from '../../../stores/canvasStore';
import { useLayoutModeStore } from '../../../stores/layoutMode';
import { getA2UIContractCase, getA2UIContractMessages } from '../../fixtures/a2uiContractFixtures';
import {
  getNativeBlockFixtureCase,
  serializeNativeBlockContent,
} from '../../fixtures/canvasNativeBlockFixtures';
import { appendSSEEventToTimeline } from '../../../utils/sseEventAdapter';

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
    useCanvasStore.getState().reset();
    useLayoutModeStore.getState().setMode('chat');

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
      queueTimelineEvent: vi.fn((event, stateUpdates) => {
        const nextTimeline = appendSSEEventToTimeline(
          mockState.timeline as any,
          event as any
        ) as any;
        mockUpdateConversationState(conversationId, {
          timeline: nextTimeline,
          ...(stateUpdates || {}),
        });
      }),
      flushTimelineBufferSync: vi.fn(),
    };
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.restoreAllMocks();
  });

  it('should handle onTextStart', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    mockState.streamingThought = 'old thought';
    mockState.isThinkingStreaming = true;
    handlers.onTextStart!();

    expect(mockUpdateConversationState).toHaveBeenCalledWith(conversationId, {
      streamStatus: 'streaming',
      streamingAssistantContent: '',
      streamingThought: '',
      isThinkingStreaming: false,
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

  it('should clear stale thinking state when text delta arrives without text_start', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    mockState.streamingThought = 'leftover thought';
    mockState.isThinkingStreaming = true;

    handlers.onTextDelta!({
      type: 'text_delta',
      data: { delta: 'Answer token' },
    });

    vi.advanceTimersByTime(50);

    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        streamingAssistantContent: 'Answer token',
        streamStatus: 'streaming',
        streamingThought: '',
        isThinkingStreaming: false,
      })
    );
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
        streamingThought: '',
        isThinkingStreaming: false,
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
    mockState.streamingThought = 'stale thought chunk';
    mockState.isThinkingStreaming = true;
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
        trace_url: 'https://trace.example/1',
        execution_summary: { step_count: 2, artifact_count: 1 },
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
    const textEndEvent = completionUpdates.timeline.find((e: any) => e.type === 'text_end');
    expect(textEndEvent?.metadata).toEqual({
      traceUrl: 'https://trace.example/1',
      executionSummary: {
        stepCount: 2,
        artifactCount: 1,
        callCount: 0,
        totalCost: 0,
        totalCostFormatted: '$0.000000',
        totalTokens: {
          input: 0,
          output: 0,
          reasoning: 0,
          cacheRead: 0,
          cacheWrite: 0,
          total: 0,
        },
        tasks: undefined,
      },
    });
    expect(completionUpdates.streamingThought).toBe('');
    expect(completionUpdates.isThinkingStreaming).toBe(false);
  });

  it('should preserve complete artifacts when merging into a text_end bubble', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    mockState.timeline = [
      {
        id: 'user-1',
        type: 'user_message',
        content: 'generate a file',
        timestamp: Date.now() - 100,
      } as any,
      {
        id: 'text-end-1',
        type: 'text_end',
        fullText: 'generated',
        timestamp: Date.now(),
      } as any,
    ];
    (mockDeps.timelineToMessages as any).mockReturnValue([
      { id: 'text-end-1', role: 'assistant', content: 'generated' },
    ]);

    handlers.onComplete!({
      type: 'complete',
      data: {
        content: 'generated',
        artifacts: [
          {
            url: 'https://example.com/output/report.pdf',
            object_key: 'artifacts/report.pdf',
            mime_type: 'application/pdf',
            size_bytes: 2048,
          },
        ],
      } as any,
    });

    const completionCall = mockUpdateConversationState.mock.calls.find(
      ([, updates]) => (updates as any).isStreaming === false
    );
    const completionUpdates = completionCall?.[1] as any;
    const textEndEvent = completionUpdates.timeline.find((e: any) => e.type === 'text_end');

    expect(textEndEvent?.artifacts).toEqual([
      expect.objectContaining({
        url: 'https://example.com/output/report.pdf',
        object_key: 'artifacts/report.pdf',
      }),
    ]);
    expect(textEndEvent?.metadata).toEqual({
      artifacts: [
        expect.objectContaining({
          url: 'https://example.com/output/report.pdf',
          object_key: 'artifacts/report.pdf',
        }),
      ],
    });
  });

  it('should append metadata-only complete events when no text_end exists', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    mockState.timeline = [];
    (mockDeps.timelineToMessages as any).mockReturnValue([
      { id: 'assistant-1', role: 'assistant', content: '' },
    ]);

    handlers.onComplete!({
      type: 'complete',
      data: {
        trace_url: 'https://trace.example/2',
        execution_summary: { step_count: 1 },
      } as any,
    });

    const completionCall = mockUpdateConversationState.mock.calls.find(
      ([, updates]) => (updates as any).isStreaming === false
    );
    const completionUpdates = completionCall?.[1] as any;
    const assistantEvent = completionUpdates.timeline.find(
      (e: any) => e.type === 'assistant_message'
    );

    expect(assistantEvent).toBeDefined();
    expect(assistantEvent.metadata).toEqual({
      traceUrl: 'https://trace.example/2',
      executionSummary: {
        stepCount: 1,
        artifactCount: 0,
        callCount: 0,
        totalCost: 0,
        totalCostFormatted: '$0.000000',
        totalTokens: {
          input: 0,
          output: 0,
          reasoning: 0,
          cacheRead: 0,
          cacheWrite: 0,
          total: 0,
        },
        tasks: undefined,
      },
    });
  });

  it('should not merge a new complete-only turn into an older text_end bubble', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    mockState.timeline = [
      {
        id: 'text-end-old',
        type: 'text_end',
        fullText: 'older final content',
        timestamp: Date.now() - 1000,
      } as any,
      {
        id: 'user-message-new',
        type: 'user_message',
        content: 'new question',
        timestamp: Date.now(),
      } as any,
    ];
    (mockDeps.timelineToMessages as any).mockReturnValue([
      { id: 'text-end-old', role: 'assistant', content: 'older final content' },
      { id: 'assistant-new', role: 'assistant', content: 'new final content' },
    ]);

    handlers.onComplete!({
      type: 'complete',
      data: {
        content: 'new final content',
        trace_url: 'https://trace.example/3',
      } as any,
    });

    const completionCall = mockUpdateConversationState.mock.calls.find(
      ([, updates]) => (updates as any).isStreaming === false
    );
    const completionUpdates = completionCall?.[1] as any;
    const oldTextEnd = completionUpdates.timeline.find((e: any) => e.id === 'text-end-old');
    const assistantMessages = completionUpdates.timeline.filter(
      (e: any) => e.type === 'assistant_message'
    );

    expect(oldTextEnd?.metadata).toBeUndefined();
    expect(assistantMessages).toHaveLength(1);
    expect(assistantMessages[0].content).toBe('new final content');
    expect(assistantMessages[0].metadata).toEqual({ traceUrl: 'https://trace.example/3' });
  });

  it('should append completion metadata when no user-message turn anchor exists', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    mockState.timeline = [
      {
        id: 'text-end-old',
        type: 'text_end',
        fullText: 'older final content',
        timestamp: Date.now() - 1000,
      } as any,
    ];
    (mockDeps.timelineToMessages as any).mockReturnValue([
      { id: 'text-end-old', role: 'assistant', content: 'older final content' },
      { id: 'assistant-new', role: 'assistant', content: 'new final content' },
    ]);

    handlers.onComplete!({
      type: 'complete',
      data: {
        content: 'new final content',
        trace_url: 'https://trace.example/4',
      } as any,
    });

    const completionCall = mockUpdateConversationState.mock.calls.find(
      ([, updates]) => (updates as any).isStreaming === false
    );
    const completionUpdates = completionCall?.[1] as any;
    const oldTextEnd = completionUpdates.timeline.find((e: any) => e.id === 'text-end-old');
    const assistantMessages = completionUpdates.timeline.filter(
      (e: any) => e.type === 'assistant_message'
    );

    expect(oldTextEnd?.metadata).toBeUndefined();
    expect(assistantMessages).toHaveLength(1);
    expect(assistantMessages[0].content).toBe('new final content');
    expect(assistantMessages[0].metadata).toEqual({ traceUrl: 'https://trace.example/4' });
  });

  it('should clear stale thinking state on onClose', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    mockState.streamingThought = 'partial thought';
    mockState.isThinkingStreaming = true;

    handlers.onClose!();

    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        streamingThought: '',
        isThinkingStreaming: false,
        isStreaming: false,
        streamStatus: 'idle',
      })
    );
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

  it('should derive A2UI surface id from payload content when metadata is missing', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    const content = [
      '{"beginRendering":{"surfaceId":"surface-42","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"surface-42","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
    ].join('\n');

    handlers.onCanvasUpdated!({
      type: 'canvas_updated',
      data: {
        conversation_id: conversationId,
        block_id: 'block-1',
        action: 'created',
        block: {
          id: 'block-1',
          block_type: 'a2ui_surface',
          title: 'Surface',
          content,
          metadata: {
            hitl_request_id: 'hitl-req-1',
          },
          version: 1,
        },
      } as any,
    });

    const tab = useCanvasStore.getState().tabs.find((item) => item.id === 'block-1');
    expect(tab?.a2uiSurfaceId).toBe('surface-42');
    expect(tab?.a2uiHitlRequestId).toBe('hitl-req-1');
    expect(tab?.a2uiMessages).toBe(content);
    expect(tab?.a2uiSnapshot?.surfaceId).toBe('surface-42');
    expect(mockState.timeline.some((item: any) => item.type === 'canvas_updated')).toBe(true);
    expect(useLayoutModeStore.getState().mode).toBe('canvas');
  });

  it('should materialize incremental A2UI dataModel updates into the tab snapshot', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    const initialContent = [
      '{"beginRendering":{"surfaceId":"surface-42","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"surface-42","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
    ].join('\n');
    const incrementalContent =
      '{"dataModelUpdate":{"surfaceId":"surface-42","path":"/","contents":[{"key":"stats","valueMap":[{"key":"count","valueNumber":2}]}]}}';

    handlers.onCanvasUpdated!({
      type: 'canvas_updated',
      data: {
        conversation_id: conversationId,
        block_id: 'block-1',
        action: 'created',
        block: {
          id: 'block-1',
          block_type: 'a2ui_surface',
          title: 'Surface',
          content: initialContent,
          metadata: {},
          version: 1,
        },
      } as any,
    });

    handlers.onCanvasUpdated!({
      type: 'canvas_updated',
      data: {
        conversation_id: conversationId,
        block_id: 'block-1',
        action: 'updated',
        block: {
          id: 'block-1',
          block_type: 'a2ui_surface',
          title: 'Surface',
          content: incrementalContent,
          metadata: {},
          version: 2,
        },
      } as any,
    });

    const tab = useCanvasStore.getState().tabs.find((item) => item.id === 'block-1');
    expect(tab?.a2uiSnapshot?.surfaceId).toBe('surface-42');
    expect(tab?.a2uiSnapshot?.data).toEqual({ stats: { count: 2 } });
    expect(tab?.a2uiMessages).toContain('"dataModelUpdate"');
  });

  it('should clear a2uiHitlRequestId when canvas metadata clears the request marker', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    const content = [
      '{"beginRendering":{"surfaceId":"surface-42","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"surface-42","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
    ].join('\n');

    handlers.onA2UIActionAsked!({
      type: 'a2ui_action_asked',
      data: {
        request_id: 'hitl-req-buffered',
        conversation_id: conversationId,
        block_id: 'block-1',
      } as any,
    });

    useCanvasStore.getState().openTab({
      id: 'block-1',
      title: 'Surface',
      type: 'a2ui-surface',
      content,
      a2uiSurfaceId: 'surface-42',
      a2uiMessages: content,
      a2uiHitlRequestId: 'hitl-req-1',
    });

    handlers.onCanvasUpdated!({
      type: 'canvas_updated',
      data: {
        conversation_id: conversationId,
        block_id: 'block-1',
        action: 'updated',
        block: {
          id: 'block-1',
          block_type: 'a2ui_surface',
          title: 'Surface',
          content,
          metadata: {
            hitl_request_id: '',
          },
          version: 2,
        },
      } as any,
    });

    const tab = useCanvasStore.getState().tabs.find((item) => item.id === 'block-1');
    expect(tab?.a2uiHitlRequestId).toBeUndefined();
  });

  it('should preserve surface continuity when a post-interaction update clears the HITL marker', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    const contractCase = getA2UIContractCase('identity_interactive_request');
    const initialContent = getA2UIContractMessages(contractCase.id);
    const incrementalContent = JSON.stringify({
      dataModelUpdate: {
        surfaceId: contractCase.identity?.surfaceId,
        path: '/',
        contents: [
          { key: 'status', valueString: 'done' },
          { key: 'approved', valueBoolean: true },
        ],
      },
    });

    handlers.onA2UIActionAsked!({
      type: 'a2ui_action_asked',
      data: {
        request_id: contractCase.identity?.hitlRequestId,
        conversation_id: conversationId,
        block_id: 'block-1',
      } as any,
    });

    handlers.onCanvasUpdated!({
      type: 'canvas_updated',
      data: {
        conversation_id: conversationId,
        block_id: 'block-1',
        action: 'created',
        block: {
          id: 'block-1',
          block_type: 'a2ui_surface',
          title: 'Surface',
          content: initialContent,
          metadata: {
            surface_id: contractCase.identity?.metadataSurfaceId,
            hitl_request_id: contractCase.identity?.hitlRequestId,
          },
          version: 1,
        },
      } as any,
    });

    handlers.onCanvasUpdated!({
      type: 'canvas_updated',
      data: {
        conversation_id: conversationId,
        block_id: 'block-1',
        action: 'updated',
        block: {
          id: 'block-1',
          block_type: 'a2ui_surface',
          title: 'Surface',
          content: incrementalContent,
          metadata: {
            surface_id: contractCase.identity?.metadataSurfaceId,
            hitl_request_id: '',
          },
          version: 2,
        },
      } as any,
    });

    const tab = useCanvasStore.getState().tabs.find((item) => item.id === 'block-1');
    expect(tab?.a2uiSurfaceId).toBe(contractCase.identity?.metadataSurfaceId);
    expect(tab?.a2uiHitlRequestId).toBeUndefined();
    expect(tab?.a2uiMessages).toContain('"dataModelUpdate"');
    expect(tab?.a2uiSnapshot?.data).toEqual({ status: 'done', approved: true });
    expect(tab?.a2uiSnapshot?.root).toBe('root-1');
  });

  it('should append a2ui_action_asked to the timeline', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);

    handlers.onA2UIActionAsked!({
      type: 'a2ui_action_asked',
      data: {
        request_id: 'hitl-req-1',
        conversation_id: conversationId,
        block_id: 'block-1',
      } as any,
    });

    expect(mockState.timeline.some((item: any) => item.type === 'a2ui_action_asked')).toBe(true);
  });

  it('should buffer A2UI request ids that arrive before the canvas tab exists', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    const content = [
      '{"beginRendering":{"surfaceId":"surface-42","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"surface-42","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
    ].join('\n');

    handlers.onA2UIActionAsked!({
      type: 'a2ui_action_asked',
      data: {
        request_id: 'hitl-req-buffered',
        conversation_id: conversationId,
        block_id: 'block-1',
      } as any,
    });

    handlers.onCanvasUpdated!({
      type: 'canvas_updated',
      data: {
        conversation_id: conversationId,
        block_id: 'block-1',
        action: 'created',
        block: {
          id: 'block-1',
          block_type: 'a2ui_surface',
          title: 'Surface',
          content,
          metadata: {},
          version: 1,
        },
      } as any,
    });

    const tab = useCanvasStore.getState().tabs.find((item) => item.id === 'block-1');
    expect(tab?.a2uiHitlRequestId).toBe('hitl-req-buffered');
    expect(tab?.a2uiSnapshot?.surfaceId).toBe('surface-42');
  });

  it('should scope buffered A2UI request ids by conversation', () => {
    const handlersA = createStreamEventHandlers('conv-a', undefined, mockDeps);
    const handlersB = createStreamEventHandlers('conv-b', undefined, mockDeps);
    const content = [
      '{"beginRendering":{"surfaceId":"surface-42","root":"root-1"}}',
      '{"surfaceUpdate":{"surfaceId":"surface-42","components":[{"id":"root-1","component":{"Text":{"text":{"literal":"hello"}}}}]}}',
    ].join('\n');

    handlersA.onA2UIActionAsked!({
      type: 'a2ui_action_asked',
      data: {
        request_id: 'hitl-req-a',
        conversation_id: 'conv-a',
        block_id: 'block-shared',
      } as any,
    });

    handlersB.onCanvasUpdated!({
      type: 'canvas_updated',
      data: {
        conversation_id: 'conv-b',
        block_id: 'block-shared',
        action: 'created',
        block: {
          id: 'block-shared',
          block_type: 'a2ui_surface',
          title: 'Surface',
          content,
          metadata: {},
          version: 1,
        },
      } as any,
    });

    const tab = useCanvasStore.getState().tabs.find((item) => item.id === 'block-shared');
    expect(tab?.a2uiHitlRequestId).toBeUndefined();
  });

  it.each([
    'chart_top_level_datasets',
    'widget_html_preview',
  ])(
    'should map native canvas block contract case %s into the expected tab type and update path',
    (caseId) => {
      const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
      const fixtureCase = getNativeBlockFixtureCase(caseId);
      const blockId = `block-${caseId}`;
      const updatedContent = serializeNativeBlockContent(
        fixtureCase.updatedContent ?? fixtureCase.content
      );
      const updatedTitle = fixtureCase.updatedTitle ?? `${fixtureCase.title} Updated`;

      handlers.onCanvasUpdated!({
        type: 'canvas_updated',
        data: {
          conversation_id: conversationId,
          block_id: blockId,
          action: 'created',
          block: {
            id: blockId,
            block_type: fixtureCase.blockType,
            title: fixtureCase.title,
            content: serializeNativeBlockContent(fixtureCase.content),
            metadata: {},
            version: 1,
          },
        } as any,
      });

      handlers.onCanvasUpdated!({
        type: 'canvas_updated',
        data: {
          conversation_id: conversationId,
          block_id: blockId,
          action: 'updated',
          block: {
            id: blockId,
            block_type: fixtureCase.blockType,
            title: updatedTitle,
            content: updatedContent,
            metadata: {},
            version: 2,
          },
        } as any,
      });

      const tab = useCanvasStore.getState().tabs.find((item) => item.id === blockId);
      expect(tab?.type).toBe(fixtureCase.expected.frontendTabType);
      expect(tab?.title).toBe(updatedTitle);
      expect(tab?.content).toBe(updatedContent);
      expect(mockState.timeline.some((item: any) => item.type === 'canvas_updated')).toBe(true);
      expect(useLayoutModeStore.getState().mode).toBe('canvas');
    }
  );

  it.each([
    'chart_top_level_datasets',
    'widget_html_preview',
  ])('should open a native tab from update-only canvas events for %s', (caseId) => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    const fixtureCase = getNativeBlockFixtureCase(caseId);
    const blockId = `block-${caseId}-update-only`;
    const updatedContent = serializeNativeBlockContent(
      fixtureCase.updatedContent ?? fixtureCase.content
    );
    const updatedTitle = fixtureCase.updatedTitle ?? `${fixtureCase.title} Updated`;

    handlers.onCanvasUpdated!({
      type: 'canvas_updated',
      data: {
        conversation_id: conversationId,
        block_id: blockId,
        action: 'updated',
        block: {
          id: blockId,
          block_type: fixtureCase.blockType,
          title: updatedTitle,
          content: updatedContent,
          metadata: {},
          version: 2,
        },
      } as any,
    });

    const tab = useCanvasStore.getState().tabs.find((item) => item.id === blockId);
    expect(tab?.type).toBe(fixtureCase.expected.frontendTabType);
    expect(tab?.title).toBe(updatedTitle);
    expect(tab?.content).toBe(updatedContent);
    expect(mockState.timeline.some((item: any) => item.type === 'canvas_updated')).toBe(true);
    expect(useLayoutModeStore.getState().mode).toBe('canvas');
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

  it('should clear stale thinking residue after thought delta goes idle', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    handlers.onThoughtDelta!({
      type: 'thought_delta',
      data: { delta: 'Working through options...' },
    } as any);

    vi.advanceTimersByTime(50);
    expect(mockState.isThinkingStreaming).toBe(true);
    expect(mockState.streamingThought).toBe('Working through options...');

    const updateCallCountAfterFlush = mockUpdateConversationState.mock.calls.length;
    vi.advanceTimersByTime(400);

    expect(mockUpdateConversationState.mock.calls.length).toBeGreaterThan(
      updateCallCountAfterFlush
    );
    expect(mockUpdateConversationState).toHaveBeenLastCalledWith(conversationId, {
      isThinkingStreaming: false,
    });
  });

  it('should not flush stale thought delta after onTextStart', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    handlers.onThoughtDelta!({
      type: 'thought_delta',
      data: { delta: 'stale thought' },
    } as any);

    vi.advanceTimersByTime(10);
    handlers.onTextStart!();
    mockUpdateConversationState.mockClear();

    vi.advanceTimersByTime(500);

    expect(mockUpdateConversationState).not.toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        streamingThought: 'stale thought',
        isThinkingStreaming: true,
      })
    );
  });

  it('should keep pending thought delta and finalized thought after onThought', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    handlers.onThoughtDelta!({
      type: 'thought_delta',
      data: { delta: 'stale thought' },
    } as any);

    vi.advanceTimersByTime(10);
    handlers.onThought!({
      type: 'thought',
      data: {
        thought: 'finalized thought',
      },
    } as any);

    vi.advanceTimersByTime(500);
    expect(mockState.isThinkingStreaming).toBe(false);
    expect(mockState.streamingThought).toBe('stale thought\nfinalized thought');
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
        streamingThought: 'I should search.',
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

  it('should merge buffered thought delta with onThought content when flush has not run', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    handlers.onThoughtDelta!({
      type: 'thought_delta',
      data: { delta: 'partial delta ' },
    } as any);

    vi.advanceTimersByTime(10);
    handlers.onThought!({
      type: 'thought',
      data: {
        thought: 'final thought',
      },
    } as any);

    expect(mockState.streamingThought).toBe('partial delta\nfinal thought');
    expect(mockState.isThinkingStreaming).toBe(false);
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

  it('should ignore malformed task_list_updated payloads', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);

    expect(() =>
      handlers.onTaskListUpdated!({
        type: 'task_list_updated',
        data: {
          conversation_id: conversationId,
        },
      } as any)
    ).not.toThrow();

    expect(mockUpdateConversationState).not.toHaveBeenCalled();
  });

  it('should ignore malformed task_updated payloads', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);

    expect(() =>
      handlers.onTaskUpdated!({
        type: 'task_updated',
        data: {
          conversation_id: conversationId,
          content: 'Missing task id and status',
        },
      } as any)
    ).not.toThrow();

    expect(mockUpdateConversationState).not.toHaveBeenCalled();
  });

  it('should handle onModelSwitchRequested and merge appModelContext', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);
    mockState.appModelContext = { llm_overrides: { temperature: 0.3 } } as any;

    handlers.onModelSwitchRequested!({
      type: 'model_switch_requested',
      data: {
        conversation_id: conversationId,
        model: 'volcengine/doubao-1.5-pro-32k-250115',
        scope: 'next_turn',
      },
    } as any);

    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        appModelContext: expect.objectContaining({
          llm_model_override: 'volcengine/doubao-1.5-pro-32k-250115',
          llm_overrides: { temperature: 0.3 },
        }),
      })
    );
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

  it('handles onAgentGoalCompleted by storing the summary on conversation state', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);

    handlers.onAgentGoalCompleted!({
      type: 'agent_goal_completed',
      data: {
        conversation_id: conversationId,
        summary: 'All checks passed',
      },
    } as any);

    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({ goalCompletionSummary: 'All checks passed' })
    );
  });

  it('handles onAgentConversationFinished by marking the conversation terminated', () => {
    const handlers = createStreamEventHandlers(conversationId, undefined, mockDeps);

    handlers.onAgentConversationFinished!({
      type: 'agent_conversation_finished',
      data: {
        conversation_id: conversationId,
        reason: 'goal_completed',
        rationale: 'goal evaluator passed',
      },
    } as any);

    expect(mockUpdateConversationState).toHaveBeenCalledWith(
      conversationId,
      expect.objectContaining({
        isTerminated: true,
        terminationReason: 'goal_completed',
        terminationRationale: 'goal evaluator passed',
        isStreaming: false,
        streamStatus: 'idle',
        agentState: 'idle',
      })
    );
  });
});

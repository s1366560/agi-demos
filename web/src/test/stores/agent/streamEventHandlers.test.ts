/**
 * Tests for streamEventHandlers - Tool visibility during streaming
 *
 * This test suite verifies that tool calls are correctly tracked
 * in activeToolCalls during the act -> observe flow.
 *
 * TDD Phase: Fix tool streaming visibility issue
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';

import { createStreamEventHandlers } from '../../../stores/agent/streamEventHandlers';

import type {
  AgentStreamHandler,
  AgentEvent,
  ActEventData,
  ObserveEventData,
} from '../../../types/agent';
import type { ConversationState } from '../../../types/conversationState';

// Mock external dependencies
vi.mock('../../../utils/sseEventAdapter', () => ({
  appendSSEEventToTimeline: vi.fn((timeline, event) => [...timeline, event]),
}));

vi.mock('../../../utils/tabSync', () => ({
  tabSync: {
    broadcastConversationCompleted: vi.fn(),
    broadcastStreamingStateChanged: vi.fn(),
  },
}));

vi.mock('../../../stores/backgroundStore', () => ({
  useBackgroundStore: {
    getState: vi.fn(() => ({
      launch: vi.fn(),
      complete: vi.fn(),
      fail: vi.fn(),
    })),
  },
}));

vi.mock('../../../stores/canvasStore', () => ({
  useCanvasStore: {
    getState: vi.fn(() => ({
      openTab: vi.fn(),
      updateContent: vi.fn(),
      closeTab: vi.fn(),
      tabs: [],
    })),
  },
}));

vi.mock('../../../stores/contextStore', () => ({
  useContextStore: {
    getState: vi.fn(() => ({
      handleCostUpdate: vi.fn(),
      handleContextCompressed: vi.fn(),
      handleContextStatus: vi.fn(),
    })),
  },
}));

vi.mock('../../../stores/layoutMode', () => ({
  useLayoutModeStore: {
    getState: vi.fn(() => ({
      mode: 'chat',
      setMode: vi.fn(),
    })),
  },
}));

describe('streamEventHandlers - Tool Visibility', () => {
  let mockConversationState: ConversationState;
  let capturedUpdates: Partial<ConversationState>[];
  let handlers: AgentStreamHandler;

  const conversationId = 'test-conv-1';

  beforeEach(() => {
    vi.clearAllMocks();

    // Reset captured updates
    capturedUpdates = [];

    // Initialize mock conversation state
    mockConversationState = {
      timeline: [],
      isStreaming: true,
      streamStatus: 'streaming',
      streamingAssistantContent: '',
      error: null,
      agentState: 'idle',
      currentThought: '',
      streamingThought: '',
      isThinkingStreaming: false,
      activeToolCalls: new Map(),
      pendingToolsStack: [],
      isPlanMode: false,
      pendingClarification: null,
      pendingDecision: null,
      pendingEnvVarRequest: null,
      pendingPermission: null,
      doomLoopDetected: null,
      costTracking: null,
      suggestions: [],
      hasEarlier: false,
      earliestTimeUs: null,
      earliestCounter: null,
      tasks: [],
      appModelContext: null,
      pendingHITLSummary: null,
    };

    const mockGet = () => ({
      activeConversationId: conversationId,
      getConversationState: () => mockConversationState,
      updateConversationState: (id: string, updates: Partial<ConversationState>) => {
        // Capture the updates for assertions
        capturedUpdates.push(updates);
        // Apply updates to mock state for testing
        mockConversationState = {
          ...mockConversationState,
          ...updates,
          // Special handling for Maps
          activeToolCalls:
            updates.activeToolCalls !== undefined
              ? updates.activeToolCalls
              : mockConversationState.activeToolCalls,
        };
      },
    });

    // Create handlers with mock dependencies
    handlers = createStreamEventHandlers(
      conversationId,
      undefined, // no additional handlers
      {
        get: mockGet as any,
        set: vi.fn() as any,
        getDeltaBuffer: () => ({
          textDeltaBuffer: '',
          textDeltaFlushTimer: null,
          thoughtDeltaBuffer: '',
          thoughtDeltaFlushTimer: null,
          actDeltaBuffer: null,
          actDeltaFlushTimer: null,
        }),
        clearDeltaBuffers: () => {},
        clearAllDeltaBuffers: () => {},
        timelineToMessages: (timeline) => timeline,
        tokenBatchIntervalMs: 50,
        thoughtBatchIntervalMs: 50,
      }
    );
  });

  describe('onAct - Tool execution starts', () => {
    it('should add tool to activeToolCalls with running status', () => {
      const actEvent: AgentEvent<ActEventData> = {
        type: 'act',
        data: {
          tool_name: 'web_search',
          tool_input: { query: 'test' },
          step_number: 1,
        },
      };

      handlers.onAct?.(actEvent);

      // Verify updateConversationState was called
      expect(capturedUpdates.length).toBeGreaterThan(0);
      const updates = capturedUpdates[0];

      expect(updates.activeToolCalls).toBeDefined();
      expect(updates.activeToolCalls!.has('web_search')).toBe(true);

      const toolCall = updates.activeToolCalls!.get('web_search');
      expect(toolCall?.status).toBe('running');
      expect(toolCall?.arguments).toEqual({ query: 'test' });
    });

    it('should push tool name to pendingToolsStack', () => {
      const actEvent: AgentEvent<ActEventData> = {
        type: 'act',
        data: {
          tool_name: 'file_read',
          tool_input: { path: '/tmp/test.txt' },
          step_number: 1,
        },
      };

      handlers.onAct?.(actEvent);

      const updates = capturedUpdates[0];
      expect(updates.pendingToolsStack).toEqual(['file_read']);
    });
  });

  describe('onObserve - Tool execution completes', () => {
    it('should pop tool from pendingToolsStack', () => {
      // First, simulate an act event
      mockConversationState.pendingToolsStack = ['web_search'];
      mockConversationState.activeToolCalls = new Map([
        [
          'web_search',
          {
            name: 'web_search',
            arguments: { query: 'test' },
            status: 'running',
            startTime: Date.now(),
          },
        ],
      ]);

      const observeEvent: AgentEvent<ObserveEventData> = {
        type: 'observe',
        data: {
          observation: 'Search completed successfully',
        },
      };

      handlers.onObserve?.(observeEvent);

      const updates = capturedUpdates[0];
      expect(updates.pendingToolsStack).toEqual([]);
    });

    it('CRITICAL: should update activeToolCalls to mark tool as completed', () => {
      // Setup: Tool is running
      const startTime = Date.now() - 1000;
      mockConversationState.pendingToolsStack = ['todowrite'];
      mockConversationState.activeToolCalls = new Map([
        [
          'todowrite',
          {
            name: 'todowrite',
            arguments: { tasks: [] },
            status: 'running',
            startTime,
          },
        ],
      ]);

      const observeEvent: AgentEvent<ObserveEventData> = {
        type: 'observe',
        data: {
          tool_name: 'todowrite',
          observation: 'Tasks updated successfully',
        },
      };

      handlers.onObserve?.(observeEvent);

      // CRITICAL ASSERTION: activeToolCalls should be updated
      const updates = capturedUpdates[0];

      // This is the fix - activeToolCalls must be updated
      expect(updates.activeToolCalls).toBeDefined();
      expect(updates.activeToolCalls!.has('todowrite')).toBe(true);

      const toolCall = updates.activeToolCalls!.get('todowrite');
      // Tool status should change from 'running' to 'completed'
      expect(toolCall?.status).toBe('completed');
      // Result should be stored
      expect(toolCall?.result).toBe('Tasks updated successfully');
      // Completion timestamp should be recorded
      expect(toolCall?.completedAt).toBeDefined();
      expect(typeof toolCall?.completedAt).toBe('number');
    });

    it('should handle observe event without tool_name in data', () => {
      // Setup: Tool is running
      mockConversationState.pendingToolsStack = ['unknown_tool'];
      mockConversationState.activeToolCalls = new Map([
        [
          'unknown_tool',
          {
            name: 'unknown_tool',
            arguments: {},
            status: 'running',
            startTime: Date.now(),
          },
        ],
      ]);

      const observeEvent: AgentEvent<ObserveEventData> = {
        type: 'observe',
        data: {
          // No tool_name provided
          observation: 'Tool completed',
        },
      };

      // Should NOT throw
      expect(() => handlers.onObserve?.(observeEvent)).not.toThrow();

      // Should still pop from stack
      const updates = capturedUpdates[0];
      expect(updates.pendingToolsStack).toEqual([]);
    });

    it('should handle multiple concurrent tool calls', () => {
      // Setup: Multiple tools running
      const startTime = Date.now() - 500;
      mockConversationState.pendingToolsStack = ['tool_a', 'tool_b'];
      mockConversationState.activeToolCalls = new Map([
        [
          'tool_a',
          {
            name: 'tool_a',
            arguments: {},
            status: 'running',
            startTime,
          },
        ],
        [
          'tool_b',
          {
            name: 'tool_b',
            arguments: {},
            status: 'running',
            startTime: startTime + 100,
          },
        ],
      ]);

      // First tool completes
      const observeEvent1: AgentEvent<ObserveEventData> = {
        type: 'observe',
        data: {
          tool_name: 'tool_b',
          observation: 'Tool B completed',
        },
      };

      handlers.onObserve?.(observeEvent1);

      const updates = capturedUpdates[0];

      // Stack should have tool_a left
      expect(updates.pendingToolsStack).toEqual(['tool_a']);

      // tool_b should be marked completed, tool_a still running
      expect(updates.activeToolCalls!.get('tool_b')?.status).toBe('completed');
      expect(updates.activeToolCalls!.get('tool_a')?.status).toBe('running');
    });
  });

  describe('Complete flow: act -> observe -> complete', () => {
    it('should correctly track tool visibility throughout full cycle', () => {
      // 1. Act: Tool starts
      const actEvent: AgentEvent<ActEventData> = {
        type: 'act',
        data: {
          tool_name: 'terminal',
          tool_input: { command: 'ls -la' },
          step_number: 1,
        },
      };

      handlers.onAct?.(actEvent);

      expect(capturedUpdates.length).toBeGreaterThan(0);
      let updates = capturedUpdates[0];

      expect(updates.activeToolCalls!.get('terminal')?.status).toBe('running');
      expect(updates.pendingToolsStack).toEqual(['terminal']);

      // Update mock state for next event
      mockConversationState.activeToolCalls = updates.activeToolCalls!;
      mockConversationState.pendingToolsStack = updates.pendingToolsStack as string[];

      // 2. Observe: Tool completes
      const observeEvent: AgentEvent<ObserveEventData> = {
        type: 'observe',
        data: {
          tool_name: 'terminal',
          observation: 'Command executed',
        },
      };

      handlers.onObserve?.(observeEvent);

      expect(capturedUpdates.length).toBeGreaterThan(1);
      updates = capturedUpdates[1];

      // CRITICAL: Tool should be marked completed
      expect(updates.activeToolCalls!.get('terminal')?.status).toBe('completed');
      expect(updates.pendingToolsStack).toEqual([]);
    });
  });
});

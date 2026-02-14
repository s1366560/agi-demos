/**
 * memstack-agent-ui - useStreaming Hook
 *
 * Hook for streaming state during agent execution.
 * Provides access to streaming content, thoughts, and tool calls.
 *
 * @packageDocumentation
 */

import { useMemo } from 'react';

import type {
  ConversationState,
  StreamStatus,
} from '@memstack-agent-ui/core';

/**
 * useStreaming options
 */
export interface UseStreamingOptions {
  /** Conversation ID to get streaming state for */
  conversationId: string;

  /** Whether to include assistant content (default: true) */
  includeAssistantContent?: boolean;

  /** Whether to include thought content (default: true) */
  includeThoughtContent?: boolean;

  /** Whether to include tool calls (default: true) */
  includeToolCalls?: boolean;
}

/**
 * useStreaming return value
 */
export interface UseStreamingReturn {
  /** Current streaming status */
  streamStatus: StreamStatus;

  /** Whether conversation is currently streaming */
  isStreaming: boolean;

  /** Streaming assistant content (accumulated during text_delta events) */
  streamingAssistantContent: string;

  /** Complete thought content (finalized after thought events) */
  currentThought: string;

  /** Streaming thought content (during thought_delta events) */
  streamingThought: string;

  /** Whether thought is currently streaming */
  isThinkingStreaming: boolean;

  /** Active tool calls by ID */
  activeToolCalls: ConversationState['activeToolCalls'];

  /** Pending tools stack (tool names in execution order) */
  pendingToolsStack: string[];
}

/**
 * useStreaming hook
 *
 * Provides access to streaming state with memoized selectors.
 * Optimized to prevent unnecessary re-renders.
 *
 * @param options - Hook options
 * @returns Hook return value
 *
 * @example
 * ```typescript
 * function StreamingContent({ conversationId }) {
 *   const {
 *     streamingAssistantContent,
 *     streamingThought,
 *     isStreaming,
 *     activeToolCalls,
 *   } = useStreaming({
 *     conversationId,
 *   });
 *
 *   return (
 *     <div>
 *       {isStreaming && <Spinner />}
 *       {streamingThought && <ThinkingBubble content={streamingThought} />}
 *       {streamingAssistantContent && <MarkdownContent content={streamingAssistantContent} />}
 *       {activeToolCalls.size > 0 && <ToolCalls tools={activeToolCalls} />}
 *     </div>
 *   );
 * }
 * ```
 */
export function useStreaming(
  options: UseStreamingOptions
): UseStreamingReturn {
  const { conversationId } = options;

  // TODO: Integrate with actual state management
  const state: ConversationState = {
    // Timeline
    timeline: [],
    hasEarlier: false,
    earliestTimeUs: null,
    earliestCounter: null,

    // Streaming
    isStreaming: false,
    streamStatus: 'idle' as StreamStatus,
    streamingAssistantContent: '',
    error: null,

    // Agent execution
    agentState: 'idle',
    currentThought: '',
    streamingThought: '',
    isThinkingStreaming: false,
    activeToolCalls: new Map(),
    pendingToolsStack: [],

    // Plan mode
    isPlanMode: false,

    // Tasks
    tasks: [],

    // HITL
    pendingClarification: null,
    pendingDecision: null,
    pendingEnvVarRequest: null,
    pendingPermission: null,
    doomLoopDetected: null,
    pendingHITLSummary: null,

    // Cost tracking
    costTracking: null,

    // Suggestions
    suggestions: [],

    // MCP App context
    appModelContext: null,
  };

  return useMemo(
    () => ({
      streamStatus: state.streamStatus,
      isStreaming: state.isStreaming,
      streamingAssistantContent: state.streamingAssistantContent,
      currentThought: state.currentThought,
      streamingThought: state.streamingThought,
      isThinkingStreaming: state.isThinkingStreaming,
      activeToolCalls: state.activeToolCalls,
      pendingToolsStack: state.pendingToolsStack,
    }),
    [conversationId, state.isStreaming, state.streamingAssistantContent, state.streamingThought]
  );
}

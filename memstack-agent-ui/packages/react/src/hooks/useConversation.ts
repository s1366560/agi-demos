/**
 * memstack-agent-ui - useConversation Hook
 *
 * Hook for accessing conversation state.
 * Provides timeline, messages, agent state, and streaming status.
 *
 * @packageDocumentation
 */

import { useMemo } from 'react';

import type {
  ConversationState,
  StreamStatus,
  HITLSummary,
} from '@memstack-agent-ui/core';
import type {
  Message,
  TimelineEvent,
  AgentState,
} from '@memstack-agent-ui/core';

/**
 * useConversation options
 */
export interface UseConversationOptions {
  /** Conversation ID to get state for */
  conversationId: string;

  /** Whether to include timeline in return (default: true) */
  includeTimeline?: boolean;

  /** Whether to include messages in return (default: true) */
  includeMessages?: boolean;

  /** Whether to include agent state in return (default: true) */
  includeAgentState?: boolean;
}

/**
 * useConversation return value
 */
export interface UseConversationReturn {
  /** Complete conversation state */
  state: ConversationState;

  /** Timeline events array */
  timeline: TimelineEvent[];

  /** Messages array (derived from timeline) */
  messages: Message[];

  /** Current agent execution state */
  agentState: AgentState;

  /** Current streaming status */
  streamStatus: StreamStatus;

  /** Whether conversation is currently streaming */
  isStreaming: boolean;

  /** Current thought content */
  currentThought: string;

  /** Streaming thought content */
  streamingThought: string;

  /** Whether thought is currently streaming */
  isThinkingStreaming: boolean;

  /** Pending HITL request summary */
  pendingHITLSummary: HITLSummary | null;

  /** Pending clarification request */
  pendingClarification: ConversationState['pendingClarification'];

  /** Pending decision request */
  pendingDecision: ConversationState['pendingDecision'];

  /** Pending environment variable request */
  pendingEnvVarRequest: ConversationState['pendingEnvVarRequest'];

  /** Pending permission request */
  pendingPermission: ConversationState['pendingPermission'];

  /** Active tool calls */
  activeToolCalls: ConversationState['activeToolCalls'];

  /** Pending tools stack */
  pendingToolsStack: string[];

  /** Agent tasks */
  tasks: ConversationState['tasks'];

  /** Cost tracking */
  costTracking: ConversationState['costTracking'] | null;

  /** Follow-up suggestions */
  suggestions: string[];

  /** Whether conversation is in plan mode */
  isPlanMode: boolean;

  /** Streaming assistant content */
  streamingAssistantContent: string;

  /** Error message if any */
  error: string | null;
}

/**
 * useConversation hook
 *
 * Provides access to conversation state with memoized selectors.
 * Returns individual state fields for convenience and re-render optimization.
 *
 * @param options - Hook options
 * @returns Hook return value
 *
 * @example
 * ```typescript
 * function Conversation({ conversationId }) {
 *   const { timeline, messages, agentState, isStreaming } = useConversation({
 *     conversationId,
 *   });
 *
 *   return (
 *     <div>
 *       <MessageList messages={messages} />
 *       <ExecutionTimeline timeline={timeline} />
 *       <StatusBar agentState={agentState} streaming={isStreaming} />
 *     </div>
 *   );
 * }
 * ```
 */
export function useConversation(
  options: UseConversationOptions
): UseConversationReturn {
  const { conversationId, includeTimeline = true, includeMessages = true, includeAgentState = true } = options;

  // TODO: Integrate with actual state management
  // For now, return default state
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
    agentState: 'idle' as AgentState,
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
      state,
      timeline: includeTimeline ? state.timeline : [],
      messages: includeMessages ? [] : [],
      agentState: includeAgentState ? state.agentState : ('idle' as AgentState),
      streamStatus: state.streamStatus,
      isStreaming: state.isStreaming,
      currentThought: state.currentThought,
      streamingThought: state.streamingThought,
      isThinkingStreaming: state.isThinkingStreaming,
      pendingHITLSummary: state.pendingHITLSummary,
      pendingClarification: state.pendingClarification,
      pendingDecision: state.pendingDecision,
      pendingEnvVarRequest: state.pendingEnvVarRequest,
      pendingPermission: state.pendingPermission,
      activeToolCalls: state.activeToolCalls,
      pendingToolsStack: state.pendingToolsStack,
      tasks: state.tasks,
      costTracking: state.costTracking,
      suggestions: state.suggestions,
      isPlanMode: state.isPlanMode,
      streamingAssistantContent: state.streamingAssistantContent,
      error: state.error,
    }),
    [conversationId, state]
  );
}

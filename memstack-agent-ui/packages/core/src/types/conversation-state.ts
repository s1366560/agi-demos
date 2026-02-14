/**
 * memstack-agent-ui - Conversation State Definitions
 *
 * Defines the per-conversation state interface and factory.
 * Based on MemStack's multi-conversation isolation pattern.
 *
 * @packageDocumentation
 */

import type { AgentState, ActiveToolCall, CostTracking } from './agent';
import type { TimelineEvent } from './conversation';
import type { PermissionAskedEventData, ClarificationAskedEventData, DecisionAskedEventData, EnvVarRequestedEventData, DoomLoopDetectedDataType } from './conversation';

/**
 * Stream connection status
 */
export type StreamStatus = 'idle' | 'connecting' | 'streaming' | 'error';

/**
 * HITL (Human-in-the-Loop) summary for display
 *
 * Derived from pending HITL requests for sidebar/notification display
 */
export interface HITLSummary {
  /** HITL request ID */
  requestId: string;

  /** Type of HITL request */
  type: 'clarification' | 'decision' | 'env_var' | 'permission';

  /** Short description for UI display */
  title: string;

  /** When this request was created */
  createdAt: string;

  /** Whether this request has expired */
  isExpired: boolean;
}

/**
 * Per-conversation state
 *
 * Complete state for a single conversation. Supports multi-conversation
 * isolation where each conversation maintains independent streaming, timeline,
 * and HITL state.
 */
export interface ConversationState {
  // ========================================================================
  // Timeline & Messages (Primary Data Source)
  // ========================================================================

  /** Raw event timeline from API and streaming */
  timeline: TimelineEvent[];

  /** Whether there are earlier messages to load (pagination) */
  hasEarlier: boolean;

  /** Earliest loaded event time (microseconds) for pagination */
  earliestTimeUs: number | null;

  /** Earliest loaded event counter for pagination */
  earliestCounter: number | null;

  // ========================================================================
  // Streaming State
  // ========================================================================

  /** Whether this conversation is actively streaming */
  isStreaming: boolean;

  /** Current stream connection status */
  streamStatus: StreamStatus;

  /** Streaming assistant response content (accumulated) */
  streamingAssistantContent: string;

  /** Error message if any error occurred */
  error: string | null;

  // ========================================================================
  // Agent Execution State
  // ========================================================================

  /** Current agent execution state from ReAct loop */
  agentState: AgentState;

  /** Current thought content (final/complete) */
  currentThought: string;

  /** Streaming thought content (in progress) */
  streamingThought: string;

  /** Whether thought is currently streaming */
  isThinkingStreaming: boolean;

  /** Active tool calls by ID */
  activeToolCalls: Map<string, ActiveToolCall>;

  /** Stack of pending tool names in execution order */
  pendingToolsStack: string[];

  // ========================================================================
  // Plan Mode State
  // ========================================================================

  /** Whether conversation is in Plan Mode (read-only analysis) */
  isPlanMode: boolean;

  // ========================================================================
  // Agent Tasks (Work Plans)
  // ========================================================================

  /** Agent-managed task checklist for this conversation */
  tasks: AgentTask[];

  // ========================================================================
  // HITL (Human-in-the-Loop) State
  // ========================================================================

  /** Pending clarification request */
  pendingClarification: ClarificationAskedEventData | null;

  /** Pending decision request */
  pendingDecision: DecisionAskedEventData | null;

  /** Pending environment variable request */
  pendingEnvVarRequest: EnvVarRequestedEventData | null;

  /** Pending permission request */
  pendingPermission: PermissionAskedEventData | null;

  /** Doom loop detection state */
  doomLoopDetected: DoomLoopDetectedDataType | null;

  /** Derived HITL summary for UI display */
  pendingHITLSummary: HITLSummary | null;

  // ========================================================================
  // Cost Tracking
  // ========================================================================

  /** Cost tracking state */
  costTracking: CostTracking | null;

  // ========================================================================
  // Suggestions
  // ========================================================================

  /** Follow-up suggestions from agent */
  suggestions: string[];

  // ========================================================================
  // MCP App Context (SEP-1865)
  // ========================================================================

  /** Context injected by MCP Apps via ui/update-model-context */
  appModelContext: Record<string, unknown> | null;
}

/**
 * Minimal interface for AgentTask (defined in agent.ts)
 * Redefined here to avoid circular dependency
 */
export interface AgentTask {
  id: string;
  title: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'cancelled';
  order: number;
  parentId?: string;
  childIds?: string[];
  createdAt: number;
  completedAt?: number;
}

/**
 * Create default conversation state
 *
 * Returns a fresh ConversationState instance with all fields
 * initialized to their default values.
 *
 * @returns Default conversation state
 */
export function createDefaultConversationState(): ConversationState {
  return {
    // Timeline
    timeline: [],
    hasEarlier: false,
    earliestTimeUs: null,
    earliestCounter: null,

    // Streaming
    isStreaming: false,
    streamStatus: 'idle',
    streamingAssistantContent: '',
    error: null,

    // Agent execution
    agentState: 'idle',
    currentThought: '',
    streamingThought: '',
    isThinkingStreaming: false,
    activeToolCalls: new Map(),
    pendingToolsStack: [],

    // Plan Mode
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
}

/**
 * Get HITL summary from conversation state
 *
 * Derives a display-friendly HITL summary from the first pending HITL request.
 *
 * @param state - Conversation state to extract HITL from
 * @returns HITL summary or null if no pending HITL
 */
export function getHITLSummaryFromState(state: ConversationState): HITLSummary | null {
  if (state.pendingClarification) {
    return {
      requestId: state.pendingClarification.request_id,
      type: 'clarification',
      title: 'Awaiting clarification',
      createdAt: new Date(state.pendingClarification.timestamp).toISOString(),
      isExpired: false,
    };
  }

  if (state.pendingDecision) {
    return {
      requestId: state.pendingDecision.request_id,
      type: 'decision',
      title: 'Awaiting decision',
      createdAt: new Date(state.pendingDecision.timestamp).toISOString(),
      isExpired: false,
    };
  }

  if (state.pendingEnvVarRequest) {
    return {
      requestId: state.pendingEnvVarRequest.request_id,
      type: 'env_var',
      title: 'Awaiting input',
      createdAt: new Date(state.pendingEnvVarRequest.timestamp).toISOString(),
      isExpired: false,
    };
  }

  if (state.pendingPermission) {
    return {
      requestId: state.pendingPermission.request_id,
      type: 'permission',
      title: `Permission: ${state.pendingPermission.tool_name}`,
      createdAt: new Date(state.pendingPermission.timestamp).toISOString(),
      isExpired: false,
    };
  }

  return null;
}

/**
 * Maximum concurrent streaming conversations
 *
 * Prevents resource exhaustion from too many active streams
 */
export const MAX_CONCURRENT_STREAMING_CONVERSATIONS = 5;

/**
 * Per-conversation state management types
 * 
 * This module defines the state structure for individual conversations,
 * enabling multi-conversation support where each conversation maintains
 * its own independent streaming, timeline, and HITL state.
 * 
 * @packageDocumentation
 */

import type {
    TimelineEvent,
    WorkPlan,
    ExecutionPlan,
    ToolCall,
    ClarificationAskedEventData,
    DecisionAskedEventData,
    EnvVarRequestedEventData,
    PermissionAskedEventData,
    DoomLoopDetectedEventData,
} from './agent';
// Re-export CostUpdateEventData for consumers that need to map to CostTrackingState
export type { CostUpdateEventData } from './agent';

/**
 * Agent execution state for a conversation
 */
export type AgentState =
    | 'idle'
    | 'thinking'
    | 'acting'
    | 'observing'
    | 'awaiting_input'
    | 'retrying';

/**
 * Stream connection status
 */
export type StreamStatus =
    | 'idle'
    | 'connecting'
    | 'streaming'
    | 'error';

/**
 * HITL (Human-In-The-Loop) request type for UI display
 */
export type HITLType = 'clarification' | 'decision' | 'env_var' | 'permission';

/**
 * HITL request summary for conversation list display
 */
export interface HITLSummary {
    /** HITL request ID */
    requestId: string;
    /** Type of HITL request */
    type: HITLType;
    /** Short description for sidebar display */
    title: string;
    /** When the request was created */
    createdAt: string;
    /** Whether this request has expired */
    isExpired: boolean;
}

/**
 * Cost tracking state for a conversation
 */
export interface CostTrackingState {
    /** Total input tokens used */
    inputTokens: number;
    /** Total output tokens used */
    outputTokens: number;
    /** Total tokens used */
    totalTokens: number;
    /** Total cost in USD */
    costUsd: number;
    /** Model used */
    model: string;
    /** Last update timestamp */
    lastUpdated: string;
}

/**
 * Per-conversation state
 * 
 * This state is isolated per conversation, allowing users to have multiple
 * concurrent conversations with independent streaming states.
 */
export interface ConversationState {
    // ===== Timeline & Messages =====
    /** Primary data source - raw events from API and streaming */
    timeline: TimelineEvent[];
    /** Whether there are earlier messages to load */
    hasEarlier: boolean;
    /** Earliest loaded sequence number for pagination */
    earliestLoadedSequence: number | null;

    // ===== Streaming State =====
    /** Whether this conversation is actively streaming */
    isStreaming: boolean;
    /** Current stream connection status */
    streamStatus: StreamStatus;
    /** Streaming assistant response content */
    streamingAssistantContent: string;
    /** Error message if any */
    error: string | null;

    // ===== Agent Execution State =====
    /** Current agent execution state */
    agentState: AgentState;
    /** Current thought content (final) */
    currentThought: string;
    /** Streaming thought content (in progress) */
    streamingThought: string;
    /** Whether thought is currently streaming */
    isThinkingStreaming: boolean;
    /** Active tool calls (tool_name -> call info) */
    activeToolCalls: Map<string, ToolCall & {
        status: 'running' | 'success' | 'failed';
        startTime: number;
    }>;
    /** Stack of pending tool names */
    pendingToolsStack: string[];

    // ===== Plan State =====
    /** Current work plan */
    workPlan: WorkPlan | null;
    /** Whether in plan mode */
    isPlanMode: boolean;
    /** Execution plan for plan mode */
    executionPlan: ExecutionPlan | null;

    // ===== HITL (Human-In-The-Loop) State =====
    /** Pending clarification request */
    pendingClarification: ClarificationAskedEventData | null;
    /** Pending decision request */
    pendingDecision: DecisionAskedEventData | null;
    /** Pending environment variable request */
    pendingEnvVarRequest: EnvVarRequestedEventData | null;
    /** Pending permission request */
    pendingPermission: PermissionAskedEventData | null;
    /** Doom loop detection state */
    doomLoopDetected: DoomLoopDetectedEventData | null;
    /** Summary of pending HITL for sidebar display */
    pendingHITLSummary: HITLSummary | null;

    // ===== Cost Tracking =====
    /** Cost tracking state */
    costTracking: CostTrackingState | null;
}

/**
 * Create default conversation state
 */
export function createDefaultConversationState(): ConversationState {
    return {
        // Timeline
        timeline: [],
        hasEarlier: false,
        earliestLoadedSequence: null,

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

        // Plan
        workPlan: null,
        isPlanMode: false,
        executionPlan: null,

        // HITL
        pendingClarification: null,
        pendingDecision: null,
        pendingEnvVarRequest: null,
        pendingPermission: null,
        doomLoopDetected: null,
        pendingHITLSummary: null,

        // Cost tracking
        costTracking: null,
    };
}

/**
 * Maximum number of concurrent streaming conversations
 * This prevents resource exhaustion from too many active streams
 */
export const MAX_CONCURRENT_STREAMING_CONVERSATIONS = 5;

/**
 * Get HITL summary from conversation state
 */
export function getHITLSummaryFromState(state: ConversationState): HITLSummary | null {
    if (state.pendingClarification) {
        return {
            requestId: state.pendingClarification.request_id,
            type: 'clarification',
            title: 'Awaiting clarification',
            createdAt: new Date().toISOString(), // Would be from actual request
            isExpired: false,
        };
    }
    if (state.pendingDecision) {
        return {
            requestId: state.pendingDecision.request_id,
            type: 'decision',
            title: 'Awaiting decision',
            createdAt: new Date().toISOString(),
            isExpired: false,
        };
    }
    if (state.pendingEnvVarRequest) {
        return {
            requestId: state.pendingEnvVarRequest.request_id,
            type: 'env_var',
            title: 'Awaiting input',
            createdAt: new Date().toISOString(),
            isExpired: false,
        };
    }
    if (state.pendingPermission) {
        return {
            requestId: state.pendingPermission.request_id,
            type: 'permission',
            title: `Permission: ${state.pendingPermission.tool_name}`,
            createdAt: new Date().toISOString(),
            isExpired: false,
        };
    }
    return null;
}

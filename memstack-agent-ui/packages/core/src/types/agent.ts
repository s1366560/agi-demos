/**
 * memstack-agent-ui - Core Agent Type Definitions
 *
 * Defines agent execution state, tool calls, and related types.
 *
 * @packageDocumentation
 */

import type { EventType } from './events';

/**
 * Agent execution state machine
 *
 * Represents the current state of the agent in its ReAct loop:
 * - idle: Not processing
 * - thinking: Generating thought/reasoning
 * - preparing: Preparing tool execution
 * - acting: Executing a tool
 * - observing: Observing tool output
 * - awaiting_input: Waiting for HITL response
 * - retrying: Recovering from error
 */
export type AgentState =
  | 'idle'
  | 'thinking'
  | 'preparing'
  | 'acting'
  | 'observing'
  | 'awaiting_input'
  | 'retrying';

/**
 * Tool execution status
 *
 * Tracks the lifecycle of a single tool invocation
 */
export type ToolCallStatus =
  | 'preparing'   // Tool arguments being prepared
  | 'running'     // Tool is executing
  | 'success'     // Tool completed successfully
  | 'failed';      // Tool execution failed

/**
 * Tool call metadata
 *
 * Contains information about a tool execution attempt
 */
export interface ToolCall {
  /** Unique identifier for this call */
  id: string;

  /** Name of the tool being executed */
  toolName: string;

  /** Current execution status */
  status: ToolCallStatus;

  /** Timestamp when execution started */
  startTime: number;

  /** Timestamp when execution completed (undefined until done) */
  endTime?: number;

  /** Duration in milliseconds (undefined until done) */
  duration?: number;

  /** Tool input arguments */
  input?: Record<string, unknown>;

  /** Partial streamed arguments (for act_delta) */
  partialArguments?: string;

  /** Tool output/result (undefined until done) */
  output?: unknown;

  /** Error if execution failed */
  error?: string;

  /** Whether this tool call had an error */
  isError?: boolean;
}

/**
 * Active tool calls map value type
 *
 * Extends ToolCall with runtime tracking fields
 */
export interface ActiveToolCall extends ToolCall {
  /** Execution status */
  status: ToolCallStatus;
  /** When execution started */
  startTime: number;
  /** Partial arguments during streaming */
  partialArguments?: string;
}

/**
 * Agent task for work plan tracking
 *
 * Represents a task in a work plan created by the agent
 */
export interface AgentTask {
  /** Unique task identifier */
  id: string;

  /** Task title/description */
  title: string;

  /** Current task status */
  status: 'pending' | 'in_progress' | 'completed' | 'failed' | 'cancelled';

  /** Task ordering/precedence */
  order: number;

  /** Optional parent task ID for nested tasks */
  parentId?: string;

  /** Optional child task IDs */
  childIds?: string[];

  /** Timestamp when task was created */
  createdAt: number;

  /** Timestamp when task completed (undefined until done) */
  completedAt?: number;
}

/**
 * Cost tracking state
 *
 * Tracks token usage and estimated costs for a conversation
 */
export interface CostTracking {
  /** Total input tokens consumed */
  inputTokens: number;

  /** Total output tokens consumed */
  outputTokens: number;

  /** Total tokens across all models */
  totalTokens: number;

  /** Estimated cost in USD */
  costUsd: number;

  /** LLM model identifier */
  model: string;

  /** Timestamp of last cost update */
  lastUpdated: string;
}

/**
 * Doom loop detection state
 *
 * Tracks when the agent is stuck in a repetitive loop
 */
export interface DoomLoopDetected {
  /** Unique identifier for this loop detection */
  request_id: string;

  /** Number of repetitions detected */
  repetition_count: number;

  /** Number of distinct actions in the loop */
  distinct_actions: number;

  /** Window of time/actions considered */
  window_size: number;

  /** Human-readable description of the loop */
  description: string;

  /** Suggested intervention action */
  suggested_action: string;

  /** Whether this has been addressed */
  addressed: boolean;
}

/**
 * Doom loop intervention state
 *
 * Tracks when a loop was automatically interrupted
 */
export interface DoomLoopIntervened {
  /** request_id from the original detection */
  request_id: string;

  /** Action taken to interrupt */
  intervention_action: string;

  /** Result of the intervention */
  result: 'success' | 'failed';

  /** Additional context */
  context?: Record<string, unknown>;
}

/**
 * Error event data
 *
 * Detailed error information from agent execution
 */
export interface ErrorEventData {
  /** Error message */
  message: string;

  /** Error type/category */
  error_type?: string;

  /** Whether error is recoverable */
  recoverable: boolean;

  /** Suggested recovery action */
  suggested_action?: string;

  /** Additional error context */
  context?: Record<string, unknown>;
}

/**
 * Retry event data
 *
 * Information about a retry attempt after failure
 */
export interface RetryEventData {
  /** Number of retry attempts made */
  attempt_number: number;

  /** Maximum retry attempts allowed */
  max_attempts: number;

  /** Original error that triggered retry */
  original_error: string;

  /** Action being retried */
  retry_action: string;

  /** Delay before next retry (ms) */
  retry_delay_ms: number;
}

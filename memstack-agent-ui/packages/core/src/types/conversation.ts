/**
 * memstack-agent-ui - Conversation Type Definitions
 *
 * Defines conversation state, messages, and related types.
 *
 * @packageDocumentation
 */

import type { AgentState, ToolCall, ActiveToolCall, CostTracking, DoomLoopDetected, DoomLoopIntervened, ErrorEventData, RetryEventData } from './agent';
import type { EventType } from './events';

/**
 * Message role in the conversation
 */
export type MessageRole = 'user' | 'assistant' | 'system';

/**
 * Message type classification
 */
export type MessageType =
  | 'text'         // Regular text message
  | 'thought'       // Agent reasoning/thinking
  | 'tool_call'    // Tool invocation
  | 'tool_result'  // Tool execution result
  | 'error'        // Error message
  | 'work_plan';    // Work plan output

/**
 * Base message interface
 *
 * Represents a single message in the conversation timeline
 */
export interface Message {
  /** Unique message identifier */
  id: string;

  /** Conversation this message belongs to */
  conversation_id: string;

  /** Message role (user/assistant/system) */
  role: MessageRole;

  /** Message content */
  content: string;

  /** Message type for specialized rendering */
  message_type: MessageType;

  /** Timestamp when message was created */
  created_at: string;

  /** Optional metadata */
  metadata?: Record<string, unknown>;

  /** Associated tool call if applicable */
  tool_call?: ToolCall;

  /** Parent message ID for threading */
  parent_id?: string;
}

/**
 * Timeline event base interface
 *
 * All events in the conversation timeline extend this base
 */
export interface TimelineEventBase {
  /** Unique event identifier */
  id: string;

  /** Event type from EventType union */
  type: EventType;

  /** Event timestamp (Unix microseconds) */
  eventTimeUs: number;

  /** Event counter for ordering within same timestamp */
  eventCounter: number;

  /** Human-readable timestamp */
  timestamp: number;

  /** Optional event metadata */
  metadata?: Record<string, unknown>;
}

/**
 * User message event
 *
 * Emitted when user sends a message to the agent
 */
export interface UserMessageEvent extends TimelineEventBase {
  type: 'user_message';

  /** User message content */
  content: string;

  /** User role (always 'user') */
  role: 'user';

  /** Optional file attachments */
  fileMetadata?: FileMetadata[];

  /** Optional forced skill name */
  forcedSkillName?: string;
}

/**
 * File attachment metadata
 */
export interface FileMetadata {
  /** File name */
  name: string;

  /** File size in bytes */
  size: number;

  /** MIME type */
  type: string;

  /** File URL or path */
  url: string;

  /** File identifier */
  id: string;
}

/**
 * Assistant message event
 *
 * Emitted when agent sends a message response
 */
export interface AssistantMessageEvent extends TimelineEventBase {
  type: 'assistant_message';

  /** Assistant message content */
  content: string;

  /** Assistant role (always 'assistant') */
  role: 'assistant';
}

/**
 * Thought event
 *
 * Emitted when agent produces reasoning output
 */
export interface ThoughtEventData extends TimelineEventBase {
  type: 'thought';

  /** Complete thought content */
  content: string;
}

/**
 * Thought delta event
 *
 * Emitted incrementally during agent reasoning
 */
export interface ThoughtDeltaEventData extends TimelineEventBase {
  type: 'thought_delta';

  /** Incremental thought content delta */
  delta: string;
}

/**
 * Work plan event
 *
 * Emitted when agent creates a work plan
 */
export interface WorkPlanEventData extends TimelineEventBase {
  type: 'work_plan';

  /** Plan steps/outline */
  plan: {
    steps: Array<{
      description: string;
      tool_name?: string;
      order: number;
    }>;
  };

  /** Estimated complexity */
  complexity?: 'low' | 'medium' | 'high';
}

/**
 * Act event
 *
 * Emitted when agent executes a tool
 */
export interface ActEventData extends TimelineEventBase {
  type: 'act';

  /** Tool being executed */
  tool_name: string;

  /** Tool input arguments */
  input: Record<string, unknown>;

  /** Tool call ID */
  tool_call_id: string;
}

/**
 * Act delta event
 *
 * Emitted incrementally during tool argument streaming
 */
export interface ActDeltaEventData extends TimelineEventBase {
  type: 'act_delta';

  /** Tool name */
  tool_name: string;

  /** Partial arguments delta */
  partial_args: string;

  /** Tool call ID */
  tool_call_id: string;
}

/**
 * Observe event
 *
 * Emitted when agent observes tool output
 */
export interface ObserveEventData extends TimelineEventBase {
  type: 'observe';

  /** Tool call ID being observed */
  tool_call_id: string;

  /** Tool output/result */
  output: unknown;

  /** Whether tool execution succeeded */
  success: boolean;

  /** Error if failed */
  error?: string;
}

/**
 * Text start event
 *
 * Emitted when agent starts streaming text response
 */
export interface TextStartEventData extends TimelineEventBase {
  type: 'text_start';

  /** Text identifier */
  text_id: string;
}

/**
 * Text delta event
 *
 * Emitted incrementally during text streaming
 */
export interface TextDeltaEventData extends TimelineEventBase {
  type: 'text_delta';

  /** Text identifier */
  text_id: string;

  /** Incremental text delta */
  delta: string;
}

/**
 * Text end event
 *
 * Emitted when agent completes text streaming
 */
export interface TextEndEventData extends TimelineEventBase {
  type: 'text_end';

  /** Text identifier */
  text_id: string;

  /** Complete final text */
  content: string;
}

/**
 * Permission asked event
 *
 * Emitted when agent requires user permission
 */
export interface PermissionAskedEventData extends TimelineEventBase {
  type: 'permission_asked';

  /** Unique request ID */
  request_id: string;

  /** Tool requesting permission */
  tool_name: string;

  /** Action being requested */
  action: string;

  /** Risk level */
  risk_level: 'low' | 'medium' | 'high' | 'critical';

  /** Detailed description */
  details: Record<string, unknown>;

  /** Human-readable description */
  description?: string;

  /** Whether "remember this choice" is available */
  allow_remember?: boolean;

  /** Default action if timeout */
  default_action?: 'allow' | 'deny';
}

/**
 * Permission replied event
 *
 * Emitted when user responds to permission request
 */
export interface PermissionRepliedEventData extends TimelineEventBase {
  type: 'permission_replied';

  /** Request ID being responded to */
  request_id: string;

  /** Whether permission was granted */
  granted: boolean;

  /** Whether to remember this choice */
  remember?: boolean;
}

/**
 * Clarification asked event
 *
 * Emitted when agent needs more information
 */
export interface ClarificationAskedEventData extends TimelineEventBase {
  type: 'clarification_asked';

  /** Unique request ID */
  request_id: string;

  /** Question being asked */
  question: string;

  /** Clarification type */
  clarification_type: 'choice' | 'confirmation' | 'text_input' | 'multi_select';

  /** Available options (for choice/multi_select) */
  options?: string[];

  /** Whether custom input is allowed */
  allow_custom?: boolean;

  /** Optional context */
  context?: Record<string, unknown>;

  /** Default value if timeout */
  default_value?: string;
}

/**
 * Clarification answered event
 *
 * Emitted when user responds to clarification
 */
export interface ClarificationAnsweredEventData extends TimelineEventBase {
  type: 'clarification_answered';

  /** Request ID being responded to */
  request_id: string;

  /** User's answer (option ID or custom text) */
  answer: string;
}

/**
 * Decision asked event
 *
 * Emitted when agent needs user to make a decision
 */
export interface DecisionAskedEventData extends TimelineEventBase {
  type: 'decision_asked';

  /** Unique request ID */
  request_id: string;

  /** Question/decision prompt */
  question: string;

  /** Decision type */
  decision_type: 'single_choice' | 'multi_choice' | 'ranking';

  /** Available options */
  options: Array<{
    id: string;
    label: string;
    description?: string;
    recommended?: boolean;
  }>;

  /** Whether custom input is allowed */
  allow_custom?: boolean;

  /** Default option if timeout */
  default_option?: string;

  /** Maximum selections (for multi_choice/ranking) */
  max_selections?: number;
}

/**
 * Decision answered event
 *
 * Emitted when user responds to decision request
 */
export interface DecisionAnsweredEventData extends TimelineEventBase {
  type: 'decision_answered';

  /** Request ID being responded to */
  request_id: string;

  /** User's decision (option ID or custom text) */
  decision: string | string[];
}

/**
 * Environment variable requested event
 *
 * Emitted when tool needs environment variables
 */
export interface EnvVarRequestedEventData extends TimelineEventBase {
  type: 'env_var_requested';

  /** Unique request ID */
  request_id: string;

  /** Tool requesting env vars */
  tool_name: string;

  /** Fields to collect */
  fields: Array<{
    name: string;
    label: string;
    description?: string;
    required: boolean;
    secret?: boolean;
    default_value?: string;
    pattern?: string;
  }>;

  /** Message to display to user */
  message: string;

  /** Optional context */
  context?: Record<string, unknown>;

  /** Whether to save for future sessions */
  allow_save?: boolean;
}

/**
 * Environment variable provided event
 *
 * Emitted when user provides environment variables
 */
export interface EnvVarProvidedEventData extends TimelineEventBase {
  type: 'env_var_provided';

  /** Request ID being responded to */
  request_id: string;

  /** Provided variable values */
  values: Record<string, string>;

  /** Whether to save for future */
  save?: boolean;
}

/**
 * Complete event
 *
 * Emitted when agent completes a full execution cycle
 */
export interface CompleteEventData extends TimelineEventBase {
  type: 'complete';

  /** Conversation ID */
  conversation_id: string;

  /** Final message content */
  content: string;

  /** Total tokens used */
  total_tokens?: number;

  /** Total cost */
  total_cost?: number;

  /** Execution duration in ms */
  duration_ms?: number;
}

/**
 * Error event data
 */
export type ErrorEventDataType = ErrorEventData;

/**
 * Retry event data
 */
export type RetryEventDataType = RetryEventData;

/**
 * Doom loop detected data
 */
export type DoomLoopDetectedDataType = DoomLoopDetected;

/**
 * Doom loop intervened data
 */
export type DoomLoopIntervenedDataType = DoomLoopIntervened;

/**
 * Cost update event data
 *
 * Emitted when token usage changes
 */
export interface CostUpdateEventData extends TimelineEventBase {
  type: 'cost_update';

  /** Input tokens consumed */
  input_tokens: number;

  /** Output tokens consumed */
  output_tokens: number;

  /** Total tokens */
  total_tokens: number;

  /** Estimated cost in USD */
  cost_usd: number;

  /** LLM model used */
  model: string;
}

/**
 * Suggestions event data
 *
 * Emitted when agent provides follow-up suggestions
 */
export interface SuggestionsEventData extends TimelineEventBase {
  type: 'suggestions';

  /** Array of suggestion strings */
  suggestions: string[];
}

/**
 * Artifact created event data
 *
 * Emitted when agent creates an artifact (file, output, etc.)
 */
export interface ArtifactCreatedEventData extends TimelineEventBase {
  type: 'artifact_created';

  /** Artifact identifier */
  artifact_id: string;

  /** Artifact type */
  artifact_type: 'file' | 'output' | 'chart' | 'other';

  /** Artifact title/name */
  title: string;

  /** Initial artifact data */
  data?: unknown;
}

/**
 * Artifact ready event data
 *
 * Emitted when artifact is ready for download/view
 */
export interface ArtifactReadyEventData extends TimelineEventBase {
  type: 'artifact_ready';

  /** Artifact identifier */
  artifact_id: string;

  /** Download/view URL */
  url?: string;

  /** File size if applicable */
  size?: number;

  /** MIME type if applicable */
  mime_type?: string;
}

/**
 * Artifact error event data
 *
 * Emitted when artifact creation fails
 */
export interface ArtifactErrorEventData extends TimelineEventBase {
  type: 'artifact_error';

  /** Artifact identifier */
  artifact_id: string;

  /** Error message */
  error: string;

  /** Whether operation can be retried */
  retryable: boolean;
}

/**
 * Title generated event data
 *
 * Emitted when conversation title is auto-generated
 */
export interface TitleGeneratedEventData extends TimelineEventBase {
  type: 'title_generated';

  /** Generated title */
  title: string;

  /** Source of title generation */
  source: 'auto' | 'user';
}

/**
 * Union of all timeline event types
 */
export type TimelineEvent =
  | UserMessageEvent
  | AssistantMessageEvent
  | ThoughtEventData
  | ThoughtDeltaEventData
  | WorkPlanEventData
  | ActEventData
  | ActDeltaEventData
  | ObserveEventData
  | TextStartEventData
  | TextDeltaEventData
  | TextEndEventData
  | PermissionAskedEventData
  | PermissionRepliedEventData
  | ClarificationAskedEventData
  | ClarificationAnsweredEventData
  | DecisionAskedEventData
  | DecisionAnsweredEventData
  | EnvVarRequestedEventData
  | EnvVarProvidedEventData
  | CompleteEventData
  | ErrorEventDataType
  | RetryEventDataType
  | DoomLoopDetectedDataType
  | DoomLoopIntervenedDataType
  | CostUpdateEventData
  | SuggestionsEventData
  | ArtifactCreatedEventData
  | ArtifactReadyEventData
  | ArtifactErrorEventData
  | TitleGeneratedEventData;

/**
 * Type guard for timeline events
 *
 * Safely narrows event type based on event type
 */
export function isTimelineEvent(event: unknown): event is TimelineEvent {
  const e = event as Partial<TimelineEvent>;
  return (
    typeof e === 'object' &&
    e !== null &&
    typeof e.id === 'string' &&
    typeof e.type === 'string' &&
    typeof e.eventTimeUs === 'number'
  );
}

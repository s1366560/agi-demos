import type { PlanStep } from './tasks';
import type { TimelineEvent } from './timeline';
/**
 * Conversation status
 */
export type ConversationStatus = 'active' | 'archived' | 'deleted';

/**
 * Message role
 */
export type MessageRole = 'user' | 'assistant' | 'system';

/**
 * Message type (extended for multi-level thinking)
 */
export type MessageType = 'text' | 'thought' | 'tool_call' | 'tool_result' | 'error' | 'work_plan';

/**
 * Agent execution status (extended for multi-level thinking)
 */
export type ExecutionStatus =
  | 'thinking'
  | 'acting'
  | 'observing'
  | 'completed'
  | 'failed'
  | 'work_planning'
  | 'planning'
  | 'step_executing';

/**
 * Thought level for multi-level thinking
 */
export type ThoughtLevel = 'work' | 'task';

/**
 * Plan status
 */
export type PlanStatus = 'planning' | 'in_progress' | 'completed' | 'failed';

/**
 * Tool call information
 */
export interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
  result?: string | undefined;
}

/**
 * Tool result information
 */
export interface ToolResult {
  tool_name: string;
  result?: string | undefined;
  error?: string | undefined;
}

/**
 * Artifact reference (externalized payload)
 */
export interface ArtifactReference {
  object_key?: string | undefined;
  url: string;
  mime_type?: string | undefined;
  size_bytes?: number | undefined;
  source?: string | undefined;
}

export interface ExecutionTokenSummary {
  input: number;
  output: number;
  reasoning: number;
  cacheRead: number;
  cacheWrite: number;
  total: number;
}

export interface ExecutionTaskSummary {
  total: number;
  completed: number;
  remaining: number;
  pending: number;
  inProgress: number;
  failed: number;
  cancelled: number;
  other: number;
}

export interface ExecutionSummary {
  stepCount: number;
  artifactCount: number;
  callCount: number;
  totalCost: number;
  totalCostFormatted: string;
  totalTokens: ExecutionTokenSummary;
  tasks?: ExecutionTaskSummary | undefined;
}

/**
 * Message in a conversation
 */
export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  message_type: MessageType;
  tool_calls?: ToolCall[] | undefined;
  tool_results?: ToolResult[] | undefined;
  artifacts?: ArtifactReference[] | undefined;
  metadata?: Record<string, unknown> | undefined;
  created_at: string;
  traceUrl?: string | undefined; // Langfuse trace URL for observability
  version?: number | undefined;
  original_content?: string | undefined;
  edited_at?: string | undefined;
}

/**
 * Conversation entity
 */
export type ConversationMode =
  | 'single_agent'
  | 'multi_agent_shared'
  | 'multi_agent_isolated'
  | 'autonomous';

export interface Conversation {
  id: string;
  project_id: string;
  tenant_id: string;
  user_id: string;
  title: string;
  status: ConversationStatus;
  agent_config?: Record<string, unknown> | undefined;
  metadata?: Record<string, unknown> | undefined;
  message_count: number;
  created_at: string;
  updated_at?: string | undefined;
  summary?: string | null | undefined;
  parent_conversation_id?: string | null | undefined;
  branch_point_message_id?: string | null | undefined;
  conversation_mode?: ConversationMode | null | undefined;
}

/**
 * Paginated response for conversation listing
 */
export interface PaginatedConversationsResponse {
  items: Conversation[];
  total: number;
  has_more: boolean;
  offset: number;
  limit: number;
}

/**
 * Agent execution tracking
 */
export interface AgentExecution {
  id: string;
  conversation_id: string;
  message_id: string;
  status: ExecutionStatus;
  thought?: string | undefined;
  action?: string | undefined;
  observation?: string | undefined;
  tool_name?: string | undefined;
  tool_input?: Record<string, unknown> | undefined;
  tool_output?: string | undefined;
  metadata?: Record<string, unknown> | undefined;
  started_at: string;
  completed_at?: string | undefined;
}

/**
 * Create conversation request
 */
export interface CreateConversationRequest {
  project_id: string;
  title?: string | undefined;
  agent_config?: Record<string, unknown> | undefined;
}

/**
 * Create conversation response
 */
export type CreateConversationResponse = Conversation;

/**
 * Chat request
 */
export interface ChatRequest {
  conversation_id: string;
  message: string;
  project_id?: string | undefined;
  /** File metadata for files uploaded to sandbox */
  file_metadata?:
    | Array<{
        filename: string;
        sandbox_path: string;
        mime_type: string;
        size_bytes: number;
      }>
    | undefined;
  /** Force execution of a specific skill by name */
  forced_skill_name?: string | undefined;
  /** Context injected by MCP Apps via ui/update-model-context (SEP-1865) */
  app_model_context?: Record<string, unknown> | undefined;
  /** Base64 image data URLs captured from video frames for vision LLM */
  image_attachments?: string[] | undefined;
  /** Target agent ID for multi-agent routing */
  agent_id?: string | undefined;
}

/**
 * Tool information
 */
export interface ToolInfo {
  name: string;
  description: string;
}

/**
 * Tools list response
 */
export interface ToolsListResponse {
  tools: ToolInfo[];
}

/**
 * Conversation messages response (unified timeline format)
 */
export interface ConversationMessagesResponse {
  conversationId: string;
  timeline: TimelineEvent[];
  total: number;
  // Pagination metadata
  has_more: boolean;
  first_time_us: number | null;
  first_counter: number | null;
  last_time_us: number | null;
  last_counter: number | null;
}

/**
 * Agent execution with multi-level thinking details
 */
export interface AgentExecutionWithDetails {
  id: string;
  message_id: string;
  status: ExecutionStatus;
  started_at: string;
  completed_at?: string | undefined;
  thought?: string | undefined;
  action?: string | undefined;
  tool_name?: string | undefined;
  tool_input?: Record<string, unknown> | undefined;
  tool_output?: string | undefined;
  observation?: string | undefined;
  // Multi-level thinking fields
  work_level_thought?: string | undefined;
  task_level_thought?: string | undefined;
  // eslint-disable-next-line @typescript-eslint/no-deprecated
  plan_steps?: PlanStep[] | undefined;
  current_step_index?: number | undefined;
  workflow_pattern_id?: string | undefined;
  work_plan_id?: string | undefined;
  current_step?: number | undefined;
  metadata?: Record<string, unknown> | undefined;
}

/**
 * Execution history response
 */
export interface ExecutionHistoryResponse {
  conversation_id: string;
  executions: AgentExecutionWithDetails[];
  total: number;
}

/**
 * Execution statistics response
 */
export interface ExecutionStatsResponse {
  total_executions: number;
  completed_count: number;
  failed_count: number;
  average_duration_ms: number;
  tool_usage: Record<string, number>;
  status_distribution: Record<string, number>;
  timeline_data: Array<{
    time: string;
    count: number;
    completed: number;
    failed: number;
  }>;
}

/**
 * Tool execution record from database
 */
export interface ToolExecutionRecord {
  id: string;
  conversation_id: string;
  message_id: string;
  call_id: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
  tool_output?: string | null | undefined;
  status: 'running' | 'success' | 'failed';
  error?: string | null | undefined;
  step_number?: number | null | undefined;
  sequence_number: number;
  started_at: string;
  completed_at?: string | null | undefined;
  duration_ms?: number | null | undefined;
}

/**
 * Tool executions response from API
 */
export interface ToolExecutionsResponse {
  conversation_id: string;
  tool_executions: ToolExecutionRecord[];
  total: number;
}

/**
 * Display mode for assistant response
 */
export type DisplayMode = 'timeline' | 'simple-timeline' | 'direct';

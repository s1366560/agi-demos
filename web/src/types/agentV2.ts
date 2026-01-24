/**
 * Agent V2 Type Definitions
 *
 * Complete type definitions for the Agent Chat system based on backend API analysis.
 * Covers 31 SSE event types, conversation management, and execution tracking.
 */

// ============================================================================
// Core Domain Types
// ============================================================================

/**
 * Conversation status
 */
export type ConversationStatus = 'active' | 'archived' | 'deleted';

/**
 * Agent mode (Build/Plan/Explore)
 */
export type AgentMode = 'build' | 'plan' | 'explore';

/**
 * Message role
 */
export type MessageRole = 'user' | 'assistant' | 'system';

/**
 * Message type
 */
export type MessageType =
  | 'text'
  | 'thought'
  | 'tool_call'
  | 'tool_result'
  | 'error'
  | 'work_plan'
  | 'step_start'
  | 'step_end'
  | 'pattern_match';

/**
 * Thought level (multi-level thinking)
 */
export type ThoughtLevel = 'work' | 'task';

/**
 * Plan status
 */
export type PlanStatus = 'pending' | 'in_progress' | 'completed' | 'failed';

/**
 * Plan document status
 */
export type PlanDocumentStatus = 'draft' | 'reviewing' | 'approved' | 'archived';

/**
 * Tool execution status
 */
export type ToolExecutionStatus = 'running' | 'success' | 'failed' | 'timeout';

/**
 * Clarification type
 */
export type ClarificationType = 'scope' | 'approach' | 'prerequisite' | 'priority' | 'custom';

/**
 * Decision type
 */
export type DecisionType = 'branch' | 'method' | 'confirmation' | 'risk' | 'custom';

/**
 * Skill execution status
 */
export type SkillExecutionStatus = 'matched' | 'executing' | 'completed' | 'failed' | 'fallback';

/**
 * Streaming phase
 */
export type StreamingPhase = 'idle' | 'thinking' | 'planning' | 'executing' | 'responding';

// ============================================================================
// Conversation Types
// ============================================================================

/**
 * Conversation entity
 */
export interface Conversation {
  id: string;
  project_id: string;
  tenant_id: string;
  user_id: string;
  title: string;
  status: ConversationStatus;
  message_count: number;
  current_mode: AgentMode;
  current_plan_id: string | null;
  parent_conversation_id: string | null;
  created_at: string;
  updated_at: string | null;
}

/**
 * Create conversation request
 */
export interface CreateConversationRequest {
  project_id: string;
  title?: string;
  agent_config?: Record<string, unknown>;
}

/**
 * Update conversation title request
 */
export interface UpdateConversationTitleRequest {
  title: string;
}

// ============================================================================
// Message Types
// ============================================================================

/**
 * Message entity
 */
export interface Message {
  id: string;
  conversation_id: string;
  role: MessageRole;
  content: string;
  message_type: MessageType;
  tool_calls?: ToolCall[];
  tool_results?: ToolResult[];
  metadata?: Record<string, unknown>;
  created_at: string;
  thought_level?: ThoughtLevel;
  work_plan_ref?: string;
  task_step_index?: number | null;
}

/**
 * Tool call
 */
export interface ToolCall {
  name: string;
  arguments: Record<string, unknown>;
  call_id?: string;
}

/**
 * Tool result
 */
export interface ToolResult {
  tool_call_id: string;
  result: string;
  is_error: boolean;
  error_message?: string;
}

// ============================================================================
// Work Plan Types
// ============================================================================

/**
 * Work plan entity
 */
export interface WorkPlan {
  id: string;
  conversation_id: string;
  status: PlanStatus;
  steps: PlanStep[];
  current_step_index: number;
  workflow_pattern_id?: string;
  created_at: string;
  updated_at?: string;
}

/**
 * Plan step
 */
export interface PlanStep {
  step_number: number;
  description: string;
  thought_prompt: string;
  required_tools: string[];
  expected_output: string;
  dependencies: number[];
}

/**
 * Step status
 */
export interface StepStatus {
  step_number: number;
  status: 'pending' | 'running' | 'completed' | 'failed';
  started_at?: string;
  completed_at?: string;
  error?: string;
}

// ============================================================================
// Tool Execution Types
// ============================================================================

/**
 * Tool execution record
 */
export interface ToolExecution {
  id: string;
  tool_name: string;
  input: Record<string, unknown>;
  status: ToolExecutionStatus;
  result?: string;
  error?: string;
  start_time: string;
  end_time?: string;
  duration_ms?: number;
  step_number?: number;
  call_id?: string;
}

/**
 * Tool info
 */
export interface ToolInfo {
  name: string;
  description: string;
  parameters?: Record<string, unknown>;
}

// ============================================================================
// Thought Types (Multi-level thinking)
// ============================================================================

/**
 * Thought entry
 */
export interface Thought {
  id: string;
  content: string;
  level: ThoughtLevel;
  step_number?: number;
  timestamp: string;
}

// ============================================================================
// Timeline Types
// ============================================================================

/**
 * Timeline step for visualization
 */
export interface TimelineStep {
  stepNumber: number;
  description: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  thoughts: Thought[];
  toolExecutions: ToolExecution[];
  startTime?: string;
  endTime?: string;
  duration?: number;
}

// ============================================================================
// Human Interaction Types
// ============================================================================

/**
 * Clarification option
 */
export interface ClarificationOption {
  id: string;
  label: string;
  description: string;
  recommended?: boolean;
}

/**
 * Clarification request event data
 */
export interface ClarificationRequest {
  request_id: string;
  question: string;
  clarification_type: ClarificationType;
  options: ClarificationOption[];
  allow_custom: boolean;
  context?: Record<string, unknown>;
  timeout?: number;
}

/**
 * Decision option
 */
export interface DecisionOption {
  id: string;
  label: string;
  description: string;
  recommended?: boolean;
  estimated_time?: string;
  estimated_cost?: number;
  risks?: string[];
}

/**
 * Decision request event data
 */
export interface DecisionRequest {
  request_id: string;
  question: string;
  decision_type: DecisionType;
  options: DecisionOption[];
  allow_custom: boolean;
  default_option?: string;
  context?: Record<string, unknown>;
  timeout?: number;
}

/**
 * Permission request event data
 */
export interface PermissionRequest {
  request_id: string;
  permission: string;
  patterns: string[];
  metadata: Record<string, unknown>;
}

/**
 * Doom loop detection event data
 */
export interface DoomLoopDetection {
  tool: string;
  input: Record<string, unknown>;
  count: number;
  threshold: number;
}

/**
 * Doom loop intervention request
 */
export interface DoomLoopRequest {
  request_id: string;
  tool: string;
  input: Record<string, unknown>;
  count: number;
  suggested_actions: ('continue' | 'stop' | 'modify')[];
}

// ============================================================================
// Cost Tracking Types
// ============================================================================

/**
 * Token breakdown
 */
export interface TokenBreakdown {
  input: number;
  output: number;
  reasoning?: number;
  total: number;
}

/**
 * Cost update event data
 */
export interface CostUpdate {
  total_tokens: number;
  total_cost: number;
  token_breakdown: TokenBreakdown;
  timestamp: string;
}

/**
 * Step cost
 */
export interface StepCost {
  step_number: number;
  tokens: TokenBreakdown;
  cost: number;
  finish_reason: string;
}

// ============================================================================
// Skill System Types (L2 Layer)
// ============================================================================

/**
 * Skill match event data
 */
export interface SkillMatch {
  skill_id: string;
  skill_name: string;
  tools: string[];
  match_score: number;
  execution_mode: 'direct' | 'prompt';
}

/**
 * Skill tool execution
 */
export interface SkillToolExecution {
  tool_name: string;
  tool_input: Record<string, unknown>;
  status: 'running' | 'success' | 'failed';
  result?: string;
  error?: string;
  step_index: number;
  duration_ms?: number;
}

/**
 * Skill execution state
 */
export interface SkillExecution {
  skill_id: string;
  skill_name: string;
  execution_mode: 'direct' | 'prompt';
  match_score: number;
  status: SkillExecutionStatus;
  tools: string[];
  tool_executions: SkillToolExecution[];
  current_step: number;
  total_steps: number;
  summary?: string;
  error?: string;
  execution_time_ms?: number;
  started_at: string;
  completed_at?: string;
}

// ============================================================================
// Plan Mode Types
// ============================================================================

/**
 * Plan document entity
 */
export interface PlanDocument {
  id: string;
  conversation_id: string;
  title: string;
  content: string;
  status: PlanDocumentStatus;
  version: number;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/**
 * Plan mode status
 */
export interface PlanModeStatus {
  is_in_plan_mode: boolean;
  current_mode: AgentMode;
  current_plan_id: string | null;
  conversation_id: string;
  can_exit: boolean;
  plan?: PlanDocument;
}

/**
 * Enter plan mode request
 */
export interface EnterPlanModeRequest {
  conversation_id: string;
  title: string;
  description?: string;
}

/**
 * Exit plan mode request
 */
export interface ExitPlanModeRequest {
  conversation_id: string;
  plan_id: string;
  approved: boolean;
  summary?: string;
}

/**
 * Update plan request
 */
export interface UpdatePlanRequest {
  content: string;
}

// ============================================================================
// Execution History Types
// ============================================================================

/**
 * Agent execution with details
 */
export interface AgentExecutionWithDetails {
  id: string;
  conversation_id: string;
  message_id: string;
  status: string;
  steps_count: number;
  tools_used: string[];
  tokens_used: number;
  cost: number;
  started_at: string;
  completed_at?: string;
  duration_ms?: number;
}

/**
 * Execution history response
 */
export interface ExecutionHistoryResponse {
  executions: AgentExecutionWithDetails[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * Execution stats response
 */
export interface ExecutionStatsResponse {
  total_requests: number;
  total_tokens: number;
  total_cost: number;
  average_latency: number;
  tool_usage: Record<string, number>;
}

/**
 * Tool executions response
 */
export interface ToolExecutionsResponse {
  tool_executions: ToolExecutionRecord[];
  total: number;
}

/**
 * Tool execution record (from API)
 */
export interface ToolExecutionRecord {
  id: string;
  conversation_id: string;
  message_id?: string;
  tool_name: string;
  tool_input?: Record<string, unknown>;
  tool_output?: string;
  status: string;
  error?: string;
  started_at: string;
  completed_at?: string;
  duration_ms?: number;
  step_number?: number;
  call_id?: string;
}

// ============================================================================
// Chat Request Types
// ============================================================================

/**
 * Chat request
 */
export interface ChatRequest {
  conversation_id: string;
  message: string;
}

// ============================================================================
// SSE Event Types
// ============================================================================

/**
 * All SSE event types (31 total)
 */
export type SSEEventType =
  // Status events
  | 'start'
  | 'complete'
  | 'error'
  | 'status'
  // Text streaming
  | 'text_start'
  | 'text_delta'
  | 'text_end'
  // Thinking (multi-level)
  | 'thought'
  | 'thought_delta'
  // Work plan
  | 'work_plan'
  | 'step_start'
  | 'step_end'
  | 'step_finish'
  // Tool execution
  | 'act'
  | 'observe'
  // Message
  | 'message'
  // Human interactions
  | 'clarification_asked'
  | 'clarification_answered'
  | 'decision_asked'
  | 'decision_answered'
  | 'permission_asked'
  | 'permission_replied'
  | 'doom_loop_detected'
  | 'doom_loop_intervened'
  // Cost tracking
  | 'cost_update'
  // Skill system
  | 'skill_matched'
  | 'skill_execution_start'
  | 'skill_tool_start'
  | 'skill_tool_result'
  | 'skill_execution_complete'
  | 'skill_fallback'
  // Plan mode
  | 'plan_mode_enter'
  | 'plan_mode_exit'
  | 'plan_created'
  | 'plan_updated'
  | 'plan_status_changed'
  // Other
  | 'pattern_match'
  | 'retry'
  | 'compact_needed';

/**
 * Base SSE event structure
 */
export interface SSEEvent<T = unknown> {
  type: SSEEventType;
  data: T;
  timestamp?: number;
}

// ============================================================================
// SSE Event Data Types
// ============================================================================

/**
 * Start event data
 */
export interface StartEventData {
  conversation_id: string;
}

/**
 * Complete event data
 */
export interface CompleteEventData {
  content?: string;
  format?: 'text' | 'markdown' | 'code' | 'table';
  id?: string;
  created_at?: string;
}

/**
 * Error event data
 */
export interface ErrorEventData {
  message: string;
  code?: string;
  isReconnectable?: boolean;
}

/**
 * Status event data
 */
export interface StatusEventData {
  status: string;
}

/**
 * Text delta event data
 */
export interface TextDeltaEventData {
  delta: string;
}

/**
 * Text end event data
 */
export interface TextEndEventData {
  full_text?: string;
}

/**
 * Thought event data
 */
export interface ThoughtEventData {
  content: string;
  thought_level?: ThoughtLevel;
  step_index?: number;
}

/**
 * Thought delta event data
 */
export interface ThoughtDeltaEventData {
  delta: string;
  step_index?: number;
}

/**
 * Work plan event data
 */
export interface WorkPlanEventData {
  plan_id: string;
  conversation_id: string;
  status: PlanStatus;
  steps: PlanStep[];
  current_step: number;
  workflow_pattern_id?: string;
}

/**
 * Step start event data
 */
export interface StepStartEventData {
  step_index: number;
  step_number: number;
  description: string;
}

/**
 * Step end event data
 */
export interface StepEndEventData {
  step_index: number;
  step_number: number;
  success: boolean;
  current_step: number;
}

/**
 * Step finish event data
 */
export interface StepFinishEventData {
  tokens: TokenBreakdown;
  cost: number;
  finish_reason: string;
  step_number?: number;
}

/**
 * Act (tool call start) event data
 */
export interface ActEventData {
  tool_name: string;
  tool_input: Record<string, unknown>;
  call_id: string;
  status: 'running';
  step_number?: number;
}

/**
 * Observe (tool result) event data
 */
export interface ObserveEventData {
  tool_name: string;
  result?: string;
  observation?: string;
  status: 'completed' | 'failed';
  duration_ms?: number;
  call_id: string;
  step_number?: number;
}

/**
 * Clarification asked event data
 */
export interface ClarificationAskedEventData extends ClarificationRequest {}

/**
 * Clarification answered event data
 */
export interface ClarificationAnsweredEventData {
  request_id: string;
  answer: string;
}

/**
 * Decision asked event data
 */
export interface DecisionAskedEventData extends DecisionRequest {}

/**
 * Decision answered event data
 */
export interface DecisionAnsweredEventData {
  request_id: string;
  decision: string;
}

/**
 * Permission asked event data
 */
export interface PermissionAskedEventData extends PermissionRequest {}

/**
 * Permission replied event data
 */
export interface PermissionRepliedEventData {
  request_id: string;
  decision: 'allow' | 'deny';
}

/**
 * Doom loop detected event data
 */
export interface DoomLoopDetectedEventData extends DoomLoopDetection {
  request_id?: string;
}

/**
 * Doom loop intervened event data
 */
export interface DoomLoopIntervenedEventData {
  request_id: string;
  action: 'continue' | 'stop';
}

/**
 * Cost update event data
 */
export interface CostUpdateEventData extends CostUpdate {}

/**
 * Skill matched event data
 */
export interface SkillMatchedEventData extends SkillMatch {}

/**
 * Skill execution start event data
 */
export interface SkillExecutionStartEventData {
  skill_id: string;
  skill_name: string;
  tools: string[];
  total_steps: number;
}

/**
 * Skill tool start event data
 */
export interface SkillToolStartEventData {
  skill_id: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
  step_index: number;
}

/**
 * Skill tool result event data
 */
export interface SkillToolResultEventData {
  skill_id: string;
  tool_name: string;
  step_index: number;
  result?: string;
  error?: string;
  status: 'success' | 'failed';
  duration_ms?: number;
}

/**
 * Skill execution complete event data
 */
export interface SkillExecutionCompleteEventData {
  skill_id: string;
  skill_name: string;
  success: boolean;
  tool_results: Array<{ tool_name: string; result: string }>;
  execution_time_ms: number;
  summary?: string;
  error?: string;
}

/**
 * Skill fallback event data
 */
export interface SkillFallbackEventData {
  skill_name: string;
  reason: string;
  error?: string;
}

/**
 * Plan mode enter event data
 */
export interface PlanModeEnterEventData {
  conversation_id: string;
  plan_id: string;
  plan_title: string;
}

/**
 * Plan mode exit event data
 */
export interface PlanModeExitEventData {
  conversation_id: string;
  plan_id: string;
  plan_status: PlanDocumentStatus;
  approved: boolean;
}

/**
 * Plan created event data
 */
export interface PlanCreatedEventData {
  plan_id: string;
  title: string;
  conversation_id: string;
}

/**
 * Plan updated event data
 */
export interface PlanUpdatedEventData {
  plan_id: string;
  content: string;
  version: number;
}

/**
 * Plan status changed event data
 */
export interface PlanStatusChangedEventData {
  plan_id: string;
  old_status: PlanDocumentStatus;
  new_status: PlanDocumentStatus;
}

/**
 * Pattern match event data
 */
export interface PatternMatchEventData {
  pattern_id: string;
  pattern_name: string;
  confidence: number;
}

/**
 * Retry event data
 */
export interface RetryEventData {
  attempt: number;
  delay_ms: number;
  message: string;
}

/**
 * Message event data
 */
export interface MessageEventData {
  id?: string;
  role: MessageRole;
  content: string;
  created_at?: string;
  format?: 'text' | 'markdown' | 'code' | 'table';
}

// ============================================================================
// API Response Types
// ============================================================================

/**
 * Conversations list response
 */
export interface ConversationsListResponse {
  conversations: Conversation[];
  total: number;
}

/**
 * Conversation messages response
 */
export interface ConversationMessagesResponse {
  messages: Message[];
  total: number;
  has_more: boolean;
}

/**
 * Tools list response
 */
export interface ToolsListResponse {
  tools: ToolInfo[];
}

// ============================================================================
// Union type for all SSE event data
// ============================================================================

export type SSEEventData =
  | StartEventData
  | CompleteEventData
  | ErrorEventData
  | StatusEventData
  | TextDeltaEventData
  | TextEndEventData
  | ThoughtEventData
  | ThoughtDeltaEventData
  | WorkPlanEventData
  | StepStartEventData
  | StepEndEventData
  | StepFinishEventData
  | ActEventData
  | ObserveEventData
  | ClarificationAskedEventData
  | ClarificationAnsweredEventData
  | DecisionAskedEventData
  | DecisionAnsweredEventData
  | PermissionAskedEventData
  | PermissionRepliedEventData
  | DoomLoopDetectedEventData
  | DoomLoopIntervenedEventData
  | CostUpdateEventData
  | SkillMatchedEventData
  | SkillExecutionStartEventData
  | SkillToolStartEventData
  | SkillToolResultEventData
  | SkillExecutionCompleteEventData
  | SkillFallbackEventData
  | PlanModeEnterEventData
  | PlanModeExitEventData
  | PlanCreatedEventData
  | PlanUpdatedEventData
  | PlanStatusChangedEventData
  | PatternMatchEventData
  | RetryEventData
  | MessageEventData;

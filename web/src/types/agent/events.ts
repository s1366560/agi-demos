import type { DesktopStatus, TerminalStatus } from './config';
import type { MessageRole, ArtifactReference, ThoughtLevel, PlanStatus } from './core';
import type { AgentTask } from './tasks';
import type {
  ExecutionPlanStatus,
  ExecutionStepStatus,
  ReflectionAssessment,
  StepAdjustment,
} from './workflow';

export interface TaskListUpdatedEventData {
  conversation_id: string;
  tasks: AgentTask[];
}


export interface TaskUpdatedEventData {
  conversation_id: string;
  task_id: string;
  status: string;
  content?: string | undefined;
}


export interface TaskStartEventData {
  task_id: string;
  content: string;
  order_index: number;
  total_tasks: number;
}


export interface TaskCompleteEventData {
  task_id: string;
  status: string;
  order_index: number;
  total_tasks: number;
}


export interface ExecutionPathDecidedEventData {
  route_id?: string | undefined;
  trace_id?: string | undefined;
  path: string;
  confidence: number;
  reason: string;
  target?: string | null | undefined;
  metadata?: Record<string, unknown> | undefined;
}


export interface SelectionTraceStageData {
  stage: string;
  before_count: number;
  after_count: number;
  removed_count: number;
  duration_ms: number;
  explain?: Record<string, unknown> | undefined;
}


export interface SelectionTraceEventData {
  route_id?: string | undefined;
  trace_id?: string | undefined;
  initial_count: number;
  final_count: number;
  removed_total: number;
  domain_lane?: string | null | undefined;
  tool_budget?: number | undefined;
  budget_exceeded_stages?: string[] | undefined;
  stages: SelectionTraceStageData[];
}


export interface PolicyFilteredEventData {
  route_id?: string | undefined;
  trace_id?: string | undefined;
  removed_total: number;
  stage_count: number;
  domain_lane?: string | null | undefined;
  tool_budget?: number | undefined;
  budget_exceeded_stages?: string[] | undefined;
}


export type ToolsetRefreshStatus = 'success' | 'failed' | 'skipped' | 'deferred' | 'not_applicable';


export interface ToolsetChangedEventData {
  source: string;
  tenant_id?: string | undefined;
  project_id?: string | undefined;
  action?: string | undefined;
  plugin_name?: string | null | undefined;
  trace_id?: string | undefined;
  mutation_fingerprint?: string | null | undefined;
  reload_plan?: Record<string, unknown> | undefined;
  details?: Record<string, unknown> | undefined;
  lifecycle?: Record<string, unknown> | undefined;
  refresh_source?: string | undefined;
  refresh_status?: ToolsetRefreshStatus | undefined;
  refreshed_tool_count?: number | undefined;
}


export type ExecutionNarrativeStage = 'routing' | 'selection' | 'policy' | 'toolset';


export interface ExecutionNarrativeEntry {
  id: string;
  stage: ExecutionNarrativeStage;
  summary: string;
  timestamp: number;
  trace_id?: string | undefined;
  route_id?: string | undefined;
  domain_lane?: string | null | undefined;
  metadata?: Record<string, unknown> | undefined;
}


/**
 * SSE event types from agent (extended for multi-level thinking and typewriter effect)
 */
export type AgentEventType =
  | 'message' // User/assistant message
  | 'thought' // Agent's reasoning (work or task level)
  | 'thought_delta' // Incremental thought update
  | 'work_plan' // Work-level plan generated
  | 'pattern_match' // Pattern matched from workflow memory (T079)
  | 'act' // Tool execution (tool name and input)
  | 'act_delta' // Tool call streaming delta (partial arguments)
  | 'observe' // Tool results
  | 'tool_start' // Tool execution started
  | 'tool_result' // Tool execution result
  | 'text_start' // Text streaming started (typewriter effect)
  | 'text_delta' // Text chunk (typewriter effect)
  | 'text_end' // Text streaming ended (typewriter effect)
  | 'clarification_asked' // Agent asks for clarification
  | 'clarification_answered' // User responds to clarification
  | 'decision_asked' // Agent asks for decision
  | 'decision_answered' // User makes decision
  | 'doom_loop_detected' // Doom loop detected
  | 'doom_loop_intervened' // Doom loop intervention
  // Environment variable events
  | 'env_var_requested' // Agent requests environment variable from user
  | 'env_var_provided' // User provides environment variable
  // Skill execution events (L2 layer)
  | 'skill_matched' // Skill matched for execution
  | 'skill_execution_start' // Skill execution started
  | 'skill_tool_start' // Skill tool execution started
  | 'skill_tool_result' // Skill tool execution result
  | 'skill_execution_complete' // Skill execution completed
  | 'skill_fallback' // Skill execution fallback to LLM
  // Context management events
  | 'context_compressed' // Context window compression occurred
  | 'context_status' // Context health status update
  | 'context_summary_generated' // Summary cache saved (internal)
  // Plan mode events (deprecated - plan mode system removed, kept for SSE compatibility)
  | 'plan_mode_enter'
  | 'plan_mode_exit'
  | 'plan_created'
  | 'plan_updated'
  | 'plan_status_changed'
  | 'plan_execution_start'
  | 'plan_step_complete'
  | 'plan_execution_complete'
  | 'reflection_complete'
  | 'adjustment_applied'
  // Permission events
  | 'permission_asked' // Permission asked
  | 'permission_replied' // Permission replied
  // Sandbox events (desktop and terminal)
  | 'sandbox_created' // Sandbox container created
  | 'sandbox_terminated' // Sandbox container terminated
  | 'sandbox_status' // Sandbox status update
  | 'desktop_started' // Remote desktop started
  | 'desktop_stopped' // Remote desktop stopped
  | 'desktop_status' // Remote desktop status update
  | 'terminal_started' // Web terminal started
  | 'terminal_stopped' // Web terminal stopped
  | 'terminal_status' // Web terminal status update
  | 'screenshot_update' // Desktop screenshot update
  // Artifact events
  | 'artifact_created' // Artifact (file/image/video) created
  | 'artifact_ready' // Artifact ready for download
  | 'artifact_error' // Artifact processing error
  | 'artifacts_batch' // Batch of artifacts
  // Suggestion events
  | 'suggestions' // Follow-up suggestions from agent
  // Artifact lifecycle events
  | 'artifact_open' // Agent opens content in canvas
  | 'artifact_update' // Agent updates canvas content
  | 'artifact_close' // Agent closes canvas tab
  // Plan step events
  | 'plan_step_ready' // Plan step ready for execution
  | 'plan_step_skipped' // Plan step skipped
  | 'plan_snapshot_created' // Plan snapshot created
  | 'plan_rollback' // Plan rolled back to snapshot
  // Plan Mode change event
  | 'plan_mode_changed' // Plan Mode toggled on/off
  // Plan Mode HITL events (legacy)
  | 'plan_suggested' // Agent suggests Plan Mode
  | 'plan_exploration_started' // Exploration phase started
  | 'plan_exploration_completed' // Exploration phase completed
  | 'plan_draft_created' // Plan draft generated
  | 'plan_approved' // User approved plan
  | 'plan_rejected' // User rejected plan
  | 'plan_cancelled' // Plan cancelled
  | 'workplan_created' // WorkPlan decomposed from plan
  | 'workplan_step_started' // WorkPlan step execution started
  | 'workplan_step_completed' // WorkPlan step completed
  | 'workplan_step_failed' // WorkPlan step failed
  | 'workplan_completed' // All WorkPlan steps completed
  | 'workplan_failed' // WorkPlan execution failed
  // System events
  | 'start' // Stream started
  | 'status' // Status update
  | 'cost_update' // Cost tracking update
  | 'retry' // Retry attempt
  | 'compact_needed' // Context compaction needed
  | 'complete' // Final assistant response
  | 'title_generated' // Conversation title generated
  | 'error' // Error messages
  // SubAgent events (L3 layer)
  | 'subagent_routed' // SubAgent routing decision
  | 'subagent_started' // SubAgent execution started
  | 'subagent_completed' // SubAgent execution completed
  | 'subagent_failed' // SubAgent execution failed
  | 'subagent_run_started' // Sessionized SubAgent run started
  | 'subagent_run_completed' // Sessionized SubAgent run completed
  | 'subagent_run_failed' // Sessionized SubAgent run failed
  | 'subagent_session_spawned' // Sessionized SubAgent run spawned
  | 'subagent_session_message_sent' // Follow-up task sent to session lineage
  | 'subagent_announce_retry' // Session announce retry event
  | 'subagent_announce_giveup' // Session announce gave up after retries
  | 'subagent_killed' // Sessionized SubAgent run cancelled
  | 'subagent_steered' // Steering instruction attached to a run
  | 'subagent_queued' // SubAgent queued waiting for lane semaphore
  | 'subagent_depth_limited' // SubAgent delegation depth exceeded
  | 'subagent_session_update' // SubAgent progress/status update
  | 'parallel_started' // Parallel SubAgent group started
  | 'parallel_completed' // Parallel SubAgent group completed
  | 'chain_started' // Chain execution started
  | 'chain_step_started' // Chain step started
  | 'chain_step_completed' // Chain step completed
  | 'chain_completed' // Chain execution completed
  | 'background_launched' // Background SubAgent launched
  // Router and tool selection diagnostics
  | 'execution_path_decided' // Router path decision with metadata
  | 'selection_trace' // Tool selection stage-by-stage trace
  | 'policy_filtered' // Tool policy filtering summary
  | 'toolset_changed' // Tool inventory changed after self-modification
  // Task list events (DB-persistent task tracking)
  | 'task_list_updated' // Full task list replacement
  | 'task_updated' // Single task status change
  // Task timeline events (plan execution tracking)
  | 'task_start' // Agent started working on a task
  | 'task_complete' // Agent finished a task
  // MCP App events
  | 'mcp_app_result' // MCP tool with UI returned result + HTML
  | 'mcp_app_registered' // New MCP App auto-detected
  // Memory events (auto-recall / auto-capture)
  | 'memory_recalled' // Memories recalled for context injection
  | 'memory_captured' // New memories captured from conversation
  | 'canvas_updated' // Canvas block created/updated/deleted by agent (A2UI)
  | 'a2ui_action_asked'; // A2UI interactive surface waiting for user action (HITL)

/**
 * Base SSE event from agent
 */
export interface AgentEvent<T = Record<string, unknown>> {
  type: AgentEventType;
  data: T;
}


/**
 * Message event data
 */
export interface MessageEventData {
  id?: string | undefined;
  role: MessageRole;
  content: string;
  created_at?: string | undefined;
  artifacts?: ArtifactReference[] | undefined;
}


/**
 * Thought event data (extended with thought level)
 */
export interface ThoughtEventData {
  thought: string;
  thought_level?: ThoughtLevel | undefined;
  step_number?: number | undefined;
}


/**
 * Work plan event data
 */
export interface WorkPlanEventData {
  plan_id: string;
  conversation_id: string;
  steps: Array<{
    step_number: number;
    description: string;
    expected_output: string;
  }>;
  total_steps: number;
  current_step: number;
  status: PlanStatus;
  workflow_pattern_id?: string | undefined;
  thought_level: ThoughtLevel;
}


/**
 * Act event data (tool execution)
 */
export interface ActEventData {
  tool_name: string;
  tool_input: Record<string, unknown>;
  step_number?: number | undefined;
  execution_id?: string | undefined; // Legacy alias
  tool_execution_id?: string | undefined; // Backend field name for act/observe matching
}


/**
 * Act delta event data (streaming tool call arguments)
 */
export interface ActDeltaEventData {
  tool_name: string;
  call_id?: string | undefined;
  arguments_fragment: string;
  accumulated_arguments: string;
  status: 'preparing';
}


/**
 * Observe event data (tool result)
 */
export interface ObserveEventData {
  observation?: string | undefined; // Legacy field for observation text
  tool_name?: string | undefined; // New: tool name
  execution_id?: string | undefined; // Legacy alias
  tool_execution_id?: string | undefined; // Backend field name for act/observe matching
  error?: string | undefined; // Error message if tool execution failed
  result?: unknown;
}


/**
 * Complete event data (final response)
 */
export interface CompleteEventData {
  content: string;
  trace_url?: string | undefined;
  id?: string | undefined;
  message_id?: string | undefined;
  assistant_message_id?: string | undefined;
  artifacts?: ArtifactReference[] | undefined;
}


/**
 * Error event data
 */
export interface ErrorEventData {
  message: string;
  isReconnectable?: boolean | undefined;
  code?: string | undefined;
}


/**
 * Retry event data (sent when LLM is retrying after a transient error)
 */
export interface RetryEventData {
  attempt: number;
  delay_ms: number;
  message: string;
}


/**
 * Title generated event data
 */
export interface TitleGeneratedEventData {
  conversation_id: string;
  title: string;
  generated_at: string;
  message_id?: string | undefined;
  generated_by?: string | undefined;
}


/**
 * Clarification type
 */
export type ClarificationType = 'scope' | 'approach' | 'prerequisite' | 'priority' | 'custom';


/**
 * Clarification option
 */
export interface ClarificationOption {
  id: string;
  label: string;
  description?: string | undefined;
  recommended?: boolean | undefined;
}


/**
 * Clarification asked event data
 */
export interface ClarificationAskedEventData {
  request_id: string;
  question: string;
  clarification_type: ClarificationType;
  options: ClarificationOption[];
  allow_custom: boolean;
  context: Record<string, unknown>;
}


/**
 * Clarification answered event data
 */
export interface ClarificationAnsweredEventData {
  request_id: string;
  answer: string;
}


/**
 * Decision type
 */
export type DecisionType = 'branch' | 'method' | 'confirmation' | 'risk' | 'custom';


/**
 * Decision option
 */
export interface DecisionOption {
  id: string;
  label: string;
  description?: string | undefined;
  recommended?: boolean | undefined;
  estimated_time?: string | undefined;
  estimated_cost?: string | undefined;
  risks?: string[] | undefined;
}


/**
 * Decision asked event data
 */
export interface DecisionAskedEventData {
  request_id: string;
  question: string;
  decision_type: DecisionType;
  options: DecisionOption[];
  allow_custom: boolean;
  context: Record<string, unknown>;
  default_option?: string | undefined;
  selection_mode?: 'single' | 'multiple' | undefined;
  max_selections?: number | undefined;
}


/**
 * Decision answered event data
 */
export interface DecisionAnsweredEventData {
  request_id: string;
  decision: string;
}


/**
 * Environment variable input type
 */
export type EnvVarInputType = 'text' | 'password' | 'textarea';


/**
 * Environment variable field definition
 */
export interface EnvVarField {
  name: string;
  label: string;
  description?: string | undefined;
  required: boolean;
  input_type: EnvVarInputType;
  default_value?: string | undefined;
  placeholder?: string | undefined;
}


/**
 * Environment variable requested event data
 */
export interface EnvVarRequestedEventData {
  request_id: string;
  tool_name: string;
  fields: EnvVarField[];
  message?: string | undefined;
  context?: Record<string, unknown> | undefined;
}


/**
 * Environment variable provided event data
 */
export interface EnvVarProvidedEventData {
  request_id: string;
  tool_name: string;
  saved_variables: string[];
}


/**
 * Doom loop detected event data
 */
export interface DoomLoopDetectedEventData {
  request_id: string;
  tool_name: string;
  call_count: number;
  last_calls: Array<{
    tool: string;
    input: Record<string, unknown>;
    timestamp: string;
  }>;
  context?: Record<string, unknown> | undefined;
}


/**
 * Doom loop intervened event data
 */
export interface DoomLoopIntervenedEventData {
  request_id: string;
  action: string;
}


/**
 * Permission asked event data
 */
export interface PermissionAskedEventData {
  request_id: string;
  tool_name: string;
  permission_type: 'allow' | 'deny' | 'ask';
  description: string;
  risk_level?: 'low' | 'medium' | 'high' | undefined;
  context?: Record<string, unknown> | undefined;
}


/**
 * Permission replied event data
 */
export interface PermissionRepliedEventData {
  request_id: string;
  tool_name: string;
  granted: boolean;
  remember?: boolean | undefined;
}


/**
 * Cost update event data
 */
export interface CostUpdateEventData {
  conversation_id: string;
  message_id?: string | undefined;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  model: string;
  cumulative_tokens?: number | undefined;
  cumulative_cost_usd?: number | undefined;
}


/**
 * Plan status changed event data
 */
export interface PlanStatusChangedEventData {
  plan_id: string;
  old_status: string;
  new_status: string;
  reason?: string | undefined;
}


/**
 * Plan step ready event data
 */
export interface PlanStepReadyEventData {
  plan_id: string;
  step_id: string;
  step_number: number;
  description: string;
}


/**
 * Plan step complete event data
 */
export interface PlanStepCompleteEventData {
  plan_id: string;
  step_id: string;
  step_number: number;
  status: 'completed' | 'failed' | 'skipped';
  result?: unknown;
  error?: string | undefined;
}


/**
 * Plan step skipped event data
 */
export interface PlanStepSkippedEventData {
  plan_id: string;
  step_id: string;
  step_number: number;
  reason: string;
}


/**
 * Plan snapshot created event data
 */
export interface PlanSnapshotCreatedEventData {
  plan_id: string;
  snapshot_id: string;
  step_number: number;
  reason: string;
}


/**
 * Plan rollback event data
 */
export interface PlanRollbackEventData {
  plan_id: string;
  snapshot_id: string;
  from_step: number;
  to_step: number;
  reason: string;
}


/**
 * Adjustment applied event data
 */
export interface AdjustmentAppliedEventData {
  plan_id: string;
  adjustment_type: string;
  description: string;
  affected_steps: number[];
}


/**
 * Sandbox event data (unified for all sandbox events)
 */
export interface SandboxEventData {
  sandbox_id?: string | undefined;
  project_id: string;
  event_type: string;
  status?: 'creating' | 'running' | 'stopping' | 'stopped' | 'error' | undefined;
  endpoint?: string | undefined;
  websocket_url?: string | undefined;
  desktop_url?: string | undefined;
  terminal_url?: string | undefined;
  error_message?: string | undefined;
  timestamp: string;
}


/**
 * Thought delta event data (streaming thought)
 */
export interface ThoughtDeltaEventData {
  delta: string;
  thought_level?: ThoughtLevel | undefined;
  step_number?: number | undefined;
}


/**
 * Text delta event data (typewriter effect)
 */
export interface TextDeltaEventData {
  delta: string;
}


/**
 * Text end event data (typewriter effect)
 */
export interface TextEndEventData {
  full_text?: string | undefined;
}


/**
 * Memory recalled event data (auto-recall)
 */
export interface MemoryRecalledEventData {
  memories: Array<{
    content: string;
    score: number;
    source: string;
    category: string;
  }>;
  count: number;
  search_ms: number;
}


/**
 * Memory captured event data (auto-capture)
 */
export interface MemoryCapturedEventData {
  captured_count: number;
  categories: string[];
}


/**
 * Pattern match SSE event data (T079)
 */
export interface PatternMatchEventData {
  pattern_id: string;
  similarity_score: number;
  query: string;
}


// ============================================
// Skill Execution Event Types (L2 Direct Execution)
// ============================================

/**
 * Skill execution mode
 */
export type SkillExecutionMode = 'direct' | 'prompt';


/**
 * Skill matched event data
 */
export interface SkillMatchedEventData {
  skill_id: string;
  skill_name: string;
  tools: string[];
  match_score: number;
  execution_mode: SkillExecutionMode;
}


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
  skill_name: string;
  tool_name: string;
  tool_input: Record<string, unknown>;
  step_index: number;
  total_steps: number;
  status: 'running';
}


/**
 * Skill tool result event data
 */
export interface SkillToolResultEventData {
  skill_id: string;
  skill_name: string;
  tool_name: string;
  result?: unknown;
  error?: string | undefined;
  duration_ms: number;
  step_index: number;
  total_steps: number;
  status: 'completed' | 'error';
}


/**
 * Skill tool execution for UI state
 */
export interface SkillToolExecution {
  tool_name: string;
  tool_input: Record<string, unknown>;
  result?: unknown;
  error?: string | undefined;
  status: 'running' | 'completed' | 'error';
  duration_ms?: number | undefined;
  step_index: number;
}


/**
 * Skill execution complete event data
 */
export interface SkillExecutionCompleteEventData {
  skill_id: string;
  skill_name: string;
  success: boolean;
  summary: string;
  tool_results: SkillToolExecution[];
  execution_time_ms: number;
  error?: string | undefined;
}


/**
 * Skill fallback event data
 */
export interface SkillFallbackEventData {
  skill_name: string;
  reason: 'execution_failed' | 'execution_error';
  error?: string | undefined;
}


/**
 * Context compressed event data
 * Emitted when context window compression occurs during a conversation
 */
export interface ContextCompressedEventData {
  was_compressed: boolean;
  compression_strategy: 'none' | 'truncate' | 'summarize';
  compression_level: string;
  original_message_count: number;
  final_message_count: number;
  estimated_tokens: number;
  token_budget: number;
  budget_utilization_pct: number;
  summarized_message_count: number;
  tokens_saved: number;
  compression_ratio: number;
  pruned_tool_outputs: number;
  duration_ms: number;
  token_distribution: Record<string, number>;
  compression_history_summary: Record<string, unknown>;
}


/**
 * Context status event data
 * Periodic context health report emitted at start of each step
 */
export interface ContextStatusEventData {
  current_tokens: number;
  token_budget: number;
  occupancy_pct: number;
  compression_level: string;
  token_distribution: Record<string, number>;
  compression_history_summary: Record<string, unknown>;
}


/**
 * Skill execution state for UI
 */
export interface SkillExecutionState {
  skill_id: string;
  skill_name: string;
  execution_mode: SkillExecutionMode;
  match_score: number;
  status: 'matched' | 'executing' | 'completed' | 'failed' | 'fallback';
  tools: string[];
  tool_executions: SkillToolExecution[];
  current_step: number;
  total_steps: number;
  summary?: string | undefined;
  error?: string | undefined;
  execution_time_ms?: number | undefined;
  started_at?: string | undefined;
  completed_at?: string | undefined;
}


/**
 * Desktop started event data
 */
export interface DesktopStartedEventData {
  sandbox_id: string;
  url: string;
  display: string;
  resolution: string;
  port: number;
}


/**
 * Desktop stopped event data
 */
export interface DesktopStoppedEventData {
  sandbox_id: string;
}


/**
 * Desktop status event data
 */
export interface DesktopStatusEventData extends DesktopStatus {
  sandbox_id: string;
}


/**
 * Terminal started event data
 */
export interface TerminalStartedEventData {
  sandbox_id: string;
  url: string;
  port: number;
  sessionId: string;
}


/**
 * Terminal stopped event data
 */
export interface TerminalStoppedEventData {
  sandbox_id: string;
  sessionId?: string | undefined;
}


/**
 * Terminal status event data
 */
export interface TerminalStatusEventData extends TerminalStatus {
  sandbox_id: string;
}


/**
 * Screenshot update event data
 */
export interface ScreenshotUpdateEventData {
  sandbox_id: string;
  imageUrl: string;
  timestamp: number;
}


/**
 * Sandbox created event data
 */
export interface SandboxCreatedEventData {
  sandbox_id: string;
  project_id: string;
  status: string;
  endpoint?: string | undefined;
  websocket_url?: string | undefined;
}


/**
 * Sandbox terminated event data
 */
export interface SandboxTerminatedEventData {
  sandbox_id: string;
}


/**
 * Sandbox status event data
 */
export interface SandboxStatusEventData {
  sandbox_id: string;
  status: string;
}


/**
 * Artifact created event data
 */
export interface ArtifactCreatedEventData {
  artifact_id: string;
  sandbox_id?: string | undefined;
  tool_execution_id?: string | undefined;
  filename: string;
  mime_type: string;
  category: string;
  size_bytes: number;
  url?: string | undefined;
  preview_url?: string | undefined;
  source_tool?: string | undefined;
  source_path?: string | undefined;
}


/**
 * Artifact ready event data
 */
export interface ArtifactReadyEventData {
  artifact_id: string;
  sandbox_id: string;
  tool_execution_id?: string | undefined;
  filename: string;
  mime_type: string;
  category: string;
  size_bytes: number;
  url: string;
  preview_url?: string | undefined;
  source_tool?: string | undefined;
  metadata?: Record<string, unknown> | undefined;
}


/**
 * Artifact error event data
 */
export interface ArtifactErrorEventData {
  artifact_id: string;
  sandbox_id: string;
  tool_execution_id?: string | undefined;
  filename: string;
  error: string;
}


/**
 * Artifact info for batch events
 */
export interface ArtifactInfo {
  id: string;
  filename: string;
  mimeType: string;
  category: string;
  sizeBytes: number;
  url?: string | undefined;
  previewUrl?: string | undefined;
  sourceTool?: string | undefined;
  metadata?: Record<string, unknown> | undefined;
}


/**
 * Artifacts batch event data
 */
export interface ArtifactsBatchEventData {
  sandbox_id: string;
  tool_execution_id?: string | undefined;
  artifacts: ArtifactInfo[];
  source_tool?: string | undefined;
}


/**
 * Suggestions event data - follow-up suggestions from the agent
 */
export interface SuggestionsEventData {
  suggestions: string[];
}


/**
 * Artifact open event data - agent opens content in canvas
 */
export interface ArtifactOpenEventData {
  artifact_id: string;
  title: string;
  content: string;
  content_type: 'code' | 'markdown' | 'preview' | 'data';
  language?: string | undefined;
}


/**
 * Artifact update event data - agent updates canvas content
 */
export interface ArtifactUpdateEventData {
  artifact_id: string;
  content: string;
  append: boolean;
}


/**
 * Artifact close event data - agent closes canvas tab
 */
export interface ArtifactCloseEventData {
  artifact_id: string;
}


// ===========================================================================
// Plan Mode SSE Event Types
// ===========================================================================

/**
 * Plan execution start event
 */
export interface PlanExecutionStartEvent {
  type: 'plan_execution_start';
  data: {
    plan_id: string;
    total_steps: number;
    user_query: string;
  };
  timestamp: string;
}


/**
 * Plan execution complete event
 */
export interface PlanExecutionCompleteEvent {
  type: 'plan_execution_complete';
  data: {
    plan_id: string;
    status: ExecutionPlanStatus;
    completed_steps: number;
    failed_steps: number;
  };
  timestamp: string;
}


/**
 * Plan step ready event
 */
export interface PlanStepReadyEvent {
  type: 'plan_step_ready';
  data: {
    plan_id: string;
    step_id: string;
    step_number: number;
    description: string;
    tool_name: string;
  };
  timestamp: string;
}


/**
 * Plan step complete event
 */
export interface PlanStepCompleteEvent {
  type: 'plan_step_complete';
  data: {
    plan_id: string;
    step_id: string;
    status: ExecutionStepStatus;
    result?: string | undefined;
  };
  timestamp: string;
}


/**
 * Plan step skipped event
 */
export interface PlanStepSkippedEvent {
  type: 'plan_step_skipped';
  data: {
    plan_id: string;
    step_id: string;
    reason: string;
  };
  timestamp: string;
}


/**
 * Plan snapshot created event
 */
export interface PlanSnapshotCreatedEvent {
  type: 'plan_snapshot_created';
  data: {
    plan_id: string;
    snapshot_id: string;
    snapshot_name: string;
    snapshot_type: string;
  };
  timestamp: string;
}


/**
 * Plan rollback event
 */
export interface PlanRollbackEvent {
  type: 'plan_rollback';
  data: {
    plan_id: string;
    snapshot_id: string;
    reason: string;
  };
  timestamp: string;
}


/**
 * Reflection complete event
 */
export interface ReflectionCompleteEvent {
  type: 'reflection_complete';
  data: {
    plan_id: string;
    assessment: ReflectionAssessment;
    reasoning: string;
    has_adjustments: boolean;
    adjustment_count: number;
  };
  timestamp: string;
}


/**
 * Adjustment applied event
 */
export interface AdjustmentAppliedEvent {
  type: 'adjustment_applied';
  data: {
    plan_id: string;
    adjustment_count: number;
    adjustments: StepAdjustment[];
  };
  timestamp: string;
}


/**
 * Union type for all Plan Mode events
 */
export type PlanModeEvent =
  | PlanExecutionStartEvent
  | PlanExecutionCompleteEvent
  | PlanStepReadyEvent
  | PlanStepCompleteEvent
  | PlanStepSkippedEvent
  | PlanSnapshotCreatedEvent
  | PlanRollbackEvent
  | ReflectionCompleteEvent
  | AdjustmentAppliedEvent;


// ============================================
// SubAgent Event Data Types (L3 layer)
// ============================================

export interface SubAgentRoutedEventData {
  route_id?: string | undefined;
  trace_id?: string | undefined;
  session_id?: string | undefined;
  subagent_id: string;
  subagent_name: string;
  confidence: number;
  reason?: string | undefined;
}


export interface SubAgentStartedEventData {
  subagent_id: string;
  subagent_name: string;
  task: string;
}


export interface SubAgentCompletedEventData {
  subagent_id: string;
  subagent_name: string;
  summary: string;
  tokens_used?: number | undefined;
  execution_time_ms?: number | undefined;
  success: boolean;
}


export interface SubAgentFailedEventData {
  subagent_id: string;
  subagent_name: string;
  error: string;
}


export interface SubAgentRunEventData {
  run_id: string;
  conversation_id: string;
  subagent_name: string;
  task: string;
  status: string;
  summary?: string | null | undefined;
  error?: string | null | undefined;
  execution_time_ms?: number | null | undefined;
  tokens_used?: number | null | undefined;
  metadata?: Record<string, unknown> | undefined;
}


export interface SubAgentSessionSpawnedEventData {
  conversation_id: string;
  run_id: string;
  subagent_name: string;
}


export interface SubAgentSessionMessageSentEventData {
  conversation_id: string;
  parent_run_id: string;
  run_id: string;
  subagent_name: string;
}


export interface SubAgentAnnounceRetryEventData {
  conversation_id: string;
  run_id: string;
  subagent_name: string;
  attempt: number;
  error: string;
  next_delay_ms: number;
}


export interface SubAgentAnnounceGiveupEventData {
  conversation_id: string;
  run_id: string;
  subagent_name: string;
  attempts: number;
  error: string;
}


export interface SubAgentQueuedEventData {
  subagent_id: string;
  subagent_name: string;
  queue_position: number;
  reason?: string | undefined;
}


export interface SubAgentKilledEventData {
  subagent_id: string;
  subagent_name: string;
  kill_reason: string;
}


export interface SubAgentSteeredEventData {
  subagent_id: string;
  subagent_name: string;
  instruction: string;
}


export interface SubAgentDepthLimitedEventData {
  subagent_name: string;
  current_depth: number;
  max_depth: number;
  parent_subagent_name?: string | undefined;
}


export interface SubAgentSessionUpdateEventData {
  subagent_id: string;
  subagent_name: string;
  progress: number;
  status_message?: string | undefined;
  tokens_used?: number | undefined;
  tool_calls_count?: number | undefined;
}


export interface ParallelStartedEventData {
  route_id?: string | undefined;
  trace_id?: string | undefined;
  session_id?: string | undefined;
  task_count: number;
  subtasks: Array<{ subagent_name: string; task: string }>;
}


export interface ParallelCompletedEventData {
  route_id?: string | undefined;
  trace_id?: string | undefined;
  session_id?: string | undefined;
  results: Array<{ subagent_name: string; summary: string; success: boolean }>;
  total_time_ms?: number | undefined;
}


export interface ChainStartedEventData {
  route_id?: string | undefined;
  trace_id?: string | undefined;
  session_id?: string | undefined;
  step_count: number;
  chain_name?: string | undefined;
}


export interface ChainStepStartedEventData {
  route_id?: string | undefined;
  trace_id?: string | undefined;
  session_id?: string | undefined;
  step_index: number;
  step_name?: string | undefined;
  subagent_name: string;
}


export interface ChainStepCompletedEventData {
  route_id?: string | undefined;
  trace_id?: string | undefined;
  session_id?: string | undefined;
  step_index: number;
  summary: string;
  success: boolean;
}


export interface ChainCompletedEventData {
  route_id?: string | undefined;
  trace_id?: string | undefined;
  session_id?: string | undefined;
  total_steps: number;
  total_time_ms?: number | undefined;
  success: boolean;
}


export interface BackgroundLaunchedEventData {
  execution_id: string;
  subagent_name: string;
  task: string;
}


/**
 * Canvas block data shape from backend CanvasBlock.to_dict()
 */
export interface CanvasBlockData {
  id: string;
  block_type: 'code' | 'table' | 'chart' | 'form' | 'image' | 'markdown' | 'widget' | 'a2ui_surface';
  title: string;
  content: string;
  metadata: Record<string, string>;
  version: number;
}

/**
 * Canvas updated event data (A2UI integration)
 *
 * Emitted by canvas_create / canvas_update / canvas_delete tools.
 */
export interface CanvasUpdatedEventData {
  conversation_id: string;
  block_id: string;
  action: 'created' | 'updated' | 'deleted';
  block: CanvasBlockData | null;
}



/**
 * A2UI action asked event data (HITL: agent paused waiting for user interaction)
 *
 * Emitted by canvas_create_interactive tool when the agent renders an interactive
 * A2UI surface and waits for the user to interact with it.
 */
export interface A2UIActionAskedEventData {
  request_id: string;
  conversation_id: string;
  block_id: string;
  title?: string | undefined;
  timeout_seconds?: number | undefined;
  surface_data?: Record<string, unknown> | undefined;
}
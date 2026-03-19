import type { ArtifactCategory } from './config';
import type { ArtifactReference } from './core';
import type {
  ClarificationType,
  ClarificationOption,
  DecisionType,
  DecisionOption,
  EnvVarField,
  MemoryRecalledEventData,
  ArtifactInfo,
} from './events';
// ============================================
// Execution Timeline Types (UI State)
// ============================================

/**
 * Tool execution status
 */
export type ToolExecutionStatus = 'running' | 'success' | 'failed';

/**
 * Timeline step status
 */
export type TimelineStepStatus = 'pending' | 'running' | 'completed' | 'failed';

/**
 * Tool execution record for timeline
 */
export interface ToolExecution {
  id: string;
  toolName: string;
  input: Record<string, unknown>;
  status: ToolExecutionStatus;
  result?: string | undefined;
  error?: string | undefined;
  startTime: string;
  endTime?: string | undefined;
  duration?: number | undefined;
  stepNumber?: number | undefined;
}

/**
 * Timeline step for execution visualization
 */
export interface TimelineStep {
  stepNumber: number;
  description: string;
  status: TimelineStepStatus;
  startTime?: string | undefined;
  endTime?: string | undefined;
  duration?: number | undefined;
  thoughts: string[];
  toolExecutions: ToolExecution[];
}

// ============================================
// Timeline Event Types (Unified Event Stream)
// ============================================

/**
 * All possible timeline event types from unified event stream
 */
export type TimelineEventType =
  | 'user_message'
  | 'assistant_message'
  | 'thought'
  | 'act'
  | 'observe'
  | 'work_plan'
  | 'text_delta'
  | 'text_start'
  | 'text_end'
  // Human-in-the-loop event types
  | 'clarification_asked'
  | 'clarification_answered'
  | 'decision_asked'
  | 'decision_answered'
  | 'env_var_requested'
  | 'env_var_provided'
  | 'permission_asked'
  | 'permission_replied'
  | 'permission_requested' // DB format
  | 'permission_granted' // DB format
  // Sandbox event types
  | 'sandbox_created'
  | 'sandbox_terminated'
  | 'sandbox_status'
  | 'desktop_started'
  | 'desktop_stopped'
  | 'desktop_status'
  | 'terminal_started'
  | 'terminal_stopped'
  | 'terminal_status'
  | 'screenshot_update'
  // Artifact event types
  | 'artifact_created'
  | 'artifact_ready'
  | 'artifact_error'
  | 'artifacts_batch'
  // SubAgent event types (L3 layer)
  | 'subagent_routed'
  | 'subagent_started'
  | 'subagent_completed'
  | 'subagent_failed'
  | 'subagent_run_started'
  | 'subagent_run_completed'
  | 'subagent_run_failed'
  | 'subagent_session_spawned'
  | 'subagent_session_message_sent'
  | 'subagent_announce_retry'
  | 'subagent_announce_giveup'
  | 'subagent_killed'
  | 'subagent_steered'
  | 'subagent_queued'
  | 'subagent_depth_limited'
  | 'subagent_session_update'
  | 'parallel_started'
  | 'parallel_completed'
  | 'chain_started'
  | 'chain_step_started'
  | 'chain_step_completed'
  | 'chain_completed'
  | 'background_launched'
  // Task timeline event types
  | 'task_start'
  | 'task_complete'
  // Memory event types
  | 'memory_recalled'
  | 'memory_captured'
  // Canvas events
  | 'canvas_updated'
  // Multi-Agent events (L4 layer)
  | 'agent_spawned'
  | 'agent_completed'
  | 'agent_stopped';

/**
 * Base timeline event (all events share these fields)
 */
export interface BaseTimelineEvent {
  id: string;
  type: TimelineEventType;
  eventTimeUs: number;
  eventCounter: number;
  timestamp: number; // Unix timestamp in milliseconds (derived from eventTimeUs / 1000)
  metadata?: Record<string, unknown> | undefined;
}

/**
 * User message event
 */
export interface UserMessageEvent extends BaseTimelineEvent {
  type: 'user_message';
  content: string;
  role: 'user';
}

/**
 * Assistant message event
 */
export interface AssistantMessageEvent extends BaseTimelineEvent {
  type: 'assistant_message';
  content: string;
  role: 'assistant';
  artifacts?: ArtifactReference[] | undefined;
}

/**
 * Thought event (agent reasoning)
 */
export interface ThoughtEvent extends BaseTimelineEvent {
  type: 'thought';
  content: string;
}

/**
 * Act event (tool call)
 */
export interface ActEvent extends BaseTimelineEvent {
  type: 'act';
  toolName: string;
  toolInput: Record<string, unknown>;
  execution_id?: string | undefined; // New: unique ID for act/observe matching
  execution?:
    | {
        startTime: number;
        endTime: number;
        duration: number;
      }
    | undefined;
}

/**
 * Observe event (tool result)
 */
export interface ObserveEvent extends BaseTimelineEvent {
  type: 'observe';
  toolName: string;
  toolOutput?: string | undefined; // May be undefined if result is not a string or empty
  isError: boolean;
  execution_id?: string | undefined; // New: matches act event's execution_id
  mcpUiMetadata?:
    | {
        resource_uri?: string | undefined;
        server_name?: string | undefined;
        app_id?: string | undefined;
        title?: string | undefined;
      }
    | undefined;
}

/**
 * Work plan event
 */
export interface WorkPlanTimelineEvent extends BaseTimelineEvent {
  type: 'work_plan';
  steps: Array<{
    step_number: number;
    description: string;
    expected_output: string;
  }>;
  status: string;
}

/**
 * Task start event (timeline marker when agent begins a task)
 */
export interface TaskStartTimelineEvent extends BaseTimelineEvent {
  type: 'task_start';
  taskId: string;
  content: string;
  orderIndex: number;
  totalTasks: number;
}

/**
 * Task complete event (timeline marker when agent finishes a task)
 */
export interface TaskCompleteTimelineEvent extends BaseTimelineEvent {
  type: 'task_complete';
  taskId: string;
  status: string;
  orderIndex: number;
  totalTasks: number;
}

// ============================================
// Memory Timeline Event Interfaces
// ============================================

export interface MemoryRecalledTimelineEvent extends BaseTimelineEvent {
  type: 'memory_recalled';
  memories: MemoryRecalledEventData['memories'];
  count: number;
  searchMs: number;
}

export interface MemoryCapturedTimelineEvent extends BaseTimelineEvent {
  type: 'memory_captured';
  capturedCount: number;
  categories: string[];
}

/**
 * Text delta event (typewriter effect - incremental text)
 */
export interface TextDeltaEvent extends BaseTimelineEvent {
  type: 'text_delta';
  content: string;
}

/**
 * Text start event (typewriter effect - marks beginning)
 */
export interface TextStartEvent extends BaseTimelineEvent {
  type: 'text_start';
}

/**
 * Text end event (typewriter effect - marks completion)
 */
export interface TextEndEvent extends BaseTimelineEvent {
  type: 'text_end';
  fullText?: string | undefined;
}

// ============================================
// Human-in-the-Loop Timeline Event Types
// ============================================

/**
 * Clarification asked event (agent asks user for clarification)
 */
export interface ClarificationAskedTimelineEvent extends BaseTimelineEvent {
  type: 'clarification_asked';
  requestId: string;
  question: string;
  clarificationType: ClarificationType;
  options: ClarificationOption[];
  allowCustom: boolean;
  context?: Record<string, unknown> | undefined;
  answered?: boolean | undefined;
  answer?: string | undefined;
}

/**
 * Clarification answered event (user responded to clarification)
 */
export interface ClarificationAnsweredTimelineEvent extends BaseTimelineEvent {
  type: 'clarification_answered';
  requestId: string;
  answer: string;
}

/**
 * Decision asked event (agent asks user for decision)
 */
export interface DecisionAskedTimelineEvent extends BaseTimelineEvent {
  type: 'decision_asked';
  requestId: string;
  question: string;
  decisionType: DecisionType;
  options: DecisionOption[];
  allowCustom: boolean;
  context?: Record<string, unknown> | undefined;
  defaultOption?: string | undefined;
  selectionMode?: 'single' | 'multiple' | undefined;
  maxSelections?: number | undefined;
  answered?: boolean | undefined;
  decision?: string | undefined;
}

/**
 * Decision answered event (user made a decision)
 */
export interface DecisionAnsweredTimelineEvent extends BaseTimelineEvent {
  type: 'decision_answered';
  requestId: string;
  decision: string;
}

/**
 * Environment variable requested event (agent requests env vars from user)
 */
export interface EnvVarRequestedTimelineEvent extends BaseTimelineEvent {
  type: 'env_var_requested';
  requestId: string;
  toolName: string;
  fields: EnvVarField[];
  message?: string | undefined;
  context?: Record<string, unknown> | undefined;
  answered?: boolean | undefined;
  providedVariables?: string[] | undefined;
}

/**
 * Environment variable provided event (user provided env vars)
 */
export interface EnvVarProvidedTimelineEvent extends BaseTimelineEvent {
  type: 'env_var_provided';
  requestId: string;
  toolName: string;
  variableNames: string[];
}

/**
 * Permission asked event (agent requests permission from user)
 */
export interface PermissionAskedTimelineEvent extends BaseTimelineEvent {
  type: 'permission_asked';
  requestId: string;
  toolName: string;
  description: string;
  riskLevel?: 'low' | 'medium' | 'high' | undefined;
  parameters?: Record<string, unknown> | undefined;
  context?: Record<string, unknown> | undefined;
  answered?: boolean | undefined;
  granted?: boolean | undefined;
}

/**
 * Permission requested event (DB format - same as permission_asked)
 */
export interface PermissionRequestedTimelineEvent extends BaseTimelineEvent {
  type: 'permission_requested';
  requestId: string;
  action?: string | undefined;
  resource?: string | undefined;
  reason?: string | undefined;
  riskLevel?: 'low' | 'medium' | 'high' | undefined;
  context?: Record<string, unknown> | undefined;
  answered?: boolean | undefined;
  granted?: boolean | undefined;
}

/**
 * Permission replied event (user granted or denied permission)
 */
export interface PermissionRepliedTimelineEvent extends BaseTimelineEvent {
  type: 'permission_replied';
  requestId: string;
  granted: boolean;
}

/**
 * Permission granted event (DB format - same as permission_replied)
 */
export interface PermissionGrantedTimelineEvent extends BaseTimelineEvent {
  type: 'permission_granted';
  requestId: string;
  granted: boolean;
}

export interface CanvasUpdatedTimelineEvent extends BaseTimelineEvent {
  type: 'canvas_updated';
  action: string;
  block_id: string;
  block?: {
    id: string;
    block_type: string;
    title: string;
    content: string;
    metadata?: Record<string, unknown>;
  } | null;
}

/**
 * Union type for all timeline events
 */
export type TimelineEvent =
  | UserMessageEvent
  | AssistantMessageEvent
  | ThoughtEvent
  | ActEvent
  | ObserveEvent
  | WorkPlanTimelineEvent
  | TextDeltaEvent
  | TextStartEvent
  | TextEndEvent
  // Human-in-the-loop events
  | ClarificationAskedTimelineEvent
  | ClarificationAnsweredTimelineEvent
  | DecisionAskedTimelineEvent
  | DecisionAnsweredTimelineEvent
  | EnvVarRequestedTimelineEvent
  | EnvVarProvidedTimelineEvent
  | PermissionAskedTimelineEvent
  | PermissionRepliedTimelineEvent
  | PermissionRequestedTimelineEvent // DB format
  | PermissionGrantedTimelineEvent // DB format
  // Sandbox events
  | DesktopStartedEvent
  | DesktopStoppedEvent
  | DesktopStatusEvent
  | TerminalStartedEvent
  | TerminalStoppedEvent
  | TerminalStatusEvent
  | ScreenshotUpdateEvent
  | SandboxCreatedEvent
  | SandboxTerminatedEvent
  | SandboxStatusEvent
  // Artifact events
  | ArtifactCreatedEvent
  | ArtifactReadyEvent
  | ArtifactErrorEvent
  | ArtifactsBatchEvent
  // SubAgent events (L3 layer)
  | SubAgentRoutedTimelineEvent
  | SubAgentStartedTimelineEvent
  | SubAgentCompletedTimelineEvent
  | SubAgentFailedTimelineEvent
  | ParallelStartedTimelineEvent
  | ParallelCompletedTimelineEvent
  | ChainStartedTimelineEvent
  | ChainStepStartedTimelineEvent
  | ChainStepCompletedTimelineEvent
  | ChainCompletedTimelineEvent
  | BackgroundLaunchedTimelineEvent
  | SubAgentQueuedTimelineEvent
  | SubAgentKilledTimelineEvent
  | SubAgentSteeredTimelineEvent
  | SubAgentDepthLimitedTimelineEvent
  | SubAgentSessionUpdateTimelineEvent
  // Task timeline events
  | TaskStartTimelineEvent
  | TaskCompleteTimelineEvent
  // Memory events
  | MemoryRecalledTimelineEvent
  | MemoryCapturedTimelineEvent
  // Canvas events
  | CanvasUpdatedTimelineEvent
  // Multi-Agent events (L4 layer)
  | AgentSpawnedTimelineEvent
  | AgentCompletedTimelineEvent
  | AgentStoppedTimelineEvent;

// ============================================
// SubAgent Timeline Event Interfaces (L3 layer)
// ============================================

export interface SubAgentRoutedTimelineEvent extends BaseTimelineEvent {
  type: 'subagent_routed';
  subagentId: string;
  subagentName: string;
  confidence: number;
  reason: string;
}

export interface SubAgentStartedTimelineEvent extends BaseTimelineEvent {
  type: 'subagent_started';
  subagentId: string;
  subagentName: string;
  task: string;
}

export interface SubAgentCompletedTimelineEvent extends BaseTimelineEvent {
  type: 'subagent_completed';
  subagentId: string;
  subagentName?: string | undefined;
  summary: string;
  tokensUsed: number;
  executionTimeMs: number;
  success?: boolean | undefined;
}

export interface SubAgentFailedTimelineEvent extends BaseTimelineEvent {
  type: 'subagent_failed';
  subagentId: string;
  subagentName?: string | undefined;
  error: string;
}

export interface SubAgentQueuedTimelineEvent extends BaseTimelineEvent {
  type: 'subagent_queued';
  subagentId: string;
  subagentName?: string | undefined;
  queuePosition?: number | undefined;
  reason?: string | undefined;
}

export interface SubAgentKilledTimelineEvent extends BaseTimelineEvent {
  type: 'subagent_killed';
  subagentId: string;
  subagentName?: string | undefined;
  kill_reason?: string | undefined;
  error?: string | undefined;
}

export interface SubAgentSteeredTimelineEvent extends BaseTimelineEvent {
  type: 'subagent_steered';
  subagentId: string;
  subagentName?: string | undefined;
  instruction?: string | undefined;
}

export interface SubAgentDepthLimitedTimelineEvent extends BaseTimelineEvent {
  type: 'subagent_depth_limited';
  subagentName?: string | undefined;
  current_depth?: number | undefined;
  max_depth?: number | undefined;
  parentSubagentName?: string | undefined;
}

export interface SubAgentSessionUpdateTimelineEvent extends BaseTimelineEvent {
  type: 'subagent_session_update';
  subagentId: string;
  subagentName?: string | undefined;
  progress?: number | undefined;
  statusMessage?: string | undefined;
  tokensUsed?: number | undefined;
  toolCallsCount?: number | undefined;
}

export interface ParallelStartedTimelineEvent extends BaseTimelineEvent {
  type: 'parallel_started';
  taskCount: number;
  subtasks: Array<{ subagent_name: string; task: string }>;
}

export interface ParallelCompletedTimelineEvent extends BaseTimelineEvent {
  type: 'parallel_completed';
  results: Array<{ subagent_name: string; summary: string; success: boolean }>;
  totalTimeMs: number;
}

export interface ChainStartedTimelineEvent extends BaseTimelineEvent {
  type: 'chain_started';
  stepCount: number;
  chainName: string;
}

export interface ChainStepStartedTimelineEvent extends BaseTimelineEvent {
  type: 'chain_step_started';
  stepIndex: number;
  stepName: string;
  subagentName: string;
}

export interface ChainStepCompletedTimelineEvent extends BaseTimelineEvent {
  type: 'chain_step_completed';
  stepIndex: number;
  summary: string;
  success?: boolean | undefined;
}

export interface ChainCompletedTimelineEvent extends BaseTimelineEvent {
  type: 'chain_completed';
  totalSteps: number;
  totalTimeMs: number;
  success?: boolean | undefined;
}

export interface BackgroundLaunchedTimelineEvent extends BaseTimelineEvent {
  type: 'background_launched';
  executionId: string;
  subagentName: string;
  task: string;
}

// Multi-Agent Timeline Event Interfaces (L4 layer)

export interface AgentSpawnedTimelineEvent extends BaseTimelineEvent {
  type: 'agent_spawned';
  agentId: string;
  agentName: string | null;
  parentAgentId: string | null;
  childSessionId: string | null;
  mode: string;
  taskSummary: string | null;
}

export interface AgentCompletedTimelineEvent extends BaseTimelineEvent {
  type: 'agent_completed';
  agentId: string;
  agentName: string | null;
  parentAgentId: string | null;
  sessionId: string | null;
  result: string | null;
  success: boolean;
  artifacts: string[];
}

export interface AgentStoppedTimelineEvent extends BaseTimelineEvent {
  type: 'agent_stopped';
  agentId: string;
  agentName: string | null;
  reason: string | null;
  stoppedBy: string | null;
}

/**
 * Timeline response from API (unified event stream)
 */
export interface TimelineResponse {
  conversationId: string;
  timeline: TimelineEvent[];
  total: number;
}

/**
 * Desktop started timeline event
 */
export interface DesktopStartedEvent extends BaseTimelineEvent {
  type: 'desktop_started';
  sandboxId: string;
  url: string;
  display: string;
  resolution: string;
  port: number;
}

/**
 * Desktop stopped timeline event
 */
export interface DesktopStoppedEvent extends BaseTimelineEvent {
  type: 'desktop_stopped';
  sandboxId: string;
}

/**
 * Desktop status timeline event
 */
export interface DesktopStatusEvent extends BaseTimelineEvent {
  type: 'desktop_status';
  sandboxId: string;
  running: boolean;
  url: string | null;
  display: string;
  resolution: string;
  port: number;
}

/**
 * Terminal started timeline event
 */
export interface TerminalStartedEvent extends BaseTimelineEvent {
  type: 'terminal_started';
  sandboxId: string;
  url: string;
  port: number;
  sessionId: string;
}

/**
 * Terminal stopped timeline event
 */
export interface TerminalStoppedEvent extends BaseTimelineEvent {
  type: 'terminal_stopped';
  sandboxId: string;
  sessionId?: string | undefined;
}

/**
 * Terminal status timeline event
 */
export interface TerminalStatusEvent extends BaseTimelineEvent {
  type: 'terminal_status';
  sandboxId: string;
  running: boolean;
  url: string | null;
  port: number;
  sessionId?: string | undefined;
}

/**
 * Screenshot update timeline event
 */
export interface ScreenshotUpdateEvent extends BaseTimelineEvent {
  type: 'screenshot_update';
  sandboxId: string;
  imageUrl: string;
}

/**
 * Sandbox created timeline event
 */
export interface SandboxCreatedEvent extends BaseTimelineEvent {
  type: 'sandbox_created';
  sandboxId: string;
  projectId: string;
  status: string;
  endpoint?: string | undefined;
  websocketUrl?: string | undefined;
}

/**
 * Sandbox terminated timeline event
 */
export interface SandboxTerminatedEvent extends BaseTimelineEvent {
  type: 'sandbox_terminated';
  sandboxId: string;
}

/**
 * Sandbox status timeline event
 */
export interface SandboxStatusEvent extends BaseTimelineEvent {
  type: 'sandbox_status';
  sandboxId: string;
  status: string;
}

/**
 * Artifact created timeline event
 */
export interface ArtifactCreatedEvent extends BaseTimelineEvent {
  type: 'artifact_created';
  artifactId: string;
  sandboxId?: string | undefined;
  toolExecutionId?: string | undefined;
  filename: string;
  mimeType: string;
  category: ArtifactCategory;
  sizeBytes: number;
  url?: string | undefined;
  previewUrl?: string | undefined;
  sourceTool?: string | undefined;
  sourcePath?: string | undefined;
}

/**
 * Artifact ready timeline event
 */
export interface ArtifactReadyEvent extends BaseTimelineEvent {
  type: 'artifact_ready';
  artifactId: string;
  sandboxId: string;
  toolExecutionId?: string | undefined;
  filename: string;
  mimeType: string;
  category: ArtifactCategory;
  sizeBytes: number;
  url: string;
  previewUrl?: string | undefined;
  sourceTool?: string | undefined;
  metadata?: Record<string, unknown> | undefined;
}

/**
 * Artifact error timeline event
 */
export interface ArtifactErrorEvent extends BaseTimelineEvent {
  type: 'artifact_error';
  artifactId: string;
  sandboxId: string;
  toolExecutionId?: string | undefined;
  filename: string;
  error: string;
}

/**
 * Artifacts batch timeline event
 */
export interface ArtifactsBatchEvent extends BaseTimelineEvent {
  type: 'artifacts_batch';
  sandboxId: string;
  toolExecutionId?: string | undefined;
  artifacts: ArtifactInfo[];
  sourceTool?: string | undefined;
}

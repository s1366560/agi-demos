/**
 * Auto-generated event types from Python.
 * Generated at: 2026-03-03T11:55:15.524191Z
 *
 * DO NOT EDIT MANUALLY - run `make generate-event-types` to regenerate.
 */

// Event Categories
export type EventCategory = 'agent' | 'hitl' | 'sandbox' | 'system' | 'message';

// All Agent Event Types
export type AgentEventType =
  | 'status'
  | 'start'
  | 'complete'
  | 'error'
  | 'thought'
  | 'thought_delta'
  | 'act'
  | 'act_delta'
  | 'observe'
  | 'text_start'
  | 'text_delta'
  | 'text_end'
  | 'message'
  | 'user_message'
  | 'assistant_message'
  | 'permission_asked'
  | 'permission_replied'
  | 'doom_loop_detected'
  | 'doom_loop_intervened'
  | 'clarification_asked'
  | 'clarification_answered'
  | 'decision_asked'
  | 'decision_answered'
  | 'env_var_requested'
  | 'env_var_provided'
  | 'cost_update'
  | 'context_compressed'
  | 'context_status'
  | 'context_summary_generated'
  | 'memory_recalled'
  | 'memory_captured'
  | 'pattern_match'
  | 'skill_matched'
  | 'skill_execution_start'
  | 'skill_execution_complete'
  | 'skill_fallback'
  | 'title_generated'
  | 'sandbox_created'
  | 'sandbox_terminated'
  | 'sandbox_status'
  | 'desktop_started'
  | 'desktop_stopped'
  | 'desktop_status'
  | 'terminal_started'
  | 'terminal_stopped'
  | 'terminal_status'
  | 'suggestions'
  | 'artifact_created'
  | 'artifact_ready'
  | 'artifact_error'
  | 'artifacts_batch'
  | 'artifact_open'
  | 'artifact_update'
  | 'artifact_close'
  | 'mcp_app_result'
  | 'mcp_app_registered'
  | 'subagent_routed'
  | 'subagent_started'
  | 'subagent_completed'
  | 'subagent_failed'
  | 'subagent_spawning'
  | 'subagent_doom_loop'
  | 'subagent_retry'
  | 'subagent_queued'
  | 'subagent_killed'
  | 'subagent_steered'
  | 'subagent_depth_limited'
  | 'subagent_session_update'
  | 'cancelled'
  | 'task_list_updated'
  | 'task_updated'
  | 'task_start'
  | 'task_complete'
  | 'tools_updated'
  | 'progress'
  | 'elicitation_asked'
  | 'elicitation_answered'
  | 'canvas_updated'
  | 'plan_suggested'
  | 'selection_trace'
  | 'policy_filtered'
  | 'parallel_started'
  | 'parallel_completed'
  | 'background_launched';

// Delta events (not persisted)
export const DELTA_EVENT_TYPES: AgentEventType[] = [
  'text_end',
  'thought_delta',
  'text_delta',
  'act_delta',
  'text_start',
];

// Terminal events (stream completion)
export const TERMINAL_EVENT_TYPES: AgentEventType[] = ['cancelled', 'error', 'complete'];

// HITL events (require user response)
export const HITL_EVENT_TYPES: AgentEventType[] = [
  'env_var_requested',
  'elicitation_asked',
  'permission_asked',
  'decision_asked',
  'clarification_asked',
];

// Helper functions
export function isTerminalEvent(eventType: AgentEventType): boolean {
  return TERMINAL_EVENT_TYPES.includes(eventType);
}

export function isDeltaEvent(eventType: AgentEventType): boolean {
  return DELTA_EVENT_TYPES.includes(eventType);
}

export function isHITLEvent(eventType: AgentEventType): boolean {
  return HITL_EVENT_TYPES.includes(eventType);
}

// Event type to category mapping
export const EVENT_CATEGORIES: Record<AgentEventType, EventCategory> = {
  status: 'agent',
  start: 'agent',
  complete: 'agent',
  error: 'agent',
  thought: 'agent',
  thought_delta: 'agent',
  act: 'agent',
  act_delta: 'agent',
  observe: 'agent',
  text_start: 'agent',
  text_delta: 'agent',
  text_end: 'agent',
  message: 'message',
  user_message: 'message',
  assistant_message: 'message',
  permission_asked: 'hitl',
  permission_replied: 'hitl',
  doom_loop_detected: 'agent',
  doom_loop_intervened: 'agent',
  clarification_asked: 'hitl',
  clarification_answered: 'hitl',
  decision_asked: 'hitl',
  decision_answered: 'hitl',
  env_var_requested: 'hitl',
  env_var_provided: 'hitl',
  cost_update: 'system',
  context_compressed: 'system',
  context_status: 'system',
  context_summary_generated: 'system',
  memory_recalled: 'agent',
  memory_captured: 'agent',
  pattern_match: 'agent',
  skill_matched: 'agent',
  skill_execution_start: 'agent',
  skill_execution_complete: 'agent',
  skill_fallback: 'agent',
  title_generated: 'agent',
  sandbox_created: 'sandbox',
  sandbox_terminated: 'sandbox',
  sandbox_status: 'sandbox',
  desktop_started: 'sandbox',
  desktop_stopped: 'sandbox',
  desktop_status: 'sandbox',
  terminal_started: 'sandbox',
  terminal_stopped: 'sandbox',
  terminal_status: 'sandbox',
  suggestions: 'agent',
  artifact_created: 'agent',
  artifact_ready: 'agent',
  artifact_error: 'agent',
  artifacts_batch: 'agent',
  artifact_open: 'agent',
  artifact_update: 'agent',
  artifact_close: 'agent',
  mcp_app_result: 'agent',
  mcp_app_registered: 'agent',
  subagent_routed: 'agent',
  subagent_started: 'agent',
  subagent_completed: 'agent',
  subagent_failed: 'agent',
  subagent_spawning: 'agent',
  subagent_doom_loop: 'agent',
  subagent_retry: 'agent',
  subagent_queued: 'agent',
  subagent_killed: 'agent',
  subagent_steered: 'agent',
  subagent_depth_limited: 'agent',
  subagent_session_update: 'agent',
  cancelled: 'agent',
  task_list_updated: 'agent',
  task_updated: 'agent',
  task_start: 'agent',
  task_complete: 'agent',
  tools_updated: 'agent',
  progress: 'agent',
  elicitation_asked: 'hitl',
  elicitation_answered: 'hitl',
  canvas_updated: 'agent',
  plan_suggested: 'agent',
  selection_trace: 'agent',
  policy_filtered: 'agent',
  parallel_started: 'agent',
  parallel_completed: 'agent',
  background_launched: 'agent',
};

export function getEventCategory(eventType: AgentEventType): EventCategory {
  return EVENT_CATEGORIES[eventType] || 'agent';
}

// All event types (for iteration)
export const ALL_EVENT_TYPES: AgentEventType[] = [
  'status',
  'start',
  'complete',
  'error',
  'thought',
  'thought_delta',
  'act',
  'act_delta',
  'observe',
  'text_start',
  'text_delta',
  'text_end',
  'message',
  'user_message',
  'assistant_message',
  'permission_asked',
  'permission_replied',
  'doom_loop_detected',
  'doom_loop_intervened',
  'clarification_asked',
  'clarification_answered',
  'decision_asked',
  'decision_answered',
  'env_var_requested',
  'env_var_provided',
  'cost_update',
  'context_compressed',
  'context_status',
  'context_summary_generated',
  'memory_recalled',
  'memory_captured',
  'pattern_match',
  'skill_matched',
  'skill_execution_start',
  'skill_execution_complete',
  'skill_fallback',
  'title_generated',
  'sandbox_created',
  'sandbox_terminated',
  'sandbox_status',
  'desktop_started',
  'desktop_stopped',
  'desktop_status',
  'terminal_started',
  'terminal_stopped',
  'terminal_status',
  'suggestions',
  'artifact_created',
  'artifact_ready',
  'artifact_error',
  'artifacts_batch',
  'artifact_open',
  'artifact_update',
  'artifact_close',
  'mcp_app_result',
  'mcp_app_registered',
  'subagent_routed',
  'subagent_started',
  'subagent_completed',
  'subagent_failed',
  'subagent_spawning',
  'subagent_doom_loop',
  'subagent_retry',
  'subagent_queued',
  'subagent_killed',
  'subagent_steered',
  'subagent_depth_limited',
  'subagent_session_update',
  'cancelled',
  'task_list_updated',
  'task_updated',
  'task_start',
  'task_complete',
  'tools_updated',
  'progress',
  'elicitation_asked',
  'elicitation_answered',
  'canvas_updated',
  'plan_suggested',
  'selection_trace',
  'policy_filtered',
  'parallel_started',
  'parallel_completed',
  'background_launched',
];

/**
 * Auto-generated event types from Python.
 * Generated at: 2026-02-04T00:33:59.441323Z
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
  | 'work_plan'
  | 'step_start'
  | 'step_end'
  | 'step_finish'
  | 'act'
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
  | 'pattern_match'
  | 'skill_matched'
  | 'skill_execution_start'
  | 'skill_execution_complete'
  | 'skill_fallback'
  | 'plan_mode_enter'
  | 'plan_mode_exit'
  | 'plan_created'
  | 'plan_updated'
  | 'plan_status_changed'
  | 'plan_execution_start'
  | 'plan_execution_complete'
  | 'plan_step_ready'
  | 'plan_step_complete'
  | 'plan_step_skipped'
  | 'plan_snapshot_created'
  | 'plan_rollback'
  | 'reflection_complete'
  | 'adjustment_applied'
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
  | 'artifact_created'
  | 'artifact_ready'
  | 'artifact_error'
  | 'artifacts_batch'
  | 'cancelled'
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
  | 'parallel_started'
  | 'parallel_completed'
  | 'chain_started'
  | 'chain_step_started'
  | 'chain_step_completed'
  | 'chain_completed'
  | 'background_launched';

// Delta events (not persisted)
export const DELTA_EVENT_TYPES: AgentEventType[] = [
  'text_start',
  'thought_delta',
  'text_end',
  'text_delta',
];

// Terminal events (stream completion)
export const TERMINAL_EVENT_TYPES: AgentEventType[] = ['cancelled', 'error', 'complete'];

// HITL events (require user response)
export const HITL_EVENT_TYPES: AgentEventType[] = [
  'decision_asked',
  'clarification_asked',
  'env_var_requested',
  'permission_asked',
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
  work_plan: 'agent',
  step_start: 'agent',
  step_end: 'agent',
  step_finish: 'agent',
  act: 'agent',
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
  pattern_match: 'agent',
  skill_matched: 'agent',
  skill_execution_start: 'agent',
  skill_execution_complete: 'agent',
  skill_fallback: 'agent',
  plan_mode_enter: 'agent',
  plan_mode_exit: 'agent',
  plan_created: 'agent',
  plan_updated: 'agent',
  plan_status_changed: 'agent',
  plan_execution_start: 'agent',
  plan_execution_complete: 'agent',
  plan_step_ready: 'agent',
  plan_step_complete: 'agent',
  plan_step_skipped: 'agent',
  plan_snapshot_created: 'agent',
  plan_rollback: 'agent',
  reflection_complete: 'agent',
  adjustment_applied: 'agent',
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
  artifact_created: 'agent',
  artifact_ready: 'agent',
  artifact_error: 'agent',
  artifacts_batch: 'agent',
  cancelled: 'agent',
  // SubAgent event types (L3 layer)
  subagent_routed: 'agent',
  subagent_started: 'agent',
  subagent_completed: 'agent',
  subagent_failed: 'agent',
  subagent_run_started: 'agent',
  subagent_run_completed: 'agent',
  subagent_run_failed: 'agent',
  subagent_session_spawned: 'agent',
  subagent_session_message_sent: 'agent',
  subagent_announce_retry: 'agent',
  subagent_announce_giveup: 'agent',
  subagent_killed: 'agent',
  subagent_steered: 'agent',
  parallel_started: 'agent',
  parallel_completed: 'agent',
  chain_started: 'agent',
  chain_step_started: 'agent',
  chain_step_completed: 'agent',
  chain_completed: 'agent',
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
  'work_plan',
  'step_start',
  'step_end',
  'step_finish',
  'act',
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
  'pattern_match',
  'skill_matched',
  'skill_execution_start',
  'skill_execution_complete',
  'skill_fallback',
  'plan_mode_enter',
  'plan_mode_exit',
  'plan_created',
  'plan_updated',
  'plan_status_changed',
  'plan_execution_start',
  'plan_execution_complete',
  'plan_step_ready',
  'plan_step_complete',
  'plan_step_skipped',
  'plan_snapshot_created',
  'plan_rollback',
  'reflection_complete',
  'adjustment_applied',
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
  'artifact_created',
  'artifact_ready',
  'artifact_error',
  'artifacts_batch',
  'cancelled',
  // SubAgent event types (L3 layer)
  'subagent_routed',
  'subagent_started',
  'subagent_completed',
  'subagent_failed',
  'subagent_run_started',
  'subagent_run_completed',
  'subagent_run_failed',
  'subagent_session_spawned',
  'subagent_session_message_sent',
  'subagent_announce_retry',
  'subagent_announce_giveup',
  'subagent_killed',
  'subagent_steered',
  'parallel_started',
  'parallel_completed',
  'chain_started',
  'chain_step_started',
  'chain_step_completed',
  'chain_completed',
  'background_launched',
];

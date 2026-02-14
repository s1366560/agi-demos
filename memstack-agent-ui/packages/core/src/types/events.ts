/**
 * memstack-agent-ui - Core Event Type Definitions
 *
 * Defines 50+ event types for Agent communication, organized by category:
 * - Agent events: Core agent lifecycle and execution
 * - HITL events: Human-in-the-loop interactions
 * - Sandbox events: Code execution environment
 * - System events: Platform-level notifications
 *
 * @packageDocumentation
 */

/**
 * Event type categories for routing and handling
 */
export type EventCategory = 'agent' | 'hitl' | 'sandbox' | 'system' | 'message';

/**
 * Complete union of all Agent event types
 *
 * Organized by functional area:
 * - Lifecycle: start, complete, error
 * - Thinking: thought, thought_delta
 * - Execution: act, act_delta, observe
 * - Messaging: message, text_start, text_delta, text_end
 * - HITL: permission/clarification/decision/env_var events
 * - Skills: skill_matched, skill_execution_*, skill_fallback
 * - Plan Mode: plan_* events
 * - Sandbox: sandbox_*, desktop_*, terminal_*
 * - SubAgent: subagent_*, parallel_*, chain_*
 * - Artifacts: artifact_*
 * - Tasks: task_*
 */
export type EventType =
  // Core Agent Lifecycle
  | 'start'
  | 'complete'
  | 'error'
  | 'status'
  | 'cancelled'
  | 'retry'

  // Thinking
  | 'thought'
  | 'thought_delta'

  // Execution
  | 'act'
  | 'act_delta'
  | 'observe'

  // Work/Task Planning
  | 'work_plan'
  | 'step_start'
  | 'step_end'
  | 'step_finish'

  // Messaging
  | 'message'
  | 'user_message'
  | 'assistant_message'
  | 'text_start'
  | 'text_delta'
  | 'text_end'

  // HITL - Permission
  | 'permission_asked'
  | 'permission_replied'

  // HITL - Clarification
  | 'clarification_asked'
  | 'clarification_answered'

  // HITL - Decision
  | 'decision_asked'
  | 'decision_answered'

  // HITL - Environment Variables
  | 'env_var_requested'
  | 'env_var_provided'

  // Doom Loop Detection
  | 'doom_loop_detected'
  | 'doom_loop_intervened'

  // Cost Tracking
  | 'cost_update'

  // Context Management
  | 'context_compressed'
  | 'context_status'
  | 'context_summary_generated'

  // Pattern Matching
  | 'pattern_match'

  // Skills (L2 Layer)
  | 'skill_matched'
  | 'skill_execution_start'
  | 'skill_tool_start'
  | 'skill_tool_result'
  | 'skill_execution_complete'
  | 'skill_fallback'

  // Plan Mode
  | 'plan_mode_enter'
  | 'plan_mode_exit'
  | 'plan_created'
  | 'plan_updated'
  | 'plan_suggested'
  | 'plan_exploration_started'
  | 'plan_exploration_completed'
  | 'plan_draft_created'
  | 'plan_approved'
  | 'plan_rejected'
  | 'plan_cancelled'
  | 'plan_status_changed'
  | 'plan_execution_start'
  | 'plan_execution_complete'
  | 'plan_step_ready'
  | 'plan_step_complete'
  | 'plan_step_skipped'
  | 'plan_snapshot_created'
  | 'plan_rollback'
  | 'reflection_complete'

  // Work Plans
  | 'workplan_created'
  | 'workplan_step_started'
  | 'workplan_step_completed'
  | 'workplan_step_failed'
  | 'workplan_completed'
  | 'workplan_failed'

  // Sandbox Lifecycle
  | 'sandbox_created'
  | 'sandbox_terminated'
  | 'sandbox_status'
  | 'sandbox_event'

  // Desktop
  | 'desktop_started'
  | 'desktop_stopped'
  | 'desktop_status'

  // Terminal
  | 'terminal_started'
  | 'terminal_stopped'
  | 'terminal_status'

  // Artifacts
  | 'artifact_created'
  | 'artifact_ready'
  | 'artifact_error'
  | 'artifacts_batch'
  | 'artifact_open'
  | 'artifact_update'
  | 'artifact_close'

  // Title Generation
  | 'title_generated'

  // Suggestions
  | 'suggestions'

  // SubAgent (L3 Layer)
  | 'subagent_routed'
  | 'subagent_started'
  | 'subagent_completed'
  | 'subagent_failed'

  // Parallel Execution
  | 'parallel_started'
  | 'parallel_completed'

  // Chain Execution
  | 'chain_started'
  | 'chain_step_started'
  | 'chain_step_completed'
  | 'chain_completed'

  // Background Tasks
  | 'background_launched'

  // Tasks
  | 'task_list_updated'
  | 'task_updated'
  | 'task_start'
  | 'task_complete';

/**
 * Event category mapping
 *
 * Maps each event type to its functional category.
 * Used for routing events to appropriate handlers.
 */
export const EVENT_CATEGORIES: Record<EventType, EventCategory> = {
  // Agent lifecycle
  start: 'agent',
  complete: 'agent',
  error: 'agent',
  status: 'agent',
  cancelled: 'agent',
  retry: 'agent',

  // Thinking
  thought: 'agent',
  thought_delta: 'agent',

  // Execution
  act: 'agent',
  act_delta: 'agent',
  observe: 'agent',

  // Work/Task Planning
  work_plan: 'agent',
  step_start: 'agent',
  step_end: 'agent',
  step_finish: 'agent',

  // Messaging
  message: 'message',
  user_message: 'message',
  assistant_message: 'message',
  text_start: 'message',
  text_delta: 'message',
  text_end: 'message',

  // HITL - Permission
  permission_asked: 'hitl',
  permission_replied: 'hitl',

  // HITL - Clarification
  clarification_asked: 'hitl',
  clarification_answered: 'hitl',

  // HITL - Decision
  decision_asked: 'hitl',
  decision_answered: 'hitl',

  // HITL - Environment Variables
  env_var_requested: 'hitl',
  env_var_provided: 'hitl',

  // Doom Loop Detection
  doom_loop_detected: 'agent',
  doom_loop_intervened: 'agent',

  // Cost Tracking
  cost_update: 'system',

  // Context Management
  context_compressed: 'system',
  context_status: 'system',
  context_summary_generated: 'system',

  // Pattern Matching
  pattern_match: 'agent',

  // Skills
  skill_matched: 'agent',
  skill_execution_start: 'agent',
  skill_tool_start: 'agent',
  skill_tool_result: 'agent',
  skill_execution_complete: 'agent',
  skill_fallback: 'agent',

  // Plan Mode
  plan_mode_enter: 'agent',
  plan_mode_exit: 'agent',
  plan_created: 'agent',
  plan_updated: 'agent',
  plan_suggested: 'agent',
  plan_exploration_started: 'agent',
  plan_exploration_completed: 'agent',
  plan_draft_created: 'agent',
  plan_approved: 'agent',
  plan_rejected: 'agent',
  plan_cancelled: 'agent',
  plan_status_changed: 'agent',
  plan_execution_start: 'agent',
  plan_execution_complete: 'agent',
  plan_step_ready: 'agent',
  plan_step_complete: 'agent',
  plan_step_skipped: 'agent',
  plan_snapshot_created: 'agent',
  plan_rollback: 'agent',
  reflection_complete: 'agent',

  // Work Plans
  workplan_created: 'agent',
  workplan_step_started: 'agent',
  workplan_step_completed: 'agent',
  workplan_step_failed: 'agent',
  workplan_completed: 'agent',
  workplan_failed: 'agent',

  // Sandbox
  sandbox_created: 'sandbox',
  sandbox_terminated: 'sandbox',
  sandbox_status: 'sandbox',
  sandbox_event: 'sandbox',

  // Desktop
  desktop_started: 'sandbox',
  desktop_stopped: 'sandbox',
  desktop_status: 'sandbox',

  // Terminal
  terminal_started: 'sandbox',
  terminal_stopped: 'sandbox',
  terminal_status: 'sandbox',

  // Artifacts
  artifact_created: 'agent',
  artifact_ready: 'agent',
  artifact_error: 'agent',
  artifacts_batch: 'agent',
  artifact_open: 'agent',
  artifact_update: 'agent',
  artifact_close: 'agent',

  // Title Generation
  title_generated: 'agent',

  // Suggestions
  suggestions: 'agent',

  // SubAgent
  subagent_routed: 'agent',
  subagent_started: 'agent',
  subagent_completed: 'agent',
  subagent_failed: 'agent',

  // Parallel Execution
  parallel_started: 'agent',
  parallel_completed: 'agent',

  // Chain Execution
  chain_started: 'agent',
  chain_step_started: 'agent',
  chain_step_completed: 'agent',
  chain_completed: 'agent',

  // Background Tasks
  background_launched: 'agent',

  // Tasks
  task_list_updated: 'agent',
  task_updated: 'agent',
  task_start: 'agent',
  task_complete: 'agent',
} as const;

/**
 * Check if an event type is a delta event (requires batching)
 *
 * Delta events are high-frequency updates that should be batched
 * for performance: text_delta, thought_delta, act_delta
 *
 * @param eventType - The event type to check
 * @returns true if this is a delta event
 */
export function isDeltaEvent(eventType: EventType): boolean {
  return (
    eventType === 'text_delta' ||
    eventType === 'thought_delta' ||
    eventType === 'act_delta'
  );
}

/**
 * Check if an event type is a terminal event
 *
 * Terminal events signal the end of a stream or operation:
 * complete, error, cancelled
 *
 * @param eventType - The event type to check
 * @returns true if this is a terminal event
 */
export function isTerminalEvent(eventType: EventType): boolean {
  return (
    eventType === 'complete' ||
    eventType === 'error' ||
    eventType === 'cancelled'
  );
}

/**
 * Check if an event type requires HITL interaction
 *
 * HITL events pause execution and require user input:
 * permission, clarification, decision, env_var
 *
 * @param eventType - The event type to check
 * @returns true if this event requires HITL
 */
export function isHITLEvent(eventType: EventType): boolean {
  const hitlEvents: EventType[] = [
    'permission_asked',
    'clarification_asked',
    'decision_asked',
    'env_var_requested',
  ];
  return hitlEvents.includes(eventType);
}

/**
 * Events that should trigger automatic saves
 *
 * These events indicate significant state changes that should persist
 */
export const SAVE_TRIGGER_EVENTS: Set<EventType> = new Set([
  'complete',
  'error',
  'cancelled',
  'user_message',
  'assistant_message',
  'artifact_created',
  'task_complete',
  'step_finish',
]);

/**
 * Events that should update the cost tracking display
 */
export const COST_UPDATE_EVENTS: Set<EventType> = new Set([
  'cost_update',
  'complete',
  'step_finish',
]);

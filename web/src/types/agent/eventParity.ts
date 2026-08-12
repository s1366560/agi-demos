import type { AgentEventType as CanonicalAgentEventType } from '../generated/eventTypes';

/**
 * Canonical backend events that do not have a purpose-built Web state handler.
 *
 * These events are still first-class timeline records: the message router sends
 * them to `onCanonicalEvent`, and the SSE adapter preserves their payload for
 * live/replay parity. Keeping this list explicit prevents the default router
 * branch from silently becoming a compatibility policy.
 */
export const CANONICAL_TIMELINE_EVENT_TYPES = [
  'a2ui_action_answered',
  'agent_conflict_marked',
  'agent_decision_logged',
  'agent_escalated',
  'agent_human_input_requested',
  'agent_progress_declared',
  'agent_supervisor_verdict',
  'agent_task_assigned',
  'agent_task_refused',
  'cancelled',
  'context_compacted',
  'context_summary_generated',
  'conversation_participant_joined',
  'conversation_participant_left',
  'desktop_status',
  'elicitation_answered',
  'elicitation_asked',
  'http_service_error',
  'http_service_started',
  'http_service_stopped',
  'http_service_updated',
  'progress',
  'run_input_applied',
  'session_forked',
  'session_merged',
  'start',
  'status',
  'subagent_announce_expired',
  'subagent_announce_received',
  'subagent_announce_sent',
  'subagent_delegation',
  'subagent_doom_loop',
  'subagent_orphan_detected',
  'subagent_retry',
  'subagent_spawn_rejected',
  'subagent_spawning',
  'task_execution_incident_opened',
  'task_execution_session_updated',
  'task_recovery_action_completed',
  'task_recovery_action_started',
  'terminal_status',
  'tools_updated',
  'workspace_adjudication_complete',
  'workspace_decomposition_complete',
  'workspace_goal_completed',
  'workspace_goal_materialized',
  'workspace_worker_dispatched',
  'workspace_worker_report_submitted',
] as const satisfies readonly CanonicalAgentEventType[];

export type CanonicalTimelineEventType = (typeof CANONICAL_TIMELINE_EVENT_TYPES)[number];

const canonicalTimelineEventTypeSet = new Set<string>(CANONICAL_TIMELINE_EVENT_TYPES);

export function isCanonicalTimelineEventType(value: string): value is CanonicalTimelineEventType {
  return canonicalTimelineEventTypeSet.has(value);
}

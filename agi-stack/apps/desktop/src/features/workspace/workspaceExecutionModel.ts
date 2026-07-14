import type { DesktopRunStatus, PlanSnapshot, WorkspaceTask } from '../../types';

export type WorkspaceExecutionSummary = {
  conversations: number;
  activeRuns: number;
  attentionRuns: number;
  taskTotal: number;
  completedTasks: number;
  pendingRequests: number;
  artifacts: number;
  deliveries: number;
};

const TERMINAL_RUN_STATES = new Set<DesktopRunStatus>(['completed', 'failed', 'cancelled']);
const ATTENTION_RUN_STATES = new Set<DesktopRunStatus>([
  'needs_input',
  'needs_approval',
  'failed',
  'disconnected',
  'interrupted',
]);
const COMPLETED_TASK_STATES = new Set(['done', 'closed', 'completed']);

export function summarizeWorkspaceExecution(
  tasks: WorkspaceTask[],
  plan: PlanSnapshot | null,
): WorkspaceExecutionSummary {
  const runs = Array.isArray(plan?.run_health) ? plan.run_health : [];
  return {
    conversations: arrayLength(plan?.conversation_plans),
    activeRuns: runs.filter((run) => !TERMINAL_RUN_STATES.has(run.status)).length,
    attentionRuns: runs.filter((run) => ATTENTION_RUN_STATES.has(run.status)).length,
    taskTotal: tasks.length,
    completedTasks: tasks.filter((task) =>
      COMPLETED_TASK_STATES.has((task.status ?? '').toLowerCase()),
    ).length,
    pendingRequests: arrayLength(plan?.pending_hitl),
    artifacts: arrayLength(plan?.artifact_index),
    deliveries: arrayLength(plan?.delivery),
  };
}

function arrayLength(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

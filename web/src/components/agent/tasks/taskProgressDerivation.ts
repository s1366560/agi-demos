/**
 * taskProgressDerivation — derive AgentProgressBar inputs from AgentTask[].
 *
 * Distilled from routa's `TaskProgressBar` model (apps/web): a single
 * always-visible compact strip that summarises "step N of M" for the user
 * while the agent is running.
 *
 * Pure function, framework-free, so it can be reused by tests and any
 * other surface that wants to show the same progress signal.
 */

import type { AgentTask } from '@/types/agent';

export type TaskProgressStatus =
  | 'thinking'
  | 'step_executing'
  | 'completed'
  | 'failed';

export interface TaskProgressSummary {
  /** 1-indexed current step (the in-progress task, or completed+1 if none). */
  current: number;
  /** Total number of tracked tasks. */
  total: number;
  /** Mapped status for AgentProgressBar. */
  status: TaskProgressStatus;
  /** Human label for the current step (the running or next pending task). */
  label?: string | undefined;
  /** True if there is anything worth showing (>=1 task). */
  hasTasks: boolean;
}

/**
 * Derive a progress summary from the conversation's task list and the
 * current streaming flag.
 *
 * Rules:
 * - No tasks → hasTasks=false (caller should hide the bar).
 * - Any task in_progress → status=step_executing, label=that task.
 * - Else if any task pending → status=thinking, label=next pending task.
 * - Else if any task failed → status=failed, label=last failed task.
 * - Else all completed → status=completed.
 * - When isStreaming is true and no in_progress/pending exists, fall back
 *   to thinking (agent is reasoning before producing the next task).
 */
export function deriveTaskProgress(
  tasks: readonly AgentTask[],
  isStreaming: boolean,
): TaskProgressSummary {
  const total = tasks.length;
  if (total === 0) {
    if (isStreaming) {
      return {
        current: 0,
        total: 0,
        status: 'thinking',
        label: undefined,
        hasTasks: false,
      };
    }
    return {
      current: 0,
      total: 0,
      status: 'completed',
      label: undefined,
      hasTasks: false,
    };
  }

  const ordered = [...tasks].sort((a, b) => a.order_index - b.order_index);

  const completedCount = ordered.filter((t) => t.status === 'completed').length;
  const inProgress = ordered.find((t) => t.status === 'in_progress');
  const nextPending = ordered.find((t) => t.status === 'pending');
  const lastFailed = [...ordered].reverse().find((t) => t.status === 'failed');

  if (inProgress) {
    const idx = ordered.indexOf(inProgress) + 1;
    return {
      current: idx,
      total,
      status: 'step_executing',
      label: inProgress.content,
      hasTasks: true,
    };
  }

  if (nextPending) {
    const idx = ordered.indexOf(nextPending) + 1;
    return {
      current: idx,
      total,
      status: isStreaming ? 'thinking' : 'step_executing',
      label: nextPending.content,
      hasTasks: true,
    };
  }

  if (lastFailed && completedCount < total) {
    return {
      current: ordered.indexOf(lastFailed) + 1,
      total,
      status: 'failed',
      label: lastFailed.content,
      hasTasks: true,
    };
  }

  return {
    current: total,
    total,
    status: 'completed',
    label: undefined,
    hasTasks: true,
  };
}

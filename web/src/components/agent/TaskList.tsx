/**
 * TaskList - Displays the agent's task checklist for a conversation
 *
 * Renders tasks streamed via SSE from the agent's todowrite tool.
 * Shows task status (pending/in_progress/completed/failed/cancelled)
 * with a progress summary bar.
 */

import { memo, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { CheckCircle2, Circle, Loader2, XCircle, Ban } from 'lucide-react';

import type { AgentTask, TaskStatus } from '@/types/agent';

export interface TaskListProps {
  tasks: AgentTask[];
}

const STATUS_CONFIG: Record<TaskStatus, { icon: typeof Circle; color: string; labelKey: string }> =
  {
    pending: {
      icon: Circle,
      color: 'text-slate-400 dark:text-slate-500',
      labelKey: 'agent.taskList.status.pending',
    },
    in_progress: {
      icon: Loader2,
      color: 'text-blue-500 dark:text-blue-400',
      labelKey: 'agent.taskList.status.inProgress',
    },
    completed: {
      icon: CheckCircle2,
      color: 'text-emerald-500 dark:text-emerald-400',
      labelKey: 'agent.taskList.status.completed',
    },
    failed: {
      icon: XCircle,
      color: 'text-red-500 dark:text-red-400',
      labelKey: 'agent.taskList.status.failed',
    },
    cancelled: {
      icon: Ban,
      color: 'text-slate-400 dark:text-slate-500',
      labelKey: 'agent.taskList.status.cancelled',
    },
  };

const PRIORITY_DOT: Record<string, string> = {
  high: 'bg-red-400',
  medium: 'bg-amber-400',
  low: 'bg-slate-300 dark:bg-slate-600',
};

const TaskItem = memo<{ task: AgentTask }>(({ task }) => {
  const { t } = useTranslation();
  const config = STATUS_CONFIG[task.status];
  const Icon = config.icon;
  const isCompleted = task.status === 'completed';
  const isActive = task.status === 'in_progress';

  return (
    <div
      className={`flex items-start gap-2.5 px-3 py-2 rounded-lg transition-colors ${
        isActive
          ? 'bg-blue-50/60 dark:bg-blue-900/15'
          : 'hover:bg-slate-50 dark:hover:bg-slate-800/40'
      }`}
    >
      <div
        className={`mt-0.5 flex-shrink-0 ${config.color}`}
        role="img"
        aria-label={t(config.labelKey, {
          defaultValue: task.status.replace(/_/g, ' '),
        })}
      >
        <Icon size={16} className={isActive ? 'animate-spin motion-reduce:animate-none' : ''} />
      </div>
      <div className="flex-1 min-w-0">
        <p
          className={`text-sm leading-snug ${
            isCompleted
              ? 'line-through text-slate-400 dark:text-slate-500'
              : 'text-slate-700 dark:text-slate-200'
          }`}
        >
          {task.content}
        </p>
      </div>
      {task.priority !== 'medium' && (
        <div
          className={`w-1.5 h-1.5 rounded-full mt-1.5 flex-shrink-0 ${PRIORITY_DOT[task.priority] || ''}`}
          role="img"
          aria-label={t('agent.taskList.priorityTitle', {
            defaultValue: '{{priority}} priority',
            priority: task.priority,
          })}
          title={t('agent.taskList.priorityTitle', {
            defaultValue: '{{priority}} priority',
            priority: task.priority,
          })}
        />
      )}
    </div>
  );
});

TaskItem.displayName = 'TaskItem';

export const TaskList = memo<TaskListProps>(({ tasks }) => {
  const { t } = useTranslation();
  const stats = useMemo(() => {
    const total = tasks.length;
    const completed = tasks.filter((t) => t.status === 'completed').length;
    const failed = tasks.filter((t) => t.status === 'failed').length;
    const active = tasks.filter((t) => t.status === 'in_progress').length;
    const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
    return { total, completed, failed, active, pct };
  }, [tasks]);

  if (tasks.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-12 px-4">
        <Circle size={32} className="text-slate-300 dark:text-slate-600 mb-3" />
        <p className="text-sm text-slate-500 dark:text-slate-400 text-center">
          {t('agent.taskList.empty', {
            defaultValue:
              'No tasks yet. The agent will create tasks when working on complex requests.',
          })}
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Progress bar */}
      <div className="px-4 py-3 border-b border-slate-200/60 dark:border-slate-700/50">
        <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 mb-1.5">
          <span>
            {t('agent.taskList.completedSummary', {
              defaultValue: '{{completed}}/{{total}} completed',
              completed: stats.completed,
              total: stats.total,
            })}
          </span>
          <span>{stats.pct}%</span>
        </div>
        <div className="h-1.5 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-emerald-500 dark:bg-emerald-400 rounded-full transition-[width] duration-500"
            style={{ width: `${String(stats.pct)}%` }}
          />
        </div>
        {stats.active > 0 && (
          <p className="text-xs text-blue-500 dark:text-blue-400 mt-1">
            {t('agent.taskList.activeSummary', {
              defaultValue: '{{count}} task in progress',
              count: stats.active,
            })}
          </p>
        )}
      </div>

      {/* Task list */}
      <div className="flex-1 overflow-y-auto py-1">
        {tasks.map((task) => (
          <TaskItem key={task.id} task={task} />
        ))}
      </div>
    </div>
  );
});

TaskList.displayName = 'TaskList';

export default TaskList;

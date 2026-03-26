/**
 * TaskItems - Task start/complete timeline markers
 */

import { memo } from 'react';

import { useTranslation } from 'react-i18next';

import { TimeBadge } from './shared';

import type { TimelineEvent } from '../../../types/agent';

interface TaskStartItemProps {
  event: TimelineEvent;
}

export const TaskStartItem = memo(
  function TaskStartItem({ event }: TaskStartItemProps) {
    const { t } = useTranslation();
    if (event.type !== 'task_start') return null;
    const e = event;
    return (
      <div className="flex flex-col gap-1">
        <div className="flex items-start gap-3 my-2.5">
          <div className="w-7 h-7 rounded-full bg-blue-100 dark:bg-blue-900/40 flex items-center justify-center shrink-0 mt-0.5">
            <span className="material-symbols-outlined text-blue-600 dark:text-blue-400 text-xs">
              task_alt
            </span>
          </div>
          <div className="flex-1 min-w-0 bg-white dark:bg-slate-800/80 border border-slate-200/80 dark:border-slate-700/70 rounded-xl px-3 py-2 shadow-sm">
            <div className="text-sm font-medium text-blue-700 dark:text-blue-300">
              {t('agent.timeline.taskProgress', 'Task {{current}}/{{total}}', {
                current: e.orderIndex + 1,
                total: e.totalTasks,
              })}
            </div>
            <div className="text-sm text-slate-600 dark:text-slate-400 mt-0.5 break-words [overflow-wrap:anywhere]">
              {e.content}
            </div>
          </div>
        </div>
        <div className="pl-10">
          <TimeBadge timestamp={event.timestamp} />
        </div>
      </div>
    );
  },
  (prev, next) => {
    return prev.event.id === next.event.id && prev.event.type === next.event.type;
  }
);

interface TaskCompleteItemProps {
  event: TimelineEvent;
}

export const TaskCompleteItem = memo(
  function TaskCompleteItem({ event }: TaskCompleteItemProps) {
    const { t } = useTranslation();
    if (event.type !== 'task_complete') return null;
    const e = event;
    const isSuccess = e.status === 'completed';
    return (
      <div className="flex items-start gap-3 my-2 opacity-80">
        <div
          className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
            isSuccess ? 'bg-green-100 dark:bg-green-900/30' : 'bg-red-100 dark:bg-red-900/30'
          }`}
        >
          <span
            className={`material-symbols-outlined text-xs ${
              isSuccess ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'
            }`}
          >
            {isSuccess ? 'check_circle' : 'cancel'}
          </span>
        </div>
        <div className="flex-1 min-w-0 text-sm text-slate-500 dark:text-slate-400 pt-1 break-words [overflow-wrap:anywhere] bg-white/70 dark:bg-slate-800/60 border border-slate-200/70 dark:border-slate-700/60 rounded-xl px-3 py-2">
          {t('agent.timeline.taskStatus', 'Task {{current}}/{{total}} {{status}}', {
            current: e.orderIndex + 1,
            total: e.totalTasks,
            status: isSuccess ? t('agent.timeline.taskCompleted', 'completed') : e.status,
          })}
        </div>
      </div>
    );
  },
  (prev, next) => {
    return prev.event.id === next.event.id && prev.event.type === next.event.type;
  }
);

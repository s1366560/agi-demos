/**
 * TaskProgressStrip — collapsible progress strip for the active conversation.
 *
 * Distilled from routa's `task-progress-bar.tsx`. Renders a single-line pill
 * showing "Todos (done/total) · {currentTitle}" when collapsed; expanding
 * reveals the full TaskList. Designed to live above the chat input so the
 * user can keep an eye on progress without losing the message thread.
 *
 * Pure derivation: counts and current item come from `tasks` directly.
 */

import { memo, useMemo, useState } from 'react';

import { ChevronDown, ChevronUp, ListChecks } from 'lucide-react';

import type { AgentTask, TaskStatus } from '@/types/agent';

import { TaskList } from './TaskList';

export interface TaskProgressStripProps {
  tasks: AgentTask[];
  defaultExpanded?: boolean;
  className?: string;
}

interface TaskCounts {
  total: number;
  completed: number;
  active: AgentTask | null;
}

function deriveCounts(tasks: AgentTask[]): TaskCounts {
  if (tasks.length === 0) {
    return { total: 0, completed: 0, active: null };
  }
  let completed = 0;
  let active: AgentTask | null = null;
  for (const task of tasks) {
    const status: TaskStatus = task.status;
    if (status === 'completed') {
      completed += 1;
    } else if (status === 'in_progress' && active === null) {
      active = task;
    }
  }
  if (active === null) {
    // Fall back to first non-terminal task as the "current" one.
    active =
      tasks.find((t) => t.status === 'pending' || t.status === 'in_progress') ?? null;
  }
  return { total: tasks.length, completed, active };
}

export const TaskProgressStrip = memo<TaskProgressStripProps>(
  ({ tasks, defaultExpanded = false, className = '' }) => {
    const [expanded, setExpanded] = useState(defaultExpanded);
    const counts = useMemo(() => deriveCounts(tasks), [tasks]);

    if (counts.total === 0) {
      return null;
    }

    const Caret = expanded ? ChevronUp : ChevronDown;
    const label = counts.active?.content ?? 'All tasks complete';

    return (
      <div
        className={`rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 ${className}`}
      >
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          aria-controls="task-progress-strip-list"
          className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors rounded-lg"
        >
          <ListChecks size={16} className="text-slate-500 dark:text-slate-400 flex-shrink-0" />
          <span className="text-xs font-medium text-slate-600 dark:text-slate-300 flex-shrink-0">
            Todos ({counts.completed}/{counts.total})
          </span>
          <span className="text-xs text-slate-500 dark:text-slate-400 truncate flex-1">
            {label}
          </span>
          <Caret size={14} className="text-slate-400 dark:text-slate-500 flex-shrink-0" />
        </button>
        {expanded && (
          <div id="task-progress-strip-list" className="border-t border-slate-200 dark:border-slate-700 p-2">
            <TaskList tasks={tasks} />
          </div>
        )}
      </div>
    );
  }
);

TaskProgressStrip.displayName = 'TaskProgressStrip';

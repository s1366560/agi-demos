/**
 * TaskLanePanel - Kanban-style alternative to the flat TaskList.
 *
 * Groups tasks by status into lanes (Backlog / In Progress / Done / Blocked),
 * with per-lane collapse persisted in localStorage keyed by conversation id.
 *
 * Reuses the same status palette as TaskList so both views feel cohesive.
 */

import { memo, useCallback, useEffect, useMemo, useState } from 'react';

import { Ban, CheckCircle2, ChevronDown, ChevronRight, Circle, Loader2, XCircle } from 'lucide-react';

import type { AgentTask, TaskStatus } from '@/types/agent';

interface TaskLanePanelProps {
  tasks: AgentTask[];
  conversationId?: string | undefined;
}

type LaneKey = 'in_progress' | 'pending' | 'completed' | 'failed';

interface LaneDef {
  key: LaneKey;
  label: string;
  statuses: TaskStatus[];
  icon: typeof Circle;
  color: string;
  accent: string;
}

const LANES: LaneDef[] = [
  {
    key: 'in_progress',
    label: 'In progress',
    statuses: ['in_progress'],
    icon: Loader2,
    color: 'text-blue-500 dark:text-blue-400',
    accent: 'bg-blue-500/80',
  },
  {
    key: 'pending',
    label: 'Backlog',
    statuses: ['pending'],
    icon: Circle,
    color: 'text-slate-400 dark:text-slate-500',
    accent: 'bg-slate-400/70',
  },
  {
    key: 'completed',
    label: 'Done',
    statuses: ['completed'],
    icon: CheckCircle2,
    color: 'text-emerald-500 dark:text-emerald-400',
    accent: 'bg-emerald-500/80',
  },
  {
    key: 'failed',
    label: 'Blocked',
    statuses: ['failed', 'cancelled'],
    icon: XCircle,
    color: 'text-rose-500 dark:text-rose-400',
    accent: 'bg-rose-500/80',
  },
];

const STATUS_ICON: Record<TaskStatus, { icon: typeof Circle; color: string }> = {
  pending: { icon: Circle, color: 'text-slate-400 dark:text-slate-500' },
  in_progress: { icon: Loader2, color: 'text-blue-500 dark:text-blue-400' },
  completed: { icon: CheckCircle2, color: 'text-emerald-500 dark:text-emerald-400' },
  failed: { icon: XCircle, color: 'text-rose-500 dark:text-rose-400' },
  cancelled: { icon: Ban, color: 'text-slate-400 dark:text-slate-500' },
};

const PRIORITY_DOT: Record<string, string> = {
  high: 'bg-red-400',
  medium: 'bg-amber-400',
  low: 'bg-slate-300 dark:bg-slate-600',
};

const COLLAPSE_STORAGE_PREFIX = 'memstack:taskLanes:collapsed:';

function loadCollapsed(conversationId: string | undefined): Record<LaneKey, boolean> {
  const empty = { in_progress: false, pending: false, completed: true, failed: false } as Record<
    LaneKey,
    boolean
  >;
  if (!conversationId || typeof window === 'undefined') return empty;
  try {
    const raw = window.localStorage.getItem(COLLAPSE_STORAGE_PREFIX + conversationId);
    if (!raw) return empty;
    const parsed = JSON.parse(raw) as Partial<Record<LaneKey, boolean>>;
    return { ...empty, ...parsed };
  } catch {
    return empty;
  }
}

const LaneTaskRow = memo<{ task: AgentTask }>(({ task }) => {
  const cfg = STATUS_ICON[task.status] ?? STATUS_ICON.pending;
  const Icon = cfg.icon;
  const isActive = task.status === 'in_progress';
  const isDone = task.status === 'completed';
  return (
    <li
      className={`flex items-start gap-2 rounded-md border border-slate-200/70 bg-white px-2.5 py-2 transition-colors hover:border-slate-300 dark:border-slate-700/60 dark:bg-slate-900/40 dark:hover:border-slate-600 ${
        isActive ? 'ring-1 ring-blue-200 dark:ring-blue-900/50' : ''
      }`}
    >
      <span className={`mt-0.5 shrink-0 ${cfg.color}`}>
        <Icon size={14} className={isActive ? 'animate-spin motion-reduce:animate-none' : ''} />
      </span>
      <span
        className={`min-w-0 flex-1 text-xs leading-snug ${
          isDone
            ? 'text-slate-400 line-through dark:text-slate-500'
            : 'text-slate-700 dark:text-slate-200'
        }`}
      >
        {task.content}
      </span>
      {task.priority !== 'medium' ? (
        <span
          className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${PRIORITY_DOT[task.priority] ?? ''}`}
          title={`${task.priority} priority`}
        />
      ) : null}
    </li>
  );
});
LaneTaskRow.displayName = 'LaneTaskRow';

export const TaskLanePanel = memo<TaskLanePanelProps>(({ tasks, conversationId }) => {
  const [collapsed, setCollapsed] = useState<Record<LaneKey, boolean>>(() =>
    loadCollapsed(conversationId)
  );

  // Reload when conversation switches
  useEffect(() => {
    setCollapsed(loadCollapsed(conversationId));
  }, [conversationId]);

  // Persist on change
  useEffect(() => {
    if (!conversationId || typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(
        COLLAPSE_STORAGE_PREFIX + conversationId,
        JSON.stringify(collapsed)
      );
    } catch {
      // ignore quota errors
    }
  }, [collapsed, conversationId]);

  const toggle = useCallback((key: LaneKey) => {
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const lanes = useMemo(() => {
    const allowed = new Set<TaskStatus>(LANES.flatMap((l) => l.statuses));
    return LANES.map((lane) => ({
      ...lane,
      tasks: tasks
        .filter((t) => lane.statuses.includes(t.status))
        .sort((a, b) => a.order_index - b.order_index),
    })).concat(
      // Catch-all bucket if any unknown status sneaks in (forward-compat)
      tasks.some((t) => !allowed.has(t.status))
        ? [
            {
              key: 'pending' as LaneKey,
              label: 'Other',
              statuses: [] as TaskStatus[],
              icon: Circle,
              color: 'text-slate-400 dark:text-slate-500',
              accent: 'bg-slate-400/70',
              tasks: tasks.filter((t) => !allowed.has(t.status)),
            },
          ]
        : []
    );
  }, [tasks]);

  const total = tasks.length;
  const completed = tasks.filter((t) => t.status === 'completed').length;
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;

  if (total === 0) {
    return (
      <div className="flex flex-col items-center justify-center px-4 py-12">
        <Circle size={32} className="mb-3 text-slate-300 dark:text-slate-600" />
        <p className="text-center text-sm text-slate-500 dark:text-slate-400">
          No tasks yet. The agent will create lanes when working on complex requests.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-slate-200/60 px-4 py-3 dark:border-slate-700/50">
        <div className="mb-1.5 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
          <span>
            {completed}/{total} done
          </span>
          <span>{pct}%</span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
          <div
            className="h-full rounded-full bg-emerald-500 transition-[width] duration-500 dark:bg-emerald-400"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {lanes.map((lane) => {
          const isCollapsed = collapsed[lane.key];
          return (
            <section
              key={lane.key + lane.label}
              className="rounded-md border border-slate-200/70 bg-slate-50/50 dark:border-slate-700/60 dark:bg-slate-900/30"
            >
              <button
                type="button"
                onClick={() => {
                  toggle(lane.key);
                }}
                className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left"
                aria-expanded={!isCollapsed}
              >
                <span className="text-slate-400 dark:text-slate-500">
                  {isCollapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
                </span>
                <span className={`h-1.5 w-1.5 rounded-full ${lane.accent}`} />
                <span className="text-xs font-semibold uppercase tracking-[0.1em] text-slate-600 dark:text-slate-300">
                  {lane.label}
                </span>
                <span className="ml-auto rounded bg-slate-200/80 px-1.5 py-0.5 text-[10px] font-mono text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {lane.tasks.length}
                </span>
              </button>
              {!isCollapsed ? (
                lane.tasks.length === 0 ? (
                  <p className="px-3 pb-2 text-[11px] text-slate-400 dark:text-slate-500">
                    Empty.
                  </p>
                ) : (
                  <ul className="space-y-1.5 p-2 pt-0">
                    {lane.tasks.map((task) => (
                      <LaneTaskRow key={task.id} task={task} />
                    ))}
                  </ul>
                )
              ) : null}
            </section>
          );
        })}
      </div>
    </div>
  );
});
TaskLanePanel.displayName = 'TaskLanePanel';

export default TaskLanePanel;

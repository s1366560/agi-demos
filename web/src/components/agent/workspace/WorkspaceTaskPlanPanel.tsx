import { memo } from 'react';

import { useTranslation } from 'react-i18next';

import { AlertCircle, CheckCircle2, Circle, GitBranch, Loader2 } from 'lucide-react';

import {
  calculateWorkspacePlanCompletionRatio,
  getWorkspacePlanCompletionCounts,
} from '@/components/blackboard/blackboardUtils';

import type { WorkspacePlanSnapshot, WorkspaceTaskStatus } from '@/types/workspace';

import type { WorkspaceTaskPanelView, WorkspaceTaskPlanRow } from './WorkspaceTaskPlanPanelModel';
import type { TFunction } from 'i18next';

const WORKSPACE_STATUS_CONFIG: Record<
  WorkspaceTaskStatus,
  { icon: typeof Circle; label: string; color: string; bar: string }
> = {
  in_progress: {
    icon: Loader2,
    label: 'In progress',
    color: 'text-blue-500 dark:text-blue-400',
    bar: 'bg-blue-500 dark:bg-blue-400',
  },
  todo: {
    icon: Circle,
    label: 'Todo',
    color: 'text-slate-400 dark:text-slate-500',
    bar: 'bg-slate-300 dark:bg-slate-600',
  },
  blocked: {
    icon: AlertCircle,
    label: 'Blocked',
    color: 'text-amber-600 dark:text-amber-400',
    bar: 'bg-amber-500 dark:bg-amber-400',
  },
  done: {
    icon: CheckCircle2,
    label: 'Done',
    color: 'text-emerald-500 dark:text-emerald-400',
    bar: 'bg-emerald-500 dark:bg-emerald-400',
  },
};

const WORKSPACE_LANE_ORDER: WorkspaceTaskStatus[] = ['in_progress', 'todo', 'blocked', 'done'];

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

function workspacePlanTitle(snapshot: WorkspacePlanSnapshot | null, t: TFunction): string {
  const rootNode = snapshot?.plan?.nodes.find((node) => node.kind === 'goal');
  return (
    snapshot?.root_goal?.title ||
    rootNode?.title ||
    tFallback(t, 'agent.rightPanel.workspacePlan.untitledPlan', 'Workspace plan')
  );
}

function formatWorkspaceTimestamp(value: string | null | undefined, locale: string): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function planTaskStats(snapshot: WorkspacePlanSnapshot | null) {
  if (!snapshot?.plan) {
    return { total: 0, done: 0, completion: 0 };
  }

  const counts = getWorkspacePlanCompletionCounts(snapshot.plan, snapshot.root_goal ?? null);
  return {
    total: counts.totalTasks,
    done: counts.completedTasks,
    completion: calculateWorkspacePlanCompletionRatio(snapshot.plan, snapshot.root_goal ?? null),
  };
}

interface WorkspaceTaskPlanPanelProps {
  rows: WorkspaceTaskPlanRow[];
  snapshot: WorkspacePlanSnapshot | null;
  loading: boolean;
  error: string | null;
  view: WorkspaceTaskPanelView;
}

const WorkspaceTaskPlanRowItem = memo<{ row: WorkspaceTaskPlanRow; locale: string }>(
  ({ row, locale }) => {
    const { t } = useTranslation();
    const config = WORKSPACE_STATUS_CONFIG[row.status];
    const Icon = config.icon;
    const isActive = row.status === 'in_progress';
    const timestamp = formatWorkspaceTimestamp(row.updatedAt, locale);
    const sourceLabel =
      row.source === 'task'
        ? tFallback(t, 'agent.rightPanel.workspacePlan.sourceTask', 'Task')
        : row.kind === 'verify'
          ? tFallback(t, 'agent.rightPanel.workspacePlan.sourceVerify', 'Verify')
          : tFallback(t, 'agent.rightPanel.workspacePlan.sourcePlan', 'Plan');

    return (
      <div
        data-testid={`workspace-task-plan-row-${row.entityId}`}
        data-current-workspace-task={row.isCurrent ? 'true' : 'false'}
        className={`rounded-md border px-3 py-2.5 transition-colors ${
          row.isCurrent
            ? 'border-amber-300 bg-amber-50/70 ring-1 ring-amber-200 dark:border-amber-500/70 dark:bg-amber-500/10 dark:ring-amber-500/25'
            : 'border-slate-200/70 bg-white hover:border-slate-300 dark:border-slate-700/60 dark:bg-slate-900/35 dark:hover:border-slate-600'
        }`}
      >
        <div className="flex items-start gap-2.5">
          <span className={`mt-0.5 shrink-0 ${config.color}`}>
            <Icon size={15} className={isActive ? 'animate-spin motion-reduce:animate-none' : ''} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <p className="min-w-0 flex-1 truncate text-sm font-medium leading-snug text-slate-800 dark:text-slate-100">
                {row.title}
              </p>
              {timestamp ? (
                <span className="shrink-0 text-[11px] text-slate-400 dark:text-slate-500">
                  {timestamp}
                </span>
              ) : null}
            </div>
            {row.description ? (
              <p className="mt-1 line-clamp-2 text-xs leading-snug text-slate-500 dark:text-slate-400">
                {row.description}
              </p>
            ) : null}
            <div className="mt-2 flex min-w-0 items-center gap-1.5 text-[11px] text-slate-500 dark:text-slate-400">
              <span className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-medium uppercase tracking-[0.08em] text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300">
                {t(`agent.rightPanel.workspacePlan.status.${row.status}`, {
                  defaultValue: config.label,
                })}
              </span>
              <span className="rounded border border-slate-200 bg-white px-1.5 py-0.5 dark:border-slate-700 dark:bg-slate-900">
                {sourceLabel}
              </span>
              {row.attemptId ? (
                <span className="min-w-0 truncate font-mono text-slate-400">
                  {row.attemptId.slice(0, 8)}
                </span>
              ) : null}
              {row.isCurrent ? (
                <span className="ml-auto rounded bg-amber-100 px-1.5 py-0.5 font-medium text-amber-700 dark:bg-amber-500/15 dark:text-amber-300">
                  {tFallback(t, 'agent.rightPanel.workspacePlan.current', 'Current')}
                </span>
              ) : null}
            </div>
            {typeof row.progressPercent === 'number' ? (
              <div className="mt-2 h-1 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                <div
                  className={`h-full rounded-full transition-[width] duration-500 ${config.bar}`}
                  style={{ width: `${String(Math.max(0, Math.min(100, row.progressPercent)))}%` }}
                />
              </div>
            ) : null}
          </div>
        </div>
      </div>
    );
  }
);

WorkspaceTaskPlanRowItem.displayName = 'WorkspaceTaskPlanRowItem';

export const WorkspaceTaskPlanPanel = memo<WorkspaceTaskPlanPanelProps>(
  ({ rows, snapshot, loading, error, view }) => {
    const { t, i18n } = useTranslation();
    const stats = planTaskStats(snapshot);
    const hasPlan = Boolean(snapshot?.plan);
    const locale = i18n.language || 'en';

    if (!loading && rows.length === 0 && !hasPlan) {
      return (
        <div className="flex flex-col items-center justify-center px-4 py-12">
          <Circle size={32} className="mb-3 text-slate-300 dark:text-slate-600" />
          <p className="text-center text-sm text-slate-500 dark:text-slate-400">
            {t('agent.rightPanel.workspacePlan.empty', {
              defaultValue:
                'No workspace tasks or plan yet. They will appear here when the workspace starts execution.',
            })}
          </p>
        </div>
      );
    }

    return (
      <div className="flex h-full flex-col">
        <div className="border-b border-slate-200/60 px-4 py-3 dark:border-slate-700/50">
          <div className="flex items-start gap-2.5">
            <GitBranch size={15} className="mt-0.5 shrink-0 text-slate-500 dark:text-slate-400" />
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2">
                <p className="min-w-0 flex-1 truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
                  {workspacePlanTitle(snapshot, t)}
                </p>
                {snapshot?.plan?.status ? (
                  <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em] text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                    {snapshot.plan.status}
                  </span>
                ) : null}
              </div>
              <div className="mt-1 flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
                <span>
                  {t('agent.rightPanel.workspacePlan.planSummary', {
                    defaultValue: '{{done}}/{{total}} plan nodes done',
                    done: stats.done,
                    total: stats.total,
                  })}
                </span>
                {error ? (
                  <span className="text-amber-600 dark:text-amber-400">
                    {tFallback(t, 'agent.rightPanel.workspacePlan.partial', 'Partial')}
                  </span>
                ) : loading ? (
                  <span>{tFallback(t, 'agent.rightPanel.workspacePlan.loading', 'Loading')}</span>
                ) : (
                  <span>{stats.completion}%</span>
                )}
              </div>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
                <div
                  className="h-full rounded-full bg-emerald-500 transition-[width] duration-500 dark:bg-emerald-400"
                  style={{ width: `${String(stats.completion)}%` }}
                />
              </div>
            </div>
          </div>
        </div>

        {view === 'lanes' ? (
          <div className="flex-1 space-y-3 overflow-y-auto p-3">
            {WORKSPACE_LANE_ORDER.map((status) => {
              const config = WORKSPACE_STATUS_CONFIG[status];
              const laneRows = rows.filter((row) => row.status === status);
              return (
                <section
                  key={status}
                  className="rounded-md border border-slate-200/70 bg-slate-50/50 dark:border-slate-700/60 dark:bg-slate-900/30"
                >
                  <div className="flex items-center gap-2 px-2.5 py-1.5">
                    <span className={`h-1.5 w-1.5 rounded-full ${config.bar}`} />
                    <span className="text-xs font-semibold uppercase tracking-[0.1em] text-slate-600 dark:text-slate-300">
                      {t(`agent.rightPanel.workspacePlan.status.${status}`, {
                        defaultValue: config.label,
                      })}
                    </span>
                    <span className="ml-auto rounded bg-slate-200/80 px-1.5 py-0.5 text-[10px] font-mono text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                      {laneRows.length}
                    </span>
                  </div>
                  {laneRows.length === 0 ? (
                    <p className="px-3 pb-2 text-[11px] text-slate-400 dark:text-slate-500">
                      {t('agent.rightPanel.workspacePlan.emptyLane', { defaultValue: 'Empty.' })}
                    </p>
                  ) : (
                    <div className="space-y-1.5 p-2 pt-0">
                      {laneRows.map((row) => (
                        <WorkspaceTaskPlanRowItem key={row.id} row={row} locale={locale} />
                      ))}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        ) : (
          <div className="flex-1 space-y-2 overflow-y-auto p-3">
            {rows.map((row) => (
              <WorkspaceTaskPlanRowItem key={row.id} row={row} locale={locale} />
            ))}
          </div>
        )}
      </div>
    );
  }
);

WorkspaceTaskPlanPanel.displayName = 'WorkspaceTaskPlanPanel';

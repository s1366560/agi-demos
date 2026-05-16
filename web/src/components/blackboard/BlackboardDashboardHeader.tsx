import { useMemo } from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  MessageSquare,
  Radio,
  Target,
  Users,
} from 'lucide-react';

import { SensingSurfaceBadge } from './SensingSurfaceBadge';

import type { Workspace } from '@/types/workspace';

import type { BlackboardStats } from './blackboardUtils';
import type { LucideIcon } from 'lucide-react';

export interface BlackboardDashboardHeaderProps {
  selectedWorkspace: Workspace | null;
  workspaces: Workspace[];
  selectedWorkspaceId: string | null;
  workspaceUseCaseLabel: string;
  collaborationModeLabel: string;
  stats: BlackboardStats;
  agentWorkspacePath: string;
  onWorkspaceChange: (workspaceId: string | null) => void;
}

interface DashboardMetric {
  key: string;
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
  tone: 'neutral' | 'success' | 'warning' | 'danger' | 'info';
}

const metricToneClass: Record<DashboardMetric['tone'], string> = {
  neutral: 'text-text-secondary dark:text-text-muted',
  success: 'text-status-text-success dark:text-status-text-success-dark',
  warning: 'text-status-text-warning dark:text-status-text-warning-dark',
  danger: 'text-status-text-error dark:text-status-text-error-dark',
  info: 'text-status-text-info dark:text-status-text-info-dark',
};

export function BlackboardDashboardHeader({
  selectedWorkspace,
  workspaces,
  selectedWorkspaceId,
  workspaceUseCaseLabel,
  collaborationModeLabel,
  stats,
  agentWorkspacePath,
  onWorkspaceChange,
}: BlackboardDashboardHeaderProps) {
  const { t } = useTranslation();
  const metrics = useMemo<DashboardMetric[]>(
    () => [
      {
        key: 'completion',
        icon: CheckCircle2,
        label: t('blackboard.summary.completion', 'Completion'),
        value: `${String(stats.completionRatio)}%`,
        detail: t('blackboard.completionSummary', {
          done: stats.completedTasks,
          total: stats.totalTasks,
        }),
        tone: stats.completionRatio >= 100 ? 'success' : 'info',
      },
      {
        key: 'tasks',
        icon: Target,
        label: t('blackboard.summary.tasks', 'Tasks'),
        value: String(stats.totalTasks),
        detail: t('blackboard.summaryTaskMix', '{{todo}} todo · {{running}} running', {
          todo: stats.todoTasks,
          running: stats.inProgressTasks,
        }),
        tone: 'neutral',
      },
      {
        key: 'running',
        icon: Activity,
        label: t('blackboard.summary.runningTasks', 'Running'),
        value: String(stats.inProgressTasks),
        detail: t('blackboard.summaryBlockedTasks', '{{count}} blocked', {
          count: stats.blockedTasks,
        }),
        tone: stats.inProgressTasks > 0 ? 'info' : 'neutral',
      },
      {
        key: 'blocked',
        icon: AlertTriangle,
        label: t('blackboard.summary.blockedTasks', 'Blocked'),
        value: String(stats.blockedTasks),
        detail: t('blackboard.summary.pendingAdjudication', '{{count}} pending review', {
          count: stats.pendingAdjudicationTasks,
        }),
        tone: stats.blockedTasks > 0 ? 'danger' : 'neutral',
      },
      {
        key: 'agents',
        icon: Users,
        label: t('blackboard.summary.activeAgents', 'Active agents'),
        value: String(stats.activeAgents),
        detail: t('blackboard.summary.humanSeats', '{{count}} human seats', {
          count: stats.humanSeats,
        }),
        tone: stats.activeAgents > 0 ? 'success' : 'neutral',
      },
      {
        key: 'threads',
        icon: MessageSquare,
        label: t('blackboard.summary.openThreads', 'Open threads'),
        value: String(stats.openPosts),
        detail: t('blackboard.boardSummaryLine', {
          posts: stats.discussions,
          pinned: stats.pinnedPosts,
        }),
        tone: stats.openPosts > 0 ? 'warning' : 'neutral',
      },
    ],
    [stats, t]
  );

  return (
    <header className="border-b border-border-light bg-surface-light dark:border-border-dark dark:bg-surface-dark">
      <div className="flex flex-col gap-4 px-3 py-4 sm:px-4 lg:px-5">
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(260px,420px)_auto] xl:items-start">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-text-muted dark:text-text-muted">
                {t('blackboard.dashboardEyebrow', 'Workspace dashboard')}
              </span>
              <span className="inline-flex min-h-6 items-center gap-1.5 rounded-full border border-success-border bg-success-bg px-2 text-[10px] font-semibold uppercase text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark">
                <Radio size={11} aria-hidden="true" />
                {t('blackboard.liveSync', 'Live sync')}
              </span>
            </div>
            <h1 className="mt-2 truncate text-xl font-semibold text-text-primary dark:text-text-inverse">
              {t('blackboard.title', 'Blackboard')}
            </h1>
            <p className="mt-1 truncate text-sm text-text-secondary dark:text-text-muted">
              {selectedWorkspace?.name ??
                t(
                  'blackboard.modalSubtitle',
                  'Shared goals, tasks, discussions, and topology for the active workspace.'
                )}
            </p>
            {selectedWorkspace && (
              <div className="mt-3 flex flex-wrap gap-2">
                <HeaderBadge>{workspaceUseCaseLabel}</HeaderBadge>
                <HeaderBadge>{collaborationModeLabel}</HeaderBadge>
              </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-text-muted dark:text-text-muted">
              <SensingSurfaceBadge
                labelKey="blackboard.shellSensingHint"
                fallbackLabel="workspace shell sync"
              />
              <span className="min-w-0">
                {t(
                  'blackboard.shellHint',
                  'Blackboard hosts collaboration and projected workspace views; execution authority remains on tasks, attempts, and runtime.'
                )}
              </span>
            </div>
          </div>

          <div className="flex w-full items-center xl:min-w-0">
            <label htmlFor="workspace-select" className="sr-only">
              {t('blackboard.workspaceLabel', 'Workspace')}
            </label>
            <select
              id="workspace-select"
              value={selectedWorkspaceId ?? ''}
              onChange={(event) => {
                onWorkspaceChange(event.target.value || null);
              }}
              className="min-h-10 w-full rounded-md border border-border-light bg-surface-light px-3 text-sm normal-case tracking-normal text-text-primary transition-colors duration-150 focus:border-primary/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-inverse"
            >
              {workspaces.map((workspace) => (
                <option
                  key={workspace.id}
                  value={workspace.id}
                  className="bg-surface-light text-text-primary dark:bg-surface-dark dark:text-text-inverse"
                >
                  {workspace.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex w-full xl:w-auto">
            {selectedWorkspaceId ? (
              <Link
                to={agentWorkspacePath}
                className="inline-flex min-h-10 w-full items-center justify-center gap-2 whitespace-nowrap rounded-md border border-border-light bg-surface-light px-4 text-sm font-medium text-text-primary transition-colors duration-150 hover:border-primary/30 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-inverse xl:w-auto"
              >
                {t('blackboard.openInAgentWorkspace', 'Open in Agent Workspace')}
                <ArrowUpRight size={15} aria-hidden="true" />
              </Link>
            ) : (
              <span className="inline-flex min-h-10 w-full items-center justify-center gap-2 whitespace-nowrap rounded-md border border-border-light px-4 text-sm font-medium text-text-muted dark:border-border-dark dark:text-text-muted xl:w-auto">
                {t('blackboard.openInAgentWorkspace', 'Open in Agent Workspace')}
                <ArrowUpRight size={15} aria-hidden="true" />
              </span>
            )}
          </div>
        </div>

        <dl className="grid overflow-hidden rounded-md border border-border-light bg-border-light dark:border-border-dark dark:bg-border-dark sm:grid-cols-2 xl:grid-cols-6">
          {metrics.map((metric) => (
            <DashboardMetricCell key={metric.key} metric={metric} />
          ))}
        </dl>
      </div>
    </header>
  );
}

function HeaderBadge({ children }: { children: string }) {
  return (
    <span className="inline-flex min-h-7 items-center rounded-md border border-border-light bg-surface-muted px-2.5 text-xs font-medium text-text-secondary dark:border-border-dark dark:bg-surface-dark-alt dark:text-text-muted">
      {children}
    </span>
  );
}

function DashboardMetricCell({ metric }: { metric: DashboardMetric }) {
  const Icon = metric.icon;
  return (
    <div className="min-w-0 bg-surface-light px-3 py-3 dark:bg-surface-dark-alt">
      <dt className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-text-muted dark:text-text-muted">
        <Icon size={14} aria-hidden="true" className={`shrink-0 ${metricToneClass[metric.tone]}`} />
        <span className="truncate">{metric.label}</span>
      </dt>
      <dd className="mt-2 min-w-0">
        <div className="text-xl font-semibold tabular-nums text-text-primary dark:text-text-inverse">
          {metric.value}
        </div>
        <div className="mt-1 truncate text-xs text-text-secondary dark:text-text-muted">
          {metric.detail}
        </div>
      </dd>
    </div>
  );
}

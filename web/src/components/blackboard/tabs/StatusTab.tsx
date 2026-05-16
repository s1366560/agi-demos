import { useEffect, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  MessageSquare,
  Network,
  ShieldCheck,
  Users,
} from 'lucide-react';

import { workspaceBlackboardService } from '@/services/workspaceService';

import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';
import {
  getPendingLeaderAdjudicationSummary,
  hasPendingLeaderAdjudication,
} from '@/utils/workspaceTaskProjection';

import { PresenceBar } from '@/components/workspace/presence/PresenceBar';

import { DerivedSurfaceBadge } from '../DerivedSurfaceBadge';
import { EmptyState } from '../EmptyState';
import { HostedProjectionBadge } from '../HostedProjectionBadge';
import { StatBadge } from '../StatBadge';

import { PlanRunSnapshotSection } from './PlanRunSnapshotSection';

import type {
  TopologyEdge,
  WorkspaceAgent,
  WorkspaceExecutionDiagnostics,
  WorkspaceExecutionDiagnosticsRow,
  WorkspaceTask,
} from '@/types/workspace';

import type { LucideIcon } from 'lucide-react';

export interface StatusTabProps {
  stats: {
    totalTasks?: number | undefined;
    todoTasks?: number | undefined;
    inProgressTasks?: number | undefined;
    completedTasks?: number | undefined;
    blockedTasks?: number | undefined;
    completionRatio: number;
    discussions: number;
    openPosts?: number | undefined;
    activeAgents: number;
    pendingAdjudicationTasks: number;
  };
  topologyEdges: TopologyEdge[];
  agents: WorkspaceAgent[];
  tasks: WorkspaceTask[];
  tenantId?: string;
  projectId?: string;
  workspaceId: string;
  statusBadgeTone: (status: string | undefined) => string;
  planRefreshToken?: number | undefined;
}

interface StatusMetric {
  key: string;
  icon: LucideIcon;
  label: string;
  value: string;
  detail: string;
  tone: 'neutral' | 'success' | 'warning' | 'danger' | 'info';
}

const statusMetricToneClass: Record<StatusMetric['tone'], string> = {
  neutral: 'text-text-secondary dark:text-text-muted',
  success: 'text-status-text-success dark:text-status-text-success-dark',
  warning: 'text-status-text-warning dark:text-status-text-warning-dark',
  danger: 'text-status-text-error dark:text-status-text-error-dark',
  info: 'text-status-text-info dark:text-status-text-info-dark',
};

export function StatusTab({
  stats,
  topologyEdges,
  agents,
  tasks,
  tenantId,
  projectId,
  workspaceId,
  statusBadgeTone,
  planRefreshToken,
}: StatusTabProps) {
  const { t } = useTranslation();
  const pendingAdjudicationTasks = tasks.filter(hasPendingLeaderAdjudication);
  const taskCounts = useMemo(
    () => ({
      total: tasks.length,
      todo: tasks.filter((task) => task.status === 'todo').length,
      inProgress: tasks.filter((task) => task.status === 'in_progress').length,
      blocked: tasks.filter((task) => task.status === 'blocked').length,
      done: tasks.filter((task) => task.status === 'done').length,
    }),
    [tasks]
  );
  const [executionDiagnostics, setExecutionDiagnostics] =
    useState<WorkspaceExecutionDiagnostics | null>(null);
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantId || !projectId) {
      return;
    }

    let cancelled = false;
    workspaceBlackboardService
      .getExecutionDiagnostics(tenantId, projectId, workspaceId)
      .then((payload) => {
        if (!cancelled) {
          setExecutionDiagnostics(payload);
          setDiagnosticsError(null);
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          const message = error instanceof Error ? error.message : String(error);
          setDiagnosticsError(message);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [tenantId, projectId, workspaceId, planRefreshToken]);

  const diagnosticsSignals = useMemo(
    () => ({
      blockers: executionDiagnostics?.blockers ?? [],
      evidenceGaps: executionDiagnostics?.evidence_gaps ?? [],
      toolFailures: executionDiagnostics?.recent_tool_failures ?? [],
    }),
    [executionDiagnostics]
  );
  const diagnosticsSignalCount =
    diagnosticsSignals.blockers.length +
    diagnosticsSignals.evidenceGaps.length +
    diagnosticsSignals.toolFailures.length;
  const statusMetrics = useMemo<StatusMetric[]>(
    () => [
      {
        key: 'completion',
        icon: CheckCircle2,
        label: t('blackboard.metrics.completion', 'Task completion'),
        value: `${String(stats.completionRatio)}%`,
        detail: t('blackboard.completionSummary', {
          done: stats.completedTasks ?? taskCounts.done,
          total: stats.totalTasks ?? taskCounts.total,
        }),
        tone: stats.completionRatio >= 100 ? 'success' : 'info',
      },
      {
        key: 'running',
        icon: Activity,
        label: t('blackboard.iterationMetricRunning', 'Running'),
        value: String(stats.inProgressTasks ?? taskCounts.inProgress),
        detail: t('blackboard.summaryTaskMix', '{{todo}} todo · {{running}} running', {
          todo: stats.todoTasks ?? taskCounts.todo,
          running: stats.inProgressTasks ?? taskCounts.inProgress,
        }),
        tone: (stats.inProgressTasks ?? taskCounts.inProgress) > 0 ? 'info' : 'neutral',
      },
      {
        key: 'blocked',
        icon: AlertTriangle,
        label: t('blackboard.iterationMetricBlocked', 'Blocked'),
        value: String(stats.blockedTasks ?? taskCounts.blocked),
        detail: t('blackboard.executionDiagnosticsTitle', 'Execution diagnostics'),
        tone: (stats.blockedTasks ?? taskCounts.blocked) > 0 ? 'danger' : 'neutral',
      },
      {
        key: 'adjudication',
        icon: ShieldCheck,
        label: t('blackboard.metrics.pendingAdjudication', 'Pending adjudication'),
        value: String(stats.pendingAdjudicationTasks),
        detail: t('blackboard.summary.pendingAdjudication', '{{count}} pending review', {
          count: stats.pendingAdjudicationTasks,
        }),
        tone: stats.pendingAdjudicationTasks > 0 ? 'warning' : 'neutral',
      },
      {
        key: 'agents',
        icon: Users,
        label: t('blackboard.metrics.activeAgents', 'Active agents'),
        value: String(stats.activeAgents),
        detail: t('blackboard.agentStatusTitle', 'Agent status'),
        tone: stats.activeAgents > 0 ? 'success' : 'neutral',
      },
      {
        key: 'collaboration',
        icon: MessageSquare,
        label: t('blackboard.metrics.discussions', 'Discussions'),
        value: String(stats.discussions),
        detail: t('blackboard.summary.openThreads', 'Open threads'),
        tone: (stats.openPosts ?? stats.discussions) > 0 ? 'warning' : 'neutral',
      },
      {
        key: 'topology',
        icon: Network,
        label: t('blackboard.metrics.links', 'Topology links'),
        value: String(topologyEdges.length),
        detail: t('blackboard.tabs.topology', 'Topology'),
        tone: topologyEdges.length > 0 ? 'info' : 'neutral',
      },
    ],
    [stats, t, taskCounts, topologyEdges.length]
  );

  return (
    <div className="space-y-5">
      <section className="rounded-md border border-border-light bg-surface-light dark:border-border-dark dark:bg-surface-dark-alt">
        <div className="flex flex-col gap-3 border-b border-border-light px-4 py-4 dark:border-border-dark xl:flex-row xl:items-start xl:justify-between">
          <div>
            <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
              {t('blackboard.statusOverviewTitle', 'Status and presence')}
            </h3>
            <div className="mt-2">
              <DerivedSurfaceBadge
                labelKey="blackboard.statusOverviewDerivedHint"
                fallbackLabel="workspace execution summary"
              />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatBadge
              label={t('blackboard.executionDiagnosticsTitle', 'Execution diagnostics')}
              value={String(diagnosticsSignalCount)}
            />
            <StatBadge
              label={t('blackboard.metrics.pendingAdjudication', 'Pending adjudication')}
              value={String(stats.pendingAdjudicationTasks)}
            />
          </div>
        </div>
        <div className="flex flex-wrap gap-px bg-border-light dark:bg-border-dark">
          {statusMetrics.map((metric) => (
            <StatusMetricCell key={metric.key} metric={metric} />
          ))}
        </div>
      </section>

      <PlanRunSnapshotSection
        workspaceId={workspaceId}
        tenantId={tenantId}
        projectId={projectId}
        agents={agents}
        tasks={tasks}
        refreshToken={planRefreshToken}
      />

      <ExecutionDiagnosticsSection
        diagnosticsError={diagnosticsError}
        diagnosticsSignalCount={diagnosticsSignalCount}
        diagnosticsSignals={diagnosticsSignals}
      />

      <PendingAdjudicationSection
        agents={agents}
        pendingAdjudicationTasks={pendingAdjudicationTasks}
        projectId={projectId}
        statsPendingAdjudicationTasks={stats.pendingAdjudicationTasks}
        tenantId={tenantId}
        workspaceId={workspaceId}
      />

      <PresenceBar workspaceId={workspaceId} />

      <AgentStatusSection agents={agents} statusBadgeTone={statusBadgeTone} />
    </div>
  );
}

function StatusMetricCell({ metric }: { metric: StatusMetric }) {
  const Icon = metric.icon;
  return (
    <div className="min-w-0 flex-grow basis-full bg-surface-light px-3 py-3 dark:bg-surface-dark-alt sm:basis-[calc(50%-1px)] xl:basis-[calc(25%-1px)] 2xl:basis-[calc(14.285%-1px)]">
      <dt className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-wide text-text-muted dark:text-text-muted">
        <Icon
          size={14}
          aria-hidden="true"
          className={`shrink-0 ${statusMetricToneClass[metric.tone]}`}
        />
        <span className="truncate">{metric.label}</span>
      </dt>
      <dd className="mt-2">
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

interface DiagnosticsSignals {
  blockers: WorkspaceExecutionDiagnosticsRow[];
  evidenceGaps: WorkspaceExecutionDiagnosticsRow[];
  toolFailures: WorkspaceExecutionDiagnosticsRow[];
}

function ExecutionDiagnosticsSection({
  diagnosticsError,
  diagnosticsSignalCount,
  diagnosticsSignals,
}: {
  diagnosticsError: string | null;
  diagnosticsSignalCount: number;
  diagnosticsSignals: DiagnosticsSignals;
}) {
  const { t } = useTranslation();

  return (
    <section className="rounded-md border border-border-light bg-surface-light p-4 dark:border-border-dark dark:bg-surface-dark-alt">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
            {t('blackboard.executionDiagnosticsTitle', 'Execution diagnostics')}
          </h3>
          <div className="mt-2">
            <DerivedSurfaceBadge
              labelKey="blackboard.executionDiagnosticsSurfaceHint"
              fallbackLabel="workspace execution diagnostics"
            />
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatBadge
            label={t('blackboard.executionDiagnosticsBlockers', 'Blockers')}
            value={String(diagnosticsSignals.blockers.length)}
          />
          <StatBadge
            label={t('blackboard.executionDiagnosticsEvidenceGaps', 'Evidence gaps')}
            value={String(diagnosticsSignals.evidenceGaps.length)}
          />
          <StatBadge
            label={t('blackboard.executionDiagnosticsToolFailures', 'Tool failures')}
            value={String(diagnosticsSignals.toolFailures.length)}
          />
        </div>
      </div>

      {diagnosticsError ? (
        <div className="mt-4 rounded-md border border-warning-border bg-warning-bg px-3 py-2 text-sm text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark">
          {diagnosticsError}
        </div>
      ) : diagnosticsSignalCount === 0 ? (
        <div className="mt-4">
          <EmptyState>
            {t(
              'blackboard.executionDiagnosticsEmpty',
              'No blockers, evidence gaps, or recent tool failures are recorded.'
            )}
          </EmptyState>
        </div>
      ) : (
        <div className="mt-4 grid gap-3 xl:grid-cols-3">
          <DiagnosticsList
            title={t('blackboard.executionDiagnosticsBlockers', 'Blockers')}
            emptyLabel={t('blackboard.executionDiagnosticsNoBlockers', 'No blockers')}
            rows={diagnosticsSignals.blockers}
            kind="blocker"
          />
          <DiagnosticsList
            title={t('blackboard.executionDiagnosticsEvidenceGaps', 'Evidence gaps')}
            emptyLabel={t('blackboard.executionDiagnosticsNoEvidenceGaps', 'No evidence gaps')}
            rows={diagnosticsSignals.evidenceGaps}
            kind="evidence"
          />
          <DiagnosticsList
            title={t('blackboard.executionDiagnosticsToolFailures', 'Tool failures')}
            emptyLabel={t('blackboard.executionDiagnosticsNoToolFailures', 'No tool failures')}
            rows={diagnosticsSignals.toolFailures}
            kind="tool"
          />
        </div>
      )}
    </section>
  );
}

function PendingAdjudicationSection({
  agents,
  pendingAdjudicationTasks,
  projectId,
  statsPendingAdjudicationTasks,
  tenantId,
  workspaceId,
}: {
  agents: WorkspaceAgent[];
  pendingAdjudicationTasks: WorkspaceTask[];
  projectId?: string | undefined;
  statsPendingAdjudicationTasks: number;
  tenantId?: string | undefined;
  workspaceId: string;
}) {
  const { t } = useTranslation();

  return (
    <section className="rounded-md border border-border-light bg-surface-light p-4 dark:border-border-dark dark:bg-surface-dark-alt">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
            {t('blackboard.pendingAdjudicationTitle', 'Pending leader adjudication')}
          </h3>
          <p className="mt-1 text-xs text-text-secondary dark:text-text-muted">
            {t(
              'blackboard.pendingAdjudicationDescription',
              'Worker-reported results that still require Sisyphus to make the final task decision.'
            )}
          </p>
          <div className="mt-2">
            <HostedProjectionBadge
              labelKey="blackboard.pendingAdjudicationSurfaceHint"
              fallbackLabel="workspace task projection"
            />
          </div>
        </div>
        <span className="rounded-full border border-info-border bg-info-bg px-3 py-1 text-xs font-semibold text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark">
          {String(statsPendingAdjudicationTasks)}
        </span>
      </div>

      {pendingAdjudicationTasks.length > 0 ? (
        <div className="mt-4 divide-y divide-border-light overflow-hidden rounded-md border border-border-light dark:divide-border-dark dark:border-border-dark">
          {pendingAdjudicationTasks.map((task) => {
            const adjudication = getPendingLeaderAdjudicationSummary(task, agents);
            const conversationHref = adjudication.attemptConversationId
              ? buildAgentWorkspacePath({
                  tenantId,
                  conversationId: adjudication.attemptConversationId,
                  projectId,
                  workspaceId,
                })
              : '';

            return (
              <article key={task.id} className="bg-surface-light px-3 py-3 dark:bg-surface-dark">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="text-sm font-semibold text-text-primary dark:text-text-inverse">
                    {task.title}
                  </div>
                  <span className="rounded-full border border-info-border bg-info-bg px-2 py-0.5 text-[10px] font-semibold uppercase text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark">
                    {adjudication.reportTypeLabel
                      ? adjudication.reportTypeLabel
                      : t('blackboard.pendingAdjudicationFallback', 'candidate result')}
                  </span>
                </div>
                {adjudication.reportSummary && (
                  <p className="mt-2 text-xs leading-5 text-text-secondary dark:text-text-muted">
                    {adjudication.reportSummary}
                  </p>
                )}
                <div className="mt-2 space-y-1 text-[11px] text-text-secondary dark:text-text-muted">
                  {adjudication.reportArtifacts.length > 0 && (
                    <p>
                      {t('blackboard.pendingAdjudicationArtifacts', 'Artifacts')}:{' '}
                      {adjudication.reportArtifacts.join(', ')}
                    </p>
                  )}
                  {adjudication.reportVerifications.length > 0 && (
                    <p>
                      {t('blackboard.pendingAdjudicationChecks', 'Checks')}:{' '}
                      {adjudication.reportVerifications.join(', ')}
                    </p>
                  )}
                  {adjudication.workerLabel && (
                    <p>
                      {t('blackboard.pendingAdjudicationWorker', 'Worker')}:{' '}
                      {adjudication.workerLabel}
                    </p>
                  )}
                  {conversationHref && (
                    <p>
                      <Link
                        to={conversationHref}
                        className="text-status-text-info underline-offset-2 hover:underline dark:text-status-text-info-dark"
                      >
                        {t(
                          'blackboard.pendingAdjudicationOpenConversation',
                          'View attempt conversation'
                        )}
                        {adjudication.attemptNumber
                          ? ` (#${String(adjudication.attemptNumber)})`
                          : ''}
                      </Link>
                    </p>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="mt-4">
          <EmptyState>
            {t(
              'blackboard.pendingAdjudicationEmpty',
              'No worker-reported tasks are waiting on leader adjudication.'
            )}
          </EmptyState>
        </div>
      )}
    </section>
  );
}

function AgentStatusSection({
  agents,
  statusBadgeTone,
}: {
  agents: WorkspaceAgent[];
  statusBadgeTone: (status: string | undefined) => string;
}) {
  const { t } = useTranslation();
  const notAvailableLabel = t('blackboard.notAvailable', 'n/a');

  return (
    <section className="rounded-md border border-border-light bg-surface-light p-4 dark:border-border-dark dark:bg-surface-dark-alt">
      <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
        {t('blackboard.agentStatusTitle', 'Agent status')}
      </h3>

      {agents.length === 0 ? (
        <div className="mt-4">
          <EmptyState>
            {t('blackboard.noAgents', 'No agents have been bound to this workspace yet.')}
          </EmptyState>
        </div>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="min-w-full table-fixed border-collapse text-sm">
            <thead>
              <tr className="border-b border-border-light text-left text-[11px] font-semibold uppercase tracking-wide text-text-muted dark:border-border-dark dark:text-text-muted">
                <th className="w-[42%] px-0 py-2 pr-4">
                  {t('blackboard.agentStatusAgent', 'Agent')}
                </th>
                <th className="w-[18%] px-0 py-2 pr-4">
                  {t('blackboard.agentStatusState', 'State')}
                </th>
                <th className="w-[22%] px-0 py-2 pr-4">
                  {t('blackboard.agentStatusCoordinates', 'Coordinates')}
                </th>
                <th className="w-[18%] px-0 py-2">{t('blackboard.agentStatusStyle', 'Style')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light dark:divide-border-dark">
              {agents.map((agent) => (
                <tr key={agent.id}>
                  <td className="px-0 py-3 pr-4 align-top">
                    <div className="flex min-w-0 items-center gap-3">
                      <span
                        className={`h-2.5 w-2.5 shrink-0 rounded-full ${statusBadgeTone(agent.status)}`}
                        aria-hidden="true"
                      />
                      <span className="sr-only">{agent.status ?? 'unknown'}</span>
                      <div className="min-w-0">
                        <div className="truncate font-medium text-text-primary dark:text-text-inverse">
                          {agent.display_name ?? agent.label ?? agent.agent_id}
                        </div>
                        <div className="mt-1 break-all font-mono text-[11px] text-text-muted">
                          {agent.agent_id}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td className="px-0 py-3 pr-4 align-top">
                    <span className="inline-flex rounded-full border border-border-light bg-surface-muted px-2.5 py-1 text-xs text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                      {agent.status ?? t('blackboard.unknownStatus', 'unknown')}
                    </span>
                  </td>
                  <td className="px-0 py-3 pr-4 align-top font-mono text-xs text-text-muted">
                    {agent.hex_q != null && agent.hex_r != null
                      ? `q ${String(agent.hex_q)} / r ${String(agent.hex_r)}`
                      : notAvailableLabel}
                  </td>
                  <td className="px-0 py-3 align-top">
                    {agent.theme_color ? (
                      <span className="inline-flex items-center gap-2 rounded-full border border-border-light bg-surface-muted px-2.5 py-1 text-xs text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                        <span
                          className="h-2.5 w-2.5 rounded-full"
                          style={{ backgroundColor: agent.theme_color }}
                        />
                        {t('blackboard.accentConfigured', 'Accent')}
                      </span>
                    ) : (
                      <span className="text-xs text-text-muted">{notAvailableLabel}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function DiagnosticsList({
  title,
  emptyLabel,
  rows,
  kind,
}: {
  title: string;
  emptyLabel: string;
  rows: WorkspaceExecutionDiagnosticsRow[];
  kind: 'blocker' | 'evidence' | 'tool';
}) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-muted p-3 dark:border-border-dark dark:bg-background-dark/35">
      <div className="flex items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-text-primary dark:text-text-inverse">{title}</h4>
        <span className="rounded-full border border-border-light bg-surface-light px-2 py-0.5 text-[10px] font-semibold text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
          {String(rows.length)}
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="mt-3 text-xs text-text-muted">{emptyLabel}</p>
      ) : (
        <div className="mt-3 space-y-2">
          {rows.slice(0, 5).map((row, index) => {
            const rowKey = [
              stringValue(row.type),
              stringValue(row.id),
              stringValue(row.task_id),
              stringValue(row.attempt_id),
              stringValue(row.tool_execution_id),
              String(index),
            ]
              .filter(Boolean)
              .join(':');
            return <DiagnosticsRow key={`${kind}-${rowKey}`} row={row} />;
          })}
        </div>
      )}
    </div>
  );
}

function DiagnosticsRow({ row }: { row: WorkspaceExecutionDiagnosticsRow }) {
  const title = stringValue(row.tool_name) || stringValue(row.title) || stringValue(row.task_id);
  const reason = stringValue(row.reason) || stringValue(row.error) || stringValue(row.status);
  const metadata = [
    stringValue(row.attempt_id),
    stringValue(row.tool_execution_id),
    stringValue(row.completed_at),
  ].filter(Boolean);

  return (
    <article className="rounded-md border border-border-light bg-surface-light px-3 py-2 dark:border-border-dark dark:bg-surface-dark">
      {title && (
        <div className="break-words text-sm font-medium text-text-primary dark:text-text-inverse">
          {title}
        </div>
      )}
      {reason && (
        <div className="mt-1 break-words text-xs leading-5 text-text-secondary dark:text-text-muted">
          {reason}
        </div>
      )}
      {metadata.length > 0 && (
        <div className="mt-2 break-all font-mono text-[10px] text-text-muted">
          {metadata.join(' / ')}
        </div>
      )}
    </article>
  );
}

function stringValue(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : '';
}

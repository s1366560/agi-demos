import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { buildAgentWorkspacePath } from '@/utils/agentWorkspacePath';
import {
  getPendingLeaderAdjudicationSummary,
  hasPendingLeaderAdjudication,
} from '@/utils/workspaceTaskProjection';

import { PresenceBar } from '@/components/workspace/presence/PresenceBar';

import { EmptyState } from '../EmptyState';
import { HostedProjectionBadge } from '../HostedProjectionBadge';
import { StatBadge } from '../StatBadge';

import type { TopologyEdge, WorkspaceAgent, WorkspaceTask } from '@/types/workspace';

export interface StatusTabProps {
  stats: {
    completionRatio: number;
    discussions: number;
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
}

export function StatusTab({
  stats,
  topologyEdges,
  agents,
  tasks,
  tenantId,
  projectId,
  workspaceId,
  statusBadgeTone,
}: StatusTabProps) {
  const { t } = useTranslation();
  const pendingAdjudicationTasks = tasks.filter(hasPendingLeaderAdjudication);

  return (
    <div className="space-y-5">
      <section className="rounded-2xl border border-border-light bg-surface-muted px-4 py-4 dark:border-border-dark dark:bg-background-dark/35">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
              {t('blackboard.statusOverviewTitle', 'Status and presence')}
            </h3>
          </div>
          <div className="flex flex-wrap gap-2">
            {[
              {
                key: 'progress',
                label: t('blackboard.metrics.completion', 'Task completion'),
                value: `${String(stats.completionRatio)}%`,
              },
              {
                key: 'pending-adjudication',
                label: t('blackboard.metrics.pendingAdjudication', 'Pending adjudication'),
                value: String(stats.pendingAdjudicationTasks),
              },
              {
                key: 'threads',
                label: t('blackboard.metrics.discussions', 'Discussions'),
                value: String(stats.discussions),
              },
              {
                key: 'agents',
                label: t('blackboard.metrics.activeAgents', 'Active agents'),
                value: String(stats.activeAgents),
              },
              {
                key: 'edges',
                label: t('blackboard.metrics.links', 'Topology links'),
                value: String(topologyEdges.length),
              },
            ].map((metric) => (
              <StatBadge key={metric.key} label={metric.label} value={metric.value} />
            ))}
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
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
            {String(stats.pendingAdjudicationTasks)}
          </span>
        </div>

        {pendingAdjudicationTasks.length > 0 ? (
          <div className="mt-4 space-y-3">
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
                <article
                  key={task.id}
                  className="rounded-lg border border-info-border/60 bg-info-bg/60 p-3 dark:border-info-border-dark/60 dark:bg-info-bg-dark/30"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="text-sm font-semibold text-text-primary dark:text-text-inverse">
                      {task.title}
                    </div>
                    <span className="rounded-full border border-info-border bg-surface-light px-2 py-0.5 text-[10px] font-semibold uppercase text-status-text-info dark:border-info-border-dark dark:bg-surface-dark dark:text-status-text-info-dark">
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

      <PresenceBar workspaceId={workspaceId} />

      <section className="rounded-xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
        <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
          {t('blackboard.agentStatusTitle', 'Agent status')}
        </h3>
        <div className="mt-4 divide-y divide-border-separator dark:divide-border-dark">
          {agents.map((agent) => (
            <div
              key={agent.id}
              className="flex flex-col gap-3 py-4 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-3">
                  <span
                    className={`h-2.5 w-2.5 rounded-full ${statusBadgeTone(agent.status)}`}
                    aria-hidden="true"
                  />
                  <span className="sr-only">{agent.status ?? 'unknown'}</span>
                  <div className="truncate text-sm font-medium text-text-primary dark:text-text-inverse">
                    {agent.display_name ?? agent.label ?? agent.agent_id}
                  </div>
                </div>
                <div className="mt-1 break-all font-mono text-[11px] text-text-muted">
                  {agent.agent_id}
                  {agent.hex_q !== undefined && agent.hex_r !== undefined && (
                    <>
                      {' '}
                      &middot; q {String(agent.hex_q)} / r {String(agent.hex_r)}
                    </>
                  )}
                </div>
              </div>
              <div className="flex flex-wrap gap-2 text-xs text-text-secondary dark:text-text-secondary">
                <span className="rounded-full border border-border-light bg-surface-light px-3 py-1.5 dark:border-border-dark dark:bg-surface-dark">
                  {agent.status ?? t('blackboard.unknownStatus', 'unknown')}
                </span>
                {agent.theme_color && (
                  <span className="inline-flex items-center gap-2 rounded-full border border-border-light bg-surface-light px-3 py-1.5 dark:border-border-dark dark:bg-surface-dark">
                    <span
                      className="h-2.5 w-2.5 rounded-full"
                      style={{ backgroundColor: agent.theme_color }}
                    />
                    {t('blackboard.accentConfigured', 'Accent')}
                  </span>
                )}
              </div>
            </div>
          ))}

          {agents.length === 0 && (
            <EmptyState>
              {t('blackboard.noAgents', 'No agents have been bound to this workspace yet.')}
            </EmptyState>
          )}
        </div>
      </section>
    </div>
  );
}

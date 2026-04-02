import { useTranslation } from 'react-i18next';

import { PresenceBar } from '@/components/workspace/presence/PresenceBar';

import { StatBadge } from '../StatBadge';

import type { TopologyEdge, WorkspaceAgent } from '@/types/workspace';

export interface StatusTabProps {
  stats: { completionRatio: number; discussions: number; activeAgents: number };
  topologyEdges: TopologyEdge[];
  agents: WorkspaceAgent[];
  workspaceId: string;
  statusBadgeTone: (status: string | undefined) => string;
}

export function StatusTab({
  stats,
  topologyEdges,
  agents,
  workspaceId,
  statusBadgeTone,
}: StatusTabProps) {
  const { t } = useTranslation();

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
            <div className="rounded-xl border border-dashed border-border-separator bg-surface-light p-5 text-sm text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
              {t('blackboard.noAgents', 'No agents have been bound to this workspace yet.')}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

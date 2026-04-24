import { useTranslation } from 'react-i18next';

import { EmptyState } from '../EmptyState';
import { HostedProjectionBadge } from '../HostedProjectionBadge';

import type { TopologyEdge, TopologyNode } from '@/types/workspace';


export interface TopologyTabProps {
  topologyNodes: TopologyNode[];
  topologyEdges: TopologyEdge[];
  topologyNodeTitles: Map<string, string>;
}

export function TopologyTab({
  topologyNodes,
  topologyEdges,
  topologyNodeTitles,
}: TopologyTabProps) {
  const { t } = useTranslation();

  return (
    <div className="space-y-5">
      <HostedProjectionBadge
        labelKey="blackboard.topologySurfaceHint"
        fallbackLabel="workspace topology projection"
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <div className="rounded-2xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
              {t('blackboard.topologyNodesTitle', 'Nodes')}
            </h3>
            <span className="rounded-full bg-surface-muted px-3 py-1 text-xs text-text-muted dark:bg-surface-dark dark:text-text-muted">
              {String(topologyNodes.length)}
            </span>
          </div>
          <div className="divide-y divide-border-separator dark:divide-border-dark">
            {topologyNodes.map((node) => (
              <div key={node.id} className="py-4 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full border border-border-light bg-surface-muted px-2.5 py-0.5 text-[11px] uppercase tracking-widest text-text-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                    {node.node_type}
                  </span>
                  {node.status && (
                    <span className="rounded-full bg-surface-muted px-2.5 py-0.5 text-xs text-text-secondary dark:bg-surface-dark dark:text-text-secondary">
                      {node.status}
                    </span>
                  )}
                </div>
                <h4 className="mt-2 break-words text-sm font-semibold text-text-primary dark:text-text-inverse">
                  {node.title}
                </h4>
                <div className="mt-1.5 break-all text-xs text-text-muted dark:text-text-muted">
                  {node.hex_q !== undefined && node.hex_r !== undefined
                    ? `q ${String(node.hex_q)} \u00b7 r ${String(node.hex_r)}`
                    : t('blackboard.topologyUnplaced', 'No hex placement')}
                </div>
              </div>
            ))}

            {topologyNodes.length === 0 && (
              <EmptyState>
                {t('blackboard.noTopologyNodes', 'No topology nodes yet.')}
              </EmptyState>
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
              {t('blackboard.topologyEdgesTitle', 'Edges')}
            </h3>
            <span className="rounded-full bg-surface-muted px-3 py-1 text-xs text-text-muted dark:bg-surface-dark dark:text-text-muted">
              {String(topologyEdges.length)}
            </span>
          </div>
          <div className="divide-y divide-border-separator dark:divide-border-dark">
            {topologyEdges.map((edge) => (
              <div key={edge.id} className="py-4 first:pt-0 last:pb-0">
                <div className="break-words text-sm font-medium text-text-primary dark:text-text-inverse">
                  {(topologyNodeTitles.get(edge.source_node_id) ?? edge.source_node_id) +
                    ' \u2192 ' +
                    (topologyNodeTitles.get(edge.target_node_id) ?? edge.target_node_id)}
                </div>
                <div className="mt-1.5 break-all font-mono text-[11px] text-text-muted dark:text-text-muted">
                  {edge.source_node_id} {'\u2192'} {edge.target_node_id}
                </div>
              </div>
            ))}

            {topologyEdges.length === 0 && (
              <EmptyState>
                {t('blackboard.noTopologyEdges', 'No topology edges yet.')}
              </EmptyState>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

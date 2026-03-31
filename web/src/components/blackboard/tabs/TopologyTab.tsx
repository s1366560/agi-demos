import { useTranslation } from 'react-i18next';

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
      <div className="rounded-3xl border border-border-light bg-surface-muted p-5 dark:border-border-dark dark:bg-surface-dark-alt">
        <div className="text-lg font-semibold text-text-primary dark:text-text-inverse">
          {t('blackboard.commandCenter', 'Workspace command center')}
        </div>
        <p className="mt-2 text-sm leading-7 text-text-secondary dark:text-text-muted">
          {t(
            'blackboard.topologyHint',
            'The live command surface stays on the page canvas. Use this tab for a structured read of current nodes, connections, and placements while the main board remains visible behind the modal.'
          )}
        </p>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
        <div className="rounded-3xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
              {t('blackboard.topologyNodesTitle', 'Nodes')}
            </h3>
            <span className="rounded-full bg-surface-muted px-3 py-1 text-xs text-text-muted dark:bg-surface-dark dark:text-text-muted">
              {String(topologyNodes.length)}
            </span>
          </div>
          <div className="space-y-3">
            {topologyNodes.map((node) => (
              <article
                key={node.id}
                className="rounded-3xl border border-border-light bg-surface-muted p-4 dark:border-border-dark dark:bg-surface-dark-alt"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <span className="rounded-full border border-border-light bg-surface-light px-3 py-1 text-[11px] uppercase tracking-[0.16em] text-text-muted dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                    {node.node_type}
                  </span>
                  {node.status && (
                    <span className="rounded-full bg-surface-light px-3 py-1 text-xs text-text-secondary dark:bg-surface-dark dark:text-text-secondary">
                      {node.status}
                    </span>
                  )}
                </div>
                <h4 className="mt-3 break-words text-sm font-semibold text-text-primary dark:text-text-inverse">
                  {node.title}
                </h4>
                <div className="mt-3 break-all text-xs text-text-muted dark:text-text-muted">
                  {node.hex_q !== undefined && node.hex_r !== undefined
                    ? `q ${String(node.hex_q)} \u00b7 r ${String(node.hex_r)}`
                    : t('blackboard.topologyUnplaced', 'No hex placement')}
                </div>
              </article>
            ))}

            {topologyNodes.length === 0 && (
              <div className="rounded-3xl border border-dashed border-border-separator bg-surface-light p-5 text-sm text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                {t('blackboard.noTopologyNodes', 'No topology nodes yet.')}
              </div>
            )}
          </div>
        </div>

        <div className="rounded-3xl border border-border-light bg-surface-light p-5 dark:border-border-dark dark:bg-surface-dark-alt">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-text-primary dark:text-text-inverse">
              {t('blackboard.topologyEdgesTitle', 'Edges')}
            </h3>
            <span className="rounded-full bg-surface-muted px-3 py-1 text-xs text-text-muted dark:bg-surface-dark dark:text-text-muted">
              {String(topologyEdges.length)}
            </span>
          </div>
          <div className="space-y-3">
            {topologyEdges.map((edge) => (
              <article
                key={edge.id}
                className="rounded-3xl border border-border-light bg-surface-muted p-4 dark:border-border-dark dark:bg-surface-dark-alt"
              >
                <div className="text-[11px] uppercase tracking-[0.16em] text-text-muted dark:text-text-muted">
                  {t('blackboard.topologyLink', 'Topology link')}
                </div>
                <div className="mt-2 break-words text-sm font-medium text-text-primary dark:text-text-inverse">
                  {(topologyNodeTitles.get(edge.source_node_id) ?? edge.source_node_id) +
                    ' \u2192 ' +
                    (topologyNodeTitles.get(edge.target_node_id) ?? edge.target_node_id)}
                </div>
                <div className="mt-2 break-all font-mono text-[11px] text-text-muted dark:text-text-muted">
                  {edge.source_node_id} {'\u2192'} {edge.target_node_id}
                </div>
              </article>
            ))}

            {topologyEdges.length === 0 && (
              <div className="rounded-3xl border border-dashed border-border-separator bg-surface-light p-5 text-sm text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted">
                {t('blackboard.noTopologyEdges', 'No topology edges yet.')}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

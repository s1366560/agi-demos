import { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { graphService } from '@/services/graphService';
import type { GraphNode } from '@/services/graphService';

import type { GraphSnapshot, NodeData, EdgeData } from '@/components/graph/CytoscapeGraph/types';

import { graphSourceUuids, requireGraphSource } from './graphProvenance';

import type { GraphSelection } from './graphProvenance';

interface Props {
  graph: GraphSnapshot;
  selection: GraphSelection;
  tenantId: string | undefined;
  projectId: string | undefined;
  onNode: (node: NodeData) => void;
  onEdge: (edge: EdgeData) => void;
}

export function GraphProvenancePanel({
  graph,
  selection,
  tenantId,
  projectId,
  onNode,
  onEdge,
}: Props) {
  const { t } = useTranslation();
  const [requestedUuid, setRequestedUuid] = useState<string | null>(null);
  const [requestNonce, setRequestNonce] = useState(0);
  const [source, setSource] = useState<GraphNode | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'unavailable'>('idle');
  const sourceUuids = graphSourceUuids(graph, selection);
  useEffect(() => {
    if (!requestedUuid || !tenantId || !projectId) return;
    let current = true;
    void graphService
      .getSubgraph({
        node_uuids: [requestedUuid],
        include_neighbors: false,
        limit: 1,
        tenant_id: tenantId,
        project_id: projectId,
      })
      .then((data) => {
        if (!current) return;
        const next = requireGraphSource(data, requestedUuid, tenantId, projectId);
        setSource(next);
        setStatus(next ? 'ready' : 'unavailable');
      })
      .catch(() => {
        if (current) {
          setSource(null);
          setStatus('unavailable');
        }
      });
    return () => {
      current = false;
    };
  }, [requestedUuid, tenantId, projectId, requestNonce]);

  const nodeButton = (id: string) => {
    const node = graph.nodes.find((item) => item.id === id);
    return node ? (
      <button
        className="text-blue-600 underline break-all"
        type="button"
        onClick={() => { onNode(node); }}
      >
        {node.name} <span className="text-xs">({id})</span>
      </button>
    ) : (
      <span>{id}</span>
    );
  };
  const adjacent =
    selection.kind === 'node'
      ? graph.edges.filter(
          (edge) => edge.source === selection.data.id || edge.target === selection.data.id
        )
      : [selection.data];

  return (
    <section
      className="space-y-4 break-words"
      aria-label={t('project.graph.provenance.title', {
        defaultValue: 'Relationships and sources',
      })}
    >
      <p className="text-xs text-slate-500">
        {t('project.graph.provenance.partial', {
          defaultValue:
            'This view contains a limited graph subset. Relationships and sources may be incomplete.',
        })}
      </p>
      <div className="text-xs space-y-1">
        {typeof selection.data.uuid === 'string' && (
          <p className="break-all">{selection.data.uuid}</p>
        )}
        {typeof selection.data.created_at === 'string' && (
          <p>
            {t('project.graph.provenance.created', {
              defaultValue: 'Created: {{time}}',
              time: selection.data.created_at,
            })}
          </p>
        )}
        {typeof selection.data.valid_at === 'string' && (
          <p>
            {t('project.graph.provenance.valid', {
              defaultValue: 'Valid from: {{time}}',
              time: selection.data.valid_at,
            })}
          </p>
        )}
      </div>
      <h3 className="font-semibold">
        {t('project.graph.provenance.relationships', { defaultValue: 'Directed relationships' })}
      </h3>
      <ul className="space-y-3">
        {adjacent.map((edge) => (
          <li key={edge.id} className="rounded border border-slate-300 p-2 dark:border-slate-600">
            {nodeButton(edge.source)} <span aria-hidden="true"> → </span>
            <button type="button" className="underline" onClick={() => { onEdge(edge); }}>
              {edge.label || edge.id}
            </button>
            <span aria-hidden="true"> → </span> {nodeButton(edge.target)}
            {typeof edge.fact === 'string' && (
              <p className="whitespace-pre-wrap mt-2">{edge.fact}</p>
            )}
          </li>
        ))}
      </ul>
      {adjacent.length === 0 && (
        <p>
          {t('project.graph.provenance.noRelationships', {
            defaultValue: 'No relationships in this view.',
          })}
        </p>
      )}
      <h3 className="font-semibold">
        {t('project.graph.provenance.sources', { defaultValue: 'Supporting sources' })}
      </h3>
      {sourceUuids.length === 0 && (
        <p>
          {t('project.graph.provenance.noSources', {
            defaultValue: 'No recorded source references in this view.',
          })}
        </p>
      )}
      <ul className="space-y-2">
        {sourceUuids.map((uuid) => (
          <li key={uuid}>
            <button
              type="button"
              className="text-blue-600 underline break-all"
              disabled={!tenantId || !projectId}
              onClick={() => {
                setSource(null);
                setStatus('loading');
                setRequestedUuid(uuid);
                setRequestNonce((value) => value + 1);
              }}
            >
              {t('project.graph.provenance.openSource', {
                defaultValue: 'Read source {{uuid}}',
                uuid,
              })}
            </button>
          </li>
        ))}
      </ul>
      {status === 'loading' && (
        <p role="status">{t('common.loading', { defaultValue: 'Loading…' })}</p>
      )}
      {status === 'unavailable' && (
        <p role="status">
          {t('project.graph.provenance.unavailable', {
            defaultValue: 'This source is unavailable in the current project.',
          })}
        </p>
      )}
      {source && (
        <article className="space-y-2 border-t pt-3">
          <h4 className="font-semibold">
            {t('project.graph.provenance.captured', { defaultValue: 'Captured source content' })}
          </h4>
          <p className="text-xs break-all">{source.uuid}</p>
          {source.source_description && <p>{source.source_description}</p>}
          {source.source && <p>{source.source}</p>}
          {source.created_at && (
            <p>
              {t('project.graph.provenance.created', {
                defaultValue: 'Created: {{time}}',
                time: source.created_at,
              })}
            </p>
          )}
          {source.valid_at && (
            <p>
              {t('project.graph.provenance.valid', {
                defaultValue: 'Valid from: {{time}}',
                time: source.valid_at,
              })}
            </p>
          )}
          <p className="whitespace-pre-wrap">
            {source.content ??
              t('project.graph.provenance.noContent', {
                defaultValue: 'No captured content is available.',
              })}
          </p>
          {source.memory_id && tenantId && projectId && (
            <div className="space-y-2">
              <p className="text-xs">
                {t('project.graph.provenance.currentNotice', {
                  defaultValue:
                    'The current memory may have changed since extraction or may no longer be available.',
                })}
              </p>
              <Link
                className="text-blue-600 underline"
                to={`/tenant/${encodeURIComponent(tenantId)}/project/${encodeURIComponent(projectId)}/memory/${encodeURIComponent(source.memory_id)}`}
              >
                {t('project.graph.provenance.currentMemory', {
                  defaultValue: 'Open current memory',
                })}
              </Link>
            </div>
          )}
        </article>
      )}
    </section>
  );
}

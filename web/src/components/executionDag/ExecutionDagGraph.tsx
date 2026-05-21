import { memo, useEffect, useMemo, useRef } from 'react';

import { useTranslation } from 'react-i18next';

import {
  Activity,
  CheckCircle2,
  CircleDashed,
  GitBranch,
  PackageCheck,
  ShieldCheck,
  UserCircle,
  XCircle,
} from 'lucide-react';

import type { ExecutionDagEdge, ExecutionDagModel, ExecutionDagNodeLayout } from './types';

const NODE_WIDTH = 224;
const NODE_HEIGHT = 116;
const COLUMN_GAP = 56;
const LEVEL_GAP = 118;
const PADDING_X = 36;
const PADDING_Y = 32;

const STATUS_TONE: Record<string, string> = {
  done: 'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark',
  completed:
    'border-success-border bg-success-bg text-status-text-success dark:border-success-border-dark dark:bg-success-bg-dark dark:text-status-text-success-dark',
  in_progress:
    'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark',
  running:
    'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark',
  dispatched:
    'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark',
  verifying:
    'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark',
  reported:
    'border-info-border bg-info-bg text-status-text-info dark:border-info-border-dark dark:bg-info-bg-dark dark:text-status-text-info-dark',
  blocked:
    'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark',
  failed:
    'border-error-border bg-error-bg text-status-text-error dark:border-error-border-dark dark:bg-error-bg-dark dark:text-status-text-error-dark',
  skipped:
    'border-warning-border bg-warning-bg text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark',
  cancelled:
    'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted',
  todo: 'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted',
  pending:
    'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted',
};

export interface ExecutionDagGraphProps {
  model: ExecutionDagModel | null;
  selectedNodeId?: string | null | undefined;
  highlightedNodeId?: string | null | undefined;
  dimmedNodeIds?: ReadonlySet<string> | undefined;
  onNodeSelect?: ((nodeId: string) => void) | undefined;
  className?: string | undefined;
  minHeight?: number | undefined;
}

interface GraphLayout {
  nodes: ExecutionDagNodeLayout[];
  edges: ExecutionDagEdge[];
  width: number;
  height: number;
  byId: Map<string, ExecutionDagNodeLayout>;
}

function statusTone(status: string): string {
  return (
    STATUS_TONE[status] ??
    'border-border-light bg-surface-muted text-text-secondary dark:border-border-dark dark:bg-surface-dark dark:text-text-muted'
  );
}

function statusIcon(status: string, execution: string | undefined) {
  if (status === 'done' || status === 'completed') {
    return <CheckCircle2 className="h-4 w-4 text-status-text-success" aria-hidden />;
  }
  if (status === 'blocked' || status === 'failed') {
    return <XCircle className="h-4 w-4 text-status-text-error" aria-hidden />;
  }
  if (execution === 'verifying' || execution === 'reported') {
    return <ShieldCheck className="h-4 w-4 text-status-text-info" aria-hidden />;
  }
  if (status === 'in_progress' || status === 'running' || execution === 'running') {
    return <Activity className="h-4 w-4 text-status-text-info" aria-hidden />;
  }
  return <CircleDashed className="h-4 w-4 text-text-muted" aria-hidden />;
}

function edgeKey(edge: ExecutionDagEdge): string {
  return `${edge.kind}:${edge.sourceId}:${edge.targetId}:${edge.label ?? ''}`;
}

function buildLayout(model: ExecutionDagModel): GraphLayout {
  const nodes = model.nodes;
  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = model.edges.filter(
    (edge) => nodeIds.has(edge.sourceId) && nodeIds.has(edge.targetId)
  );
  const incoming = new Map<string, number>();
  const adjacency = new Map<string, string[]>();

  for (const node of nodes) {
    incoming.set(node.id, 0);
    adjacency.set(node.id, []);
  }
  for (const edge of edges) {
    incoming.set(edge.targetId, (incoming.get(edge.targetId) ?? 0) + 1);
    adjacency.get(edge.sourceId)?.push(edge.targetId);
  }

  const nodeOrder = new Map(nodes.map((node, index) => [node.id, index]));
  const levels = new Map<string, number>();
  const queue = nodes
    .filter((node) => (incoming.get(node.id) ?? 0) === 0)
    .sort((left, right) => (nodeOrder.get(left.id) ?? 0) - (nodeOrder.get(right.id) ?? 0));

  if (queue.length === 0 && nodes[0]) {
    queue.push(nodes[0]);
  }

  const mutableIncoming = new Map(incoming);
  while (queue.length > 0) {
    const node = queue.shift();
    if (!node) {
      continue;
    }
    const currentLevel = levels.get(node.id) ?? 0;
    const neighbors = adjacency.get(node.id) ?? [];
    for (const neighborId of neighbors) {
      levels.set(neighborId, Math.max(levels.get(neighborId) ?? 0, currentLevel + 1));
      const remaining = (mutableIncoming.get(neighborId) ?? 0) - 1;
      mutableIncoming.set(neighborId, remaining);
      if (remaining <= 0) {
        const neighbor = nodes.find((item) => item.id === neighborId);
        if (neighbor) {
          queue.push(neighbor);
        }
      }
    }
  }

  let fallbackLevel = Math.max(0, ...Array.from(levels.values()));
  for (const node of nodes) {
    if (!levels.has(node.id)) {
      fallbackLevel += 1;
      levels.set(node.id, fallbackLevel);
    }
  }

  const levelsByNumber = new Map<number, typeof nodes>();
  for (const node of nodes) {
    const level = levels.get(node.id) ?? 0;
    const existing = levelsByNumber.get(level) ?? [];
    existing.push(node);
    levelsByNumber.set(level, existing);
  }

  const maxColumns = Math.max(
    1,
    ...Array.from(levelsByNumber.values()).map((items) => items.length)
  );
  const maxLevel = Math.max(0, ...Array.from(levelsByNumber.keys()));
  const width = PADDING_X * 2 + maxColumns * NODE_WIDTH + (maxColumns - 1) * COLUMN_GAP;
  const height = PADDING_Y * 2 + (maxLevel + 1) * NODE_HEIGHT + maxLevel * LEVEL_GAP;
  const laidOut: ExecutionDagNodeLayout[] = [];

  for (const [level, levelNodes] of levelsByNumber.entries()) {
    const sorted = [...levelNodes].sort(
      (left, right) => (nodeOrder.get(left.id) ?? 0) - (nodeOrder.get(right.id) ?? 0)
    );
    const rowWidth = sorted.length * NODE_WIDTH + (sorted.length - 1) * COLUMN_GAP;
    const startX = (width - rowWidth) / 2;
    sorted.forEach((node, order) => {
      laidOut.push({
        ...node,
        x: startX + order * (NODE_WIDTH + COLUMN_GAP),
        y: PADDING_Y + level * (NODE_HEIGHT + LEVEL_GAP),
        level,
        order,
      });
    });
  }

  const byId = new Map(laidOut.map((node) => [node.id, node]));
  return { nodes: laidOut, edges, width, height, byId };
}

function edgePath(source: ExecutionDagNodeLayout, target: ExecutionDagNodeLayout): string {
  const startX = source.x + NODE_WIDTH / 2;
  const startY = source.y + NODE_HEIGHT;
  const endX = target.x + NODE_WIDTH / 2;
  const endY = target.y;
  const midY = startY + Math.max(34, (endY - startY) / 2);
  return `M ${startX.toFixed(1)} ${startY.toFixed(1)} C ${startX.toFixed(1)} ${midY.toFixed(
    1
  )}, ${endX.toFixed(1)} ${(midY - 10).toFixed(1)}, ${endX.toFixed(1)} ${endY.toFixed(1)}`;
}

function centerScrollOffset(nodeStart: number, nodeSize: number, viewportSize: number): number {
  return Math.max(0, nodeStart + nodeSize / 2 - viewportSize / 2);
}

export const ExecutionDagGraph = memo<ExecutionDagGraphProps>(
  ({
    model,
    selectedNodeId,
    highlightedNodeId,
    dimmedNodeIds,
    onNodeSelect,
    className = '',
    minHeight = 520,
  }) => {
    const { t } = useTranslation();
    const scrollContainerRef = useRef<HTMLDivElement | null>(null);
    const layout = useMemo(() => (model ? buildLayout(model) : null), [model]);

    useEffect(() => {
      if (!layout || !highlightedNodeId) {
        return;
      }
      const container = scrollContainerRef.current;
      const highlightedNode = layout.byId.get(highlightedNodeId);
      if (!container || !highlightedNode) {
        return;
      }

      container.scrollTo({
        left: centerScrollOffset(highlightedNode.x, NODE_WIDTH, container.clientWidth),
        top: centerScrollOffset(highlightedNode.y, NODE_HEIGHT, container.clientHeight),
        behavior: 'auto',
      });
    }, [highlightedNodeId, layout]);

    if (!model || model.nodes.length === 0 || !layout) {
      return (
        <div
          className={`flex min-h-[320px] items-center justify-center rounded-md border border-border-light bg-surface-light text-sm text-text-muted dark:border-border-dark dark:bg-surface-dark ${className}`}
          data-testid="execution-dag-empty"
        >
          <div className="text-center">
            <GitBranch className="mx-auto h-8 w-8 text-text-muted" aria-hidden />
            <p className="mt-2">
              {t('executionDag.empty', {
                defaultValue: 'No execution graph is available.',
              })}
            </p>
          </div>
        </div>
      );
    }

    return (
      <div
        ref={scrollContainerRef}
        className={`overflow-auto rounded-md border border-border-light bg-surface-light dark:border-border-dark dark:bg-surface-dark ${className}`}
        style={{ minHeight }}
        data-testid="execution-dag-graph"
      >
        <svg
          width={layout.width}
          height={layout.height}
          viewBox={`0 0 ${layout.width} ${layout.height}`}
          className="min-h-full min-w-full"
          role="img"
          aria-label={t('executionDag.ariaLabel', {
            defaultValue: 'Execution DAG',
          })}
        >
          <title>{t('executionDag.ariaLabel', { defaultValue: 'Execution DAG' })}</title>
          <defs>
            <marker
              id="execution-dag-arrow-dependency"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" className="fill-text-muted" />
            </marker>
            <marker
              id="execution-dag-arrow-handoff"
              viewBox="0 0 10 10"
              refX="8"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" className="fill-status-text-info" />
            </marker>
          </defs>

          {layout.edges.map((edge) => {
            const source = layout.byId.get(edge.sourceId);
            const target = layout.byId.get(edge.targetId);
            if (!source || !target) {
              return null;
            }
            const muted = edge.kind === 'hierarchy';
            const handoff = edge.kind === 'handoff';
            return (
              <path
                key={edge.id || edgeKey(edge)}
                d={edgePath(source, target)}
                fill="none"
                strokeWidth={handoff ? 2 : 1.5}
                strokeDasharray={muted ? '4 5' : handoff ? '6 4' : undefined}
                markerEnd={
                  handoff
                    ? 'url(#execution-dag-arrow-handoff)'
                    : 'url(#execution-dag-arrow-dependency)'
                }
                className={
                  handoff
                    ? 'stroke-status-text-info'
                    : muted
                      ? 'stroke-border-light opacity-70 dark:stroke-border-dark'
                      : 'stroke-text-muted'
                }
              />
            );
          })}

          {layout.nodes.map((node) => {
            const isSelected = selectedNodeId === node.id;
            const isHighlighted = highlightedNodeId === node.id;
            const isDimmed = dimmedNodeIds?.has(node.id) ?? false;
            const selectable = node.selectable !== false && Boolean(onNodeSelect);
            return (
              <foreignObject
                key={node.id}
                x={node.x}
                y={node.y}
                width={NODE_WIDTH}
                height={NODE_HEIGHT}
                className="overflow-visible"
              >
                <button
                  type="button"
                  disabled={!selectable}
                  onClick={() => {
                    if (selectable) {
                      onNodeSelect?.(node.id);
                    }
                  }}
                  onKeyDown={(event) => {
                    if (!selectable) {
                      return;
                    }
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onNodeSelect?.(node.id);
                    }
                  }}
                  className={`relative flex h-full w-full flex-col rounded-md border bg-surface-light p-3 text-left shadow-[0_0_0_1px_rgba(0,0,0,0.02)] transition-[border-color,background-color,box-shadow,opacity] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-default dark:bg-surface-dark ${
                    isSelected
                      ? 'border-info-border ring-2 ring-ring dark:border-info-border-dark'
                      : isHighlighted
                        ? 'border-warning-border ring-2 ring-status-text-warning/35 dark:border-warning-border-dark dark:ring-status-text-warning-dark/35'
                        : 'border-border-light hover:border-info-border dark:border-border-dark dark:hover:border-info-border-dark'
                  } ${isDimmed ? 'opacity-35' : 'opacity-100'}`}
                  aria-pressed={isSelected}
                  data-current-session-node={isHighlighted ? 'true' : undefined}
                  data-testid={`execution-dag-node-${node.id}`}
                >
                  {isHighlighted ? (
                    <span className="absolute right-2 top-2 inline-flex h-5 max-w-[112px] items-center rounded-full border border-warning-border bg-warning-bg px-2 text-[10px] font-semibold uppercase text-status-text-warning dark:border-warning-border-dark dark:bg-warning-bg-dark dark:text-status-text-warning-dark">
                      <span className="truncate">
                        {t('executionDag.currentSession', {
                          defaultValue: 'Current session',
                        })}
                      </span>
                    </span>
                  ) : null}
                  <div
                    className={`flex min-w-0 items-start gap-2 ${isHighlighted ? 'pr-[118px]' : ''}`}
                  >
                    <span className="mt-0.5 shrink-0">
                      {statusIcon(node.status, node.execution)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold leading-5 text-text-primary dark:text-text-inverse">
                        {node.title}
                      </span>
                      {node.subtitle ? (
                        <span className="mt-0.5 block truncate text-[11px] text-text-muted">
                          {node.subtitle}
                        </span>
                      ) : null}
                    </span>
                  </div>

                  <div className="mt-2 flex min-w-0 flex-wrap gap-1.5">
                    <span
                      className={`inline-flex h-5 items-center rounded-full border px-2 text-[10px] font-semibold uppercase ${statusTone(
                        node.status
                      )}`}
                    >
                      {node.status}
                    </span>
                    {node.execution ? (
                      <span className="inline-flex h-5 items-center rounded-full border border-border-light px-2 text-[10px] font-semibold uppercase text-text-secondary dark:border-border-dark dark:text-text-muted">
                        {node.execution}
                      </span>
                    ) : null}
                  </div>

                  <div className="mt-auto min-w-0 space-y-1.5">
                    {typeof node.progress === 'number' ? (
                      <div className="h-1.5 overflow-hidden rounded-full bg-surface-dark/10 dark:bg-surface-light/10">
                        <div
                          className="h-full rounded-full bg-status-text-info transition-[width] motion-reduce:transition-none"
                          style={{
                            width: `${Math.max(0, Math.min(100, node.progress)).toFixed(0)}%`,
                          }}
                        />
                      </div>
                    ) : null}
                    <div className="flex min-w-0 items-center justify-between gap-2 text-[10px] text-text-muted">
                      <span className="flex min-w-0 items-center gap-1 truncate">
                        <UserCircle className="h-3 w-3 shrink-0" aria-hidden />
                        <span className="truncate">
                          {node.agentLabel ||
                            t('executionDag.unassignedAgent', { defaultValue: 'Unassigned' })}
                        </span>
                      </span>
                      <span className="shrink-0 font-mono">{node.attemptId ?? node.kind}</span>
                    </div>
                    {node.metrics ? (
                      <div className="flex min-w-0 items-center gap-2 text-[10px] text-text-muted">
                        <PackageCheck className="h-3 w-3 shrink-0" aria-hidden />
                        <span className="truncate">
                          {t(
                            'executionDag.metrics',
                            '{{evidence}} refs · {{artifacts}} artifacts',
                            {
                              evidence: node.metrics.evidence ?? 0,
                              artifacts: node.metrics.artifacts ?? 0,
                            }
                          )}
                        </span>
                      </div>
                    ) : null}
                  </div>
                </button>
              </foreignObject>
            );
          })}
        </svg>
      </div>
    );
  }
);

ExecutionDagGraph.displayName = 'ExecutionDagGraph';

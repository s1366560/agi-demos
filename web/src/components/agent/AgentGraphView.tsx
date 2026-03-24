import { memo, useMemo } from 'react';

import { Network, Clock, CheckCircle2, AlertCircle, XCircle, PlayCircle, Loader2 } from 'lucide-react';

import { useActiveGraphRun, useActiveGraphRunNodes, useGraphPanel } from '../../stores/graphStore';

import type { GraphNodeStatus } from '../../stores/graphStore';

const formatDuration = (seconds?: number): string => {
  if (seconds == null) return '--';
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
};

const StatusIcon = memo(({ status }: { status: string }) => {
  switch (status) {
    case 'completed':
      return <CheckCircle2 size={16} className="text-emerald-500" />;
    case 'running':
      return <Loader2 size={16} className="text-blue-500 animate-spin motion-reduce:animate-none" />;
    case 'failed':
      return <XCircle size={16} className="text-red-500" />;
    case 'cancelled':
      return <AlertCircle size={16} className="text-slate-400" />;
    default:
      return <PlayCircle size={16} className="text-slate-400" />;
  }
});

StatusIcon.displayName = 'StatusIcon';

const getNodeStyles = (status: GraphNodeStatus) => {
  switch (status) {
    case 'pending':
      return 'bg-slate-300 border-slate-400 text-slate-800 dark:bg-slate-600 dark:border-slate-500 dark:text-slate-100';
    case 'running':
      return 'bg-blue-500 border-blue-600 text-white animate-pulse motion-reduce:animate-none shadow-lg shadow-blue-500/30';
    case 'completed':
      return 'bg-emerald-500 border-emerald-600 text-white shadow-md shadow-emerald-500/20';
    case 'failed':
      return 'bg-red-500 border-red-600 text-white shadow-md shadow-red-500/20';
    case 'skipped':
      return 'bg-amber-400 border-amber-500 text-amber-900 dark:bg-amber-500 dark:border-amber-600 dark:text-amber-50';
    case 'cancelled':
      return 'bg-slate-400 border-slate-500 text-white dark:bg-slate-500 dark:border-slate-600';
    default:
      return 'bg-slate-300 border-slate-400 text-slate-800 dark:bg-slate-600 dark:border-slate-500 dark:text-slate-100';
  }
};

export const AgentGraphView = memo(() => {
  const panelOpen = useGraphPanel();
  const run = useActiveGraphRun();
  const nodes = useActiveGraphRunNodes();

  const layout = useMemo(() => {
    if (!run || nodes.length === 0) return null;

    const handoffs = run.handoffs || [];

    const inDegree = new Map<string, number>();
    const adjacency = new Map<string, string[]>();

    nodes.forEach((n) => {
      inDegree.set(n.nodeId, 0);
      adjacency.set(n.nodeId, []);
    });

    handoffs.forEach((h) => {
      if (!inDegree.has(h.toNodeId)) inDegree.set(h.toNodeId, 0);
      if (!adjacency.has(h.fromNodeId)) adjacency.set(h.fromNodeId, []);

      inDegree.set(h.toNodeId, (inDegree.get(h.toNodeId) ?? 0) + 1);
      const neighbors = adjacency.get(h.fromNodeId);
      if (neighbors) neighbors.push(h.toNodeId);
    });

    const levels = new Map<string, number>();
    let queue = Array.from(inDegree.entries())
      .filter(([_, deg]) => deg === 0)
      .map(([id]) => id);

    let currentLevel = 0;
    while (queue.length > 0) {
      const nextQueue: string[] = [];
      for (const nodeId of queue) {
        levels.set(nodeId, currentLevel);
        for (const neighbor of adjacency.get(nodeId) || []) {
          const deg = (inDegree.get(neighbor) ?? 0) - 1;
          inDegree.set(neighbor, deg);
          if (deg === 0) {
            nextQueue.push(neighbor);
          }
        }
      }
      queue = nextQueue;
      currentLevel++;
    }

    nodes.forEach((n) => {
      if (!levels.has(n.nodeId)) {
        levels.set(n.nodeId, currentLevel);
      }
    });

    const levelMap = new Map<number, string[]>();
    let maxLevel = 0;
    levels.forEach((lvl, nodeId) => {
      if (!levelMap.has(lvl)) levelMap.set(lvl, []);
      const lvlNodes = levelMap.get(lvl);
      if (lvlNodes) lvlNodes.push(nodeId);
      maxLevel = Math.max(maxLevel, lvl);
    });

    const NODE_WIDTH = 200;
    const NODE_HEIGHT = 64;
    const LEVEL_HEIGHT = 140;
    const NODE_SPACING = 60;

    let maxRowWidth = 0;
    for (const [_, nodeIds] of levelMap.entries()) {
      const w = nodeIds.length * NODE_WIDTH + (nodeIds.length - 1) * NODE_SPACING;
      maxRowWidth = Math.max(maxRowWidth, w);
    }

    const PADDING = 100;
    const SVG_WIDTH = Math.max(600, maxRowWidth + PADDING * 2);
    const SVG_HEIGHT = (maxLevel + 1) * LEVEL_HEIGHT + PADDING;
    const centerX = SVG_WIDTH / 2;

    const positions = new Map<string, { x: number; y: number }>();
    for (let lvl = 0; lvl <= maxLevel; lvl++) {
      const nodeIds = levelMap.get(lvl) || [];
      const rowWidth = nodeIds.length * NODE_WIDTH + (nodeIds.length - 1) * NODE_SPACING;
      let startX = centerX - rowWidth / 2 + NODE_WIDTH / 2;

      nodeIds.forEach((nodeId) => {
        positions.set(nodeId, {
          x: startX,
          y: PADDING / 2 + lvl * LEVEL_HEIGHT,
        });
        startX += NODE_WIDTH + NODE_SPACING;
      });
    }

    return {
      positions,
      SVG_WIDTH,
      SVG_HEIGHT,
      NODE_WIDTH,
      NODE_HEIGHT,
    };
  }, [run, nodes]);

  if (!run || !layout || !panelOpen) {
    return (
      <div className="flex flex-col items-center justify-center h-full w-full p-8 text-slate-400 dark:text-slate-500 bg-slate-50 dark:bg-slate-900 rounded-lg border border-slate-200 dark:border-slate-800">
        <Network size={48} className="mb-4 opacity-20" />
        <h3 className="text-lg font-medium mb-1">No Active Graph</h3>
        <p className="text-sm">Start a multi-agent orchestration to see the graph.</p>
      </div>
    );
  }

  const { positions, SVG_WIDTH, SVG_HEIGHT, NODE_WIDTH, NODE_HEIGHT } = layout;

  return (
    <div className="flex flex-col w-full h-full bg-white dark:bg-slate-950 border border-slate-200 dark:border-slate-800 rounded-lg overflow-hidden">
      <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-100 dark:bg-indigo-900/40 rounded-lg text-indigo-600 dark:text-indigo-400">
            <Network size={20} />
          </div>
          <div>
            <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100 leading-tight">
              {run.graphName}
            </h2>
            {run.pattern && (
              <span className="text-xs text-slate-500 dark:text-slate-400 bg-slate-200 dark:bg-slate-800 px-2 py-0.5 rounded-full mt-1 inline-block">
                {run.pattern}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-1.5 text-sm text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-800 px-3 py-1.5 rounded-full border border-slate-200 dark:border-slate-700 shadow-sm">
            <StatusIcon status={run.status} />
            <span className="capitalize font-medium">{run.status}</span>
          </div>
          <div className="flex items-center gap-1.5 text-sm text-slate-500 dark:text-slate-400">
            <Clock size={16} />
            <span>{formatDuration(run.durationSeconds)}</span>
          </div>
        </div>
      </div>

      <div className="flex-1 overflow-auto relative bg-slate-50/50 dark:bg-slate-950/50 p-4">
        <svg
          width={SVG_WIDTH}
          height={SVG_HEIGHT}
          viewBox={`0 0 ${SVG_WIDTH} ${SVG_HEIGHT}`}
          className="min-w-full min-h-full"
          role="img"
          aria-label="Agent Graph Run Visualization"
        >
          <title>Agent Graph Run Visualization</title>
          <defs>
            <marker
              id="arrowhead"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" className="fill-indigo-400 dark:fill-indigo-600" />
            </marker>
            <marker
              id="arrowhead-active"
              viewBox="0 0 10 10"
              refX="9"
              refY="5"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M 0 0 L 10 5 L 0 10 z" className="fill-blue-500 dark:fill-blue-400" />
            </marker>
          </defs>

          {run.handoffs.map((h) => {
            const fromPos = positions.get(h.fromNodeId);
            const toPos = positions.get(h.toNodeId);
            if (!fromPos || !toPos) return null;

            const startX = fromPos.x;
            const startY = fromPos.y + NODE_HEIGHT / 2;
            const endX = toPos.x;
            const endY = toPos.y - NODE_HEIGHT / 2;

            const midX = (startX + endX) / 2;
            const midY = (startY + endY) / 2;

            const isRecent = h.timestamp > Date.now() - 5000;
            const pathClass = isRecent
              ? 'stroke-blue-500 dark:stroke-blue-400'
              : 'stroke-indigo-400 dark:stroke-indigo-600 opacity-60';

            const markerId = isRecent ? 'url(#arrowhead-active)' : 'url(#arrowhead)';
            const pathData = `M ${startX} ${startY} C ${startX} ${startY + 40}, ${endX} ${
              endY - 40
            }, ${endX} ${endY - 2}`;

            return (
              <g key={`edge-${h.fromNodeId}-${h.toNodeId}-${h.timestamp}`}>
                <path
                  d={pathData}
                  fill="none"
                  className={`${pathClass} transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-500`}
                  strokeWidth="2"
                  strokeDasharray="5 5"
                  markerEnd={markerId}
                />
                <foreignObject
                  x={midX - 60}
                  y={midY - 12}
                  width={120}
                  height={24}
                  className="overflow-visible"
                >
                  <div className="flex justify-center w-full h-full items-center">
                    <span className="text-[10px] font-medium bg-white dark:bg-slate-900 px-2.5 py-0.5 rounded-full border border-indigo-200 dark:border-indigo-800 text-indigo-600 dark:text-indigo-400 shadow-sm truncate max-w-full">
                      Handoff
                    </span>
                  </div>
                </foreignObject>
              </g>
            );
          })}

          {nodes.map((node) => {
            const pos = positions.get(node.nodeId);
            if (!pos) return null;

            const styleClass = getNodeStyles(node.status);
            const pad = 16;

            return (
              <foreignObject
                key={node.nodeId}
                x={pos.x - NODE_WIDTH / 2 - pad}
                y={pos.y - NODE_HEIGHT / 2 - pad}
                width={NODE_WIDTH + pad * 2}
                height={NODE_HEIGHT + pad * 2}
                className="overflow-visible"
              >
                <div className="w-full h-full p-4 flex items-center justify-center">
                  <div
                    className={`w-full h-full rounded-xl border-2 flex flex-col items-center justify-center p-2 transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-300 ${styleClass}`}
                  >
                    <span className="font-semibold text-sm truncate w-full text-center px-2">
                      {node.label}
                    </span>
                    <span className="text-[11px] font-medium opacity-90 uppercase tracking-wider mt-0.5">
                      {node.status}
                    </span>
                  </div>
                </div>
              </foreignObject>
            );
          })}
        </svg>
      </div>
    </div>
  );
});

AgentGraphView.displayName = 'AgentGraphView';

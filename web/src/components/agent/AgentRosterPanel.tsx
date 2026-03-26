/**
 * AgentRosterPanel - Sidebar panel showing agents participating in the active graph run.
 * Displays node status, agent names, durations, and error/skip details.
 */

import { memo, useMemo, useState } from 'react';

import { useTranslation } from 'react-i18next';

import { Drawer } from 'antd';
import {
  Circle,
  Loader2,
  CheckCircle2,
  XCircle,
  SkipForward,
  X,
  Clock,
  Network,
  Trash2,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';

import {
  useActiveGraphRun,
  useActiveGraphRunNodes,
  useGraphPanel,
  useGraphActions,
} from '../../stores/graphStore';

import type { GraphNodeState, GraphRunStatus } from '../../stores/graphStore';

const formatDuration = (seconds: number | undefined): string => {
  if (seconds == null) return '--';
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
};

const formatElapsedFromStart = (
  startedAt: number | undefined,
  completedAt: number | undefined
): string => {
  if (startedAt == null) return '--';
  const ms = (completedAt ?? Date.now()) - startedAt;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
};

const NodeStatusBadge = memo<{ status: GraphNodeState['status'] }>(({ status }) => {
  switch (status) {
    case 'pending':
      return <Circle size={14} className="text-slate-400" />;
    case 'running':
      return (
        <Loader2 size={14} className="text-blue-500 animate-spin motion-reduce:animate-none" />
      );
    case 'completed':
      return <CheckCircle2 size={14} className="text-emerald-500" />;
    case 'failed':
      return <XCircle size={14} className="text-red-500" />;
    case 'skipped':
      return <SkipForward size={14} className="text-amber-500" />;
    case 'cancelled':
      return <X size={14} className="text-slate-400" />;
  }
});

NodeStatusBadge.displayName = 'NodeStatusBadge';

const RunStatusLabel = memo<{ status: GraphRunStatus }>(({ status }) => {
  const colorMap: Record<GraphRunStatus, string> = {
    pending: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400',
    running: 'bg-blue-100 text-blue-600 dark:bg-blue-900/40 dark:text-blue-400',
    completed: 'bg-emerald-100 text-emerald-600 dark:bg-emerald-900/40 dark:text-emerald-400',
    failed: 'bg-red-100 text-red-600 dark:bg-red-900/40 dark:text-red-400',
    cancelled: 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-500',
  };

  return (
    <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${colorMap[status]}`}>
      {status}
    </span>
  );
});

RunStatusLabel.displayName = 'RunStatusLabel';

const NodeItem = memo<{
  node: GraphNodeState;
  isExpanded: boolean;
  onToggleExpand: (id: string) => void;
}>(({ node, isExpanded, onToggleExpand }) => {
  const hasDetails = Boolean(
    node.errorMessage || node.skipReason || (node.outputKeys && node.outputKeys.length > 0)
  );

  const statusBg =
    node.status === 'running'
      ? 'border-blue-200/60 dark:border-blue-800/40 bg-blue-50/50 dark:bg-blue-950/20'
      : node.status === 'completed'
        ? 'border-emerald-200/60 dark:border-emerald-800/30 bg-emerald-50/30 dark:bg-emerald-950/10'
        : node.status === 'failed'
          ? 'border-red-200/60 dark:border-red-800/30 bg-red-50/30 dark:bg-red-950/10'
          : 'border-slate-200/60 dark:border-slate-700/40 bg-slate-50/30 dark:bg-slate-800/20';

  return (
    <div className={`rounded-lg border p-3 ${statusBg} transition-colors`}>
      <div className="flex items-start gap-2">
        <NodeStatusBadge status={node.status} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300 truncate">
              {node.label}
            </span>
            {hasDetails && (
              <button
                type="button"
                onClick={() => {
                  onToggleExpand(node.nodeId);
                }}
                className="p-0.5 rounded text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
              >
                {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
              </button>
            )}
          </div>

          <div className="flex items-center gap-3 mt-1">
            <span className="text-[10px] text-slate-400 flex items-center gap-0.5">
              <Clock size={9} />
              {node.durationSeconds != null
                ? formatDuration(node.durationSeconds)
                : formatElapsedFromStart(node.startedAt, node.completedAt)}
            </span>
            {node.agentDefinitionId && (
              <span className="text-[10px] text-slate-400 truncate max-w-[120px]">
                {node.agentDefinitionId}
              </span>
            )}
          </div>

          {isExpanded && (
            <div className="mt-2 space-y-1.5">
              {node.errorMessage && (
                <div className="p-2 rounded bg-red-50/60 dark:bg-red-950/20 border border-red-200/30 dark:border-red-800/20">
                  <p className="text-xs text-red-600 dark:text-red-400 line-clamp-3">
                    {node.errorMessage}
                  </p>
                </div>
              )}
              {node.skipReason && (
                <div className="p-2 rounded bg-amber-50/60 dark:bg-amber-950/20 border border-amber-200/30 dark:border-amber-800/20">
                  <p className="text-xs text-amber-600 dark:text-amber-400 line-clamp-2">
                    {node.skipReason}
                  </p>
                </div>
              )}
              {node.outputKeys && node.outputKeys.length > 0 && (
                <div className="p-2 rounded bg-white/60 dark:bg-slate-900/40 border border-slate-200/30 dark:border-slate-700/20">
                  <p className="text-[10px] text-slate-500 dark:text-slate-400">
                    Output keys: {node.outputKeys.join(', ')}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
});

NodeItem.displayName = 'NodeItem';

export const AgentRosterPanel = memo(() => {
  const panelOpen = useGraphPanel();

  if (!panelOpen) return null;

  return <AgentRosterDrawer />;
});

AgentRosterPanel.displayName = 'AgentRosterPanel';

const AgentRosterDrawer = memo(() => {
  const { t } = useTranslation();
  const activeRun = useActiveGraphRun();
  const nodes = useActiveGraphRunNodes();
  const { setPanel, clearRun, clearAll } = useGraphActions();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const sorted = useMemo(
    () =>
      [...nodes].sort((a, b) => {
        // Running first, then by start time
        const statusOrder: Record<string, number> = {
          running: 0,
          pending: 1,
          completed: 2,
          failed: 3,
          skipped: 4,
          cancelled: 5,
        };
        const aOrder = statusOrder[a.status] ?? 6;
        const bOrder = statusOrder[b.status] ?? 6;
        if (aOrder !== bOrder) return aOrder - bOrder;
        return (a.startedAt ?? 0) - (b.startedAt ?? 0);
      }),
    [nodes]
  );

  const runningCount = useMemo(() => sorted.filter((n) => n.status === 'running').length, [sorted]);

  return (
    <Drawer
      title={
        <div className="flex items-center gap-2">
          <Network size={16} className="text-indigo-500" />
          <span>{activeRun ? activeRun.graphName : t('agent.graph.title', 'Agent Graph')}</span>
          {activeRun && <RunStatusLabel status={activeRun.status} />}
          {runningCount > 0 && (
            <span className="text-xs px-1.5 py-0.5 rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400">
              {runningCount}
            </span>
          )}
        </div>
      }
      placement="right"
      width={380}
      open={true}
      onClose={() => {
        setPanel(false);
      }}
      destroyOnClose
      extra={
        activeRun && (
          <button
            type="button"
            onClick={() => {
              if (activeRun.status !== 'running') {
                clearRun(activeRun.graphRunId);
              } else {
                clearAll();
              }
            }}
            className="text-xs text-slate-400 hover:text-red-500 transition-colors flex items-center gap-1"
          >
            <Trash2 size={12} />
            {t('agent.graph.clear', 'Clear')}
          </button>
        )
      }
    >
      {!activeRun ? (
        <div className="flex flex-col items-center justify-center py-12 text-slate-400">
          <Network size={32} className="mb-3 opacity-30" />
          <p className="text-sm">{t('agent.graph.noActiveRun', 'No active graph run')}</p>
        </div>
      ) : sorted.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-slate-400">
          <Network size={32} className="mb-3 opacity-30" />
          <p className="text-sm">{t('agent.graph.noNodes', 'Waiting for nodes to start...')}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {activeRun.pattern && (
            <div className="px-3 py-2 rounded-lg bg-slate-50/80 dark:bg-slate-800/40 border border-slate-200/40 dark:border-slate-700/30">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  Pattern
                </span>
                <span className="text-xs font-medium text-slate-600 dark:text-slate-300">
                  {activeRun.pattern}
                </span>
              </div>
              {activeRun.errorMessage && (
                <p className="text-xs text-red-500 mt-1 line-clamp-2">{activeRun.errorMessage}</p>
              )}
            </div>
          )}

          {sorted.map((node) => (
            <NodeItem
              key={node.nodeId}
              node={node}
              isExpanded={expanded.has(node.nodeId)}
              onToggleExpand={toggleExpand}
            />
          ))}
        </div>
      )}
    </Drawer>
  );
});

AgentRosterDrawer.displayName = 'AgentRosterDrawer';

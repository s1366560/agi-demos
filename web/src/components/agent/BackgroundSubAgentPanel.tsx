/**
 * BackgroundSubAgentPanel - Sidebar panel showing background SubAgent executions.
 * Shows running, completed, and failed background tasks with status indicators.
 */

import { memo, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { Drawer } from 'antd';
import {
  Rocket,
  CheckCircle2,
  XCircle,
  Loader2,
  Clock,
  Zap,
  Trash2,
  X,
} from 'lucide-react';

import {
  useBackgroundExecutions,
  useBackgroundPanel,
  useBackgroundActions,
} from '../../stores/backgroundStore';

import type { BackgroundSubAgent } from '../../stores/backgroundStore';

const formatElapsed = (startedAt: number, completedAt?: number): string => {
  const ms = (completedAt || Date.now()) - startedAt;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.round((ms % 60000) / 1000)}s`;
};

const StatusBadge = memo<{ status: BackgroundSubAgent['status'] }>(({ status }) => {
  switch (status) {
    case 'running':
      return <Loader2 size={14} className="text-blue-500 animate-spin" />;
    case 'completed':
      return <CheckCircle2 size={14} className="text-emerald-500" />;
    case 'failed':
      return <XCircle size={14} className="text-red-500" />;
    case 'cancelled':
      return <X size={14} className="text-slate-400" />;
  }
});

StatusBadge.displayName = 'StatusBadge';

const ExecutionItem = memo<{
  execution: BackgroundSubAgent;
  onClear: (id: string) => void;
}>(({ execution, onClear }) => {
  const { t } = useTranslation();

  const statusBg =
    execution.status === 'running'
      ? 'border-blue-200/60 dark:border-blue-800/40 bg-blue-50/50 dark:bg-blue-950/20'
      : execution.status === 'completed'
        ? 'border-emerald-200/60 dark:border-emerald-800/30 bg-emerald-50/30 dark:bg-emerald-950/10'
        : execution.status === 'failed'
          ? 'border-red-200/60 dark:border-red-800/30 bg-red-50/30 dark:bg-red-950/10'
          : 'border-slate-200/60 dark:border-slate-700/40 bg-slate-50/30 dark:bg-slate-800/20';

  return (
    <div className={`rounded-lg border p-3 ${statusBg} transition-colors`}>
      <div className="flex items-start gap-2">
        <StatusBadge status={execution.status} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300 truncate">
              {execution.subagentName}
            </span>
            {execution.status !== 'running' && (
              <button
                onClick={() => onClear(execution.executionId)}
                className="p-0.5 rounded text-slate-400 hover:text-red-500 transition-colors"
                title={t('agent.background.clear', 'Clear')}
              >
                <Trash2 size={12} />
              </button>
            )}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 line-clamp-2">
            {execution.task}
          </p>

          {/* Metadata row */}
          <div className="flex items-center gap-3 mt-1.5">
            <span className="text-[10px] text-slate-400 flex items-center gap-0.5">
              <Clock size={9} />
              {formatElapsed(execution.startedAt, execution.completedAt)}
            </span>
            {execution.tokensUsed != null && execution.tokensUsed > 0 && (
              <span className="text-[10px] text-slate-400 flex items-center gap-0.5">
                <Zap size={9} />
                {execution.tokensUsed < 1000
                  ? execution.tokensUsed
                  : `${(execution.tokensUsed / 1000).toFixed(1)}k`}
              </span>
            )}
          </div>

          {/* Summary or error */}
          {execution.summary && (
            <div className="mt-2 p-2 rounded bg-white/60 dark:bg-slate-900/40 border border-slate-200/30 dark:border-slate-700/20">
              <p className="text-xs text-slate-600 dark:text-slate-400 line-clamp-3">
                {execution.summary}
              </p>
            </div>
          )}
          {execution.error && (
            <div className="mt-2 p-2 rounded bg-red-50/60 dark:bg-red-950/20 border border-red-200/30 dark:border-red-800/20">
              <p className="text-xs text-red-600 dark:text-red-400 line-clamp-3">
                {execution.error}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
});

ExecutionItem.displayName = 'ExecutionItem';

export const BackgroundSubAgentPanel = memo(() => {
  const panelOpen = useBackgroundPanel();

  // Only mount Drawer internals when panel is open to avoid Antd effect loops
  if (!panelOpen) return null;

  return <BackgroundSubAgentDrawer />;
});

BackgroundSubAgentPanel.displayName = 'BackgroundSubAgentPanel';

const BackgroundSubAgentDrawer = memo(() => {
  const { t } = useTranslation();
  const executions = useBackgroundExecutions();
  const { setPanel, clear, clearAll } = useBackgroundActions();

  const sorted = useMemo(
    () => [...executions].sort((a, b) => b.startedAt - a.startedAt),
    [executions],
  );

  const runningCount = useMemo(
    () => sorted.filter((e) => e.status === 'running').length,
    [sorted],
  );

  return (
    <Drawer
      title={
        <div className="flex items-center gap-2">
          <Rocket size={16} className="text-purple-500" />
          <span>
            {t('agent.background.title', 'Background Tasks')}
          </span>
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
      onClose={() => setPanel(false)}
      destroyOnClose
      extra={
        sorted.length > 0 && (
          <button
            onClick={clearAll}
            className="text-xs text-slate-400 hover:text-red-500 transition-colors"
          >
            {t('agent.background.clearAll', 'Clear all')}
          </button>
        )
      }
    >
      {sorted.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12 text-slate-400">
          <Rocket size={32} className="mb-3 opacity-30" />
          <p className="text-sm">
            {t('agent.background.empty', 'No background tasks')}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {sorted.map((exec) => (
            <ExecutionItem key={exec.executionId} execution={exec} onClear={clear} />
          ))}
        </div>
      )}
    </Drawer>
  );
});

BackgroundSubAgentDrawer.displayName = 'BackgroundSubAgentDrawer';

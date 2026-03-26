import { memo, useState, useCallback, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import {
  ChevronDown,
  ChevronRight,
  BarChart3,
  Clock,
  Zap,
  CheckCircle2,
  XCircle,
  Loader2,
} from 'lucide-react';

import { formatDuration, formatTokens } from './subagentUtils';

import type { SubAgentGroup } from './SubAgentTimeline';

interface SubAgentCostSummaryProps {
  groups: SubAgentGroup[];
}

export const SubAgentCostSummary = memo<SubAgentCostSummaryProps>(({ groups }) => {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const toggleExpanded = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);

  const stats = useMemo(() => {
    let completed = 0;
    let running = 0;
    let failed = 0;
    let totalTokens = 0;
    let totalTimeMs = 0;

    groups.forEach((group) => {
      if (group.status === 'success') completed++;
      else if (group.status === 'running') running++;
      else if (group.status === 'error') failed++;

      if (group.tokensUsed) totalTokens += group.tokensUsed;
      if (group.executionTimeMs) totalTimeMs += group.executionTimeMs;
    });

    return {
      totalAgents: groups.length,
      completed,
      running,
      failed,
      totalTokens,
      totalTimeMs,
    };
  }, [groups]);

  if (groups.length === 0) return null;

  return (
    <div className="mt-4 rounded-lg border border-slate-200 dark:border-slate-700/50 bg-white dark:bg-slate-800/30 overflow-hidden text-slate-700 dark:text-slate-300">
      <button
        type="button"
        className="flex w-full items-center justify-between px-3 py-2.5 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
        onClick={toggleExpanded}
        title={
          expanded
            ? t('agent.subagent.cost_hide', 'Hide Summary')
            : t('agent.subagent.cost_show', 'Show Summary')
        }
      >
        <div className="flex items-center gap-2">
          <BarChart3 size={14} className="text-slate-500" />
          <span className="text-xs font-medium">
            {t('agent.subagent.cost_title', 'Execution Summary')}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-500">
            {stats.totalAgents} {t('agent.subagent.cost_totalAgents', 'Total SubAgents')}
          </span>
          {expanded ? (
            <ChevronDown size={14} className="text-slate-400" />
          ) : (
            <ChevronRight size={14} className="text-slate-400" />
          )}
        </div>
      </button>

      {expanded && (
        <div className="px-3 pb-3 pt-1 border-t border-slate-100 dark:border-slate-700/30">
          <div className="grid grid-cols-2 gap-2">
            <div className="flex flex-col p-2 rounded bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700/50">
              <div className="flex items-center gap-1.5 mb-1 text-amber-500">
                <Zap size={12} />
                <span className="text-[10px] font-medium text-slate-500">
                  {t('agent.subagent.cost_totalTokens', 'Total Tokens')}
                </span>
              </div>
              <span className="text-sm font-semibold">{formatTokens(stats.totalTokens)}</span>
            </div>

            <div className="flex flex-col p-2 rounded bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700/50">
              <div className="flex items-center gap-1.5 mb-1 text-blue-500">
                <Clock size={12} />
                <span className="text-[10px] font-medium text-slate-500">
                  {t('agent.subagent.cost_totalTime', 'Total Time')}
                </span>
              </div>
              <span className="text-sm font-semibold">{formatDuration(stats.totalTimeMs)}</span>
            </div>

            <div className="flex flex-col p-2 rounded bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700/50">
              <div className="flex items-center gap-1.5 mb-1 text-emerald-500">
                <CheckCircle2 size={12} />
                <span className="text-[10px] font-medium text-slate-500">
                  {t('agent.subagent.cost_completed', 'Completed')}
                </span>
              </div>
              <span className="text-sm font-semibold">{stats.completed}</span>
            </div>

            <div className="flex flex-col p-2 rounded bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700/50">
              <div className="flex items-center gap-1.5 mb-1">
                {stats.failed > 0 ? (
                  <XCircle size={12} className="text-red-500" />
                ) : (
                  <Loader2
                    size={12}
                    className="text-blue-500 animate-spin motion-reduce:animate-none"
                  />
                )}
                <span className="text-[10px] font-medium text-slate-500">
                  {stats.failed > 0
                    ? t('agent.subagent.cost_failed', 'Failed')
                    : t('agent.subagent.cost_running', 'Running')}
                </span>
              </div>
              <span className="text-sm font-semibold">
                {stats.failed > 0 ? stats.failed : stats.running}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

SubAgentCostSummary.displayName = 'SubAgentCostSummary';

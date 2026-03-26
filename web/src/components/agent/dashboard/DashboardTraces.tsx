/**
 * Dashboard Traces Component
 *
 * Displays recent execution traces with trace timeline visualization.
 */

import { memo, useEffect, useMemo, useState, useCallback } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Activity, RefreshCw, Search } from 'lucide-react';

import {
  useTraceRuns,
  useTraceLoading,
  useTraceChain,
  useTraceChainLoading,
  useGetTraceChain,
  useTraceStore,
} from '../../../stores/traceStore';
import { TraceChainView } from '../multiAgent/TraceChainView';
import { TraceTimeline } from '../multiAgent/TraceTimeline';

import type { SubAgentRunDTO } from '../../../types/multiAgent';

// ============================================================================
// Dashboard Traces Component
// ============================================================================

export const DashboardTraces: FC = memo(() => {
  const { t } = useTranslation();

  const runs = useTraceRuns();
  const isLoading = useTraceLoading();

  const traceChain = useTraceChain();
  const isChainLoading = useTraceChainLoading();
  const getTraceChain = useGetTraceChain();

  const [selectedRun, setSelectedRun] = useState<SubAgentRunDTO | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    // Fetch recent traces on mount
    void useTraceStore.getState().listRuns('default');
  }, []);

  const handleRefresh = useCallback(() => {
    void useTraceStore.getState().listRuns('default');
  }, []);

  const handleSelectRun = useCallback(
    (run: SubAgentRunDTO) => {
      setSelectedRun(run);
      if (run.trace_id) {
        void getTraceChain(run.conversation_id, run.trace_id);
      }
    },
    [getTraceChain]
  );

  const handleCloseDetails = useCallback(() => {
    setSelectedRun(null);
  }, []);

  const filteredRuns = useMemo(() => {
    if (!search) return runs;
    const lower = search.toLowerCase();
    return runs.filter(
      (run) =>
        run.subagent_name.toLowerCase().includes(lower) || run.task.toLowerCase().includes(lower)
    );
  }, [runs, search]);

  // Stats
  const stats = useMemo(() => {
    const completed = runs.filter((r) => r.status === 'completed').length;
    const failed = runs.filter((r) => r.status === 'failed').length;
    const running = runs.filter((r) => r.status === 'running').length;
    return { completed, failed, running, total: runs.length };
  }, [runs]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-slate-900 dark:text-white">
            {t('tenant.dashboard.traces.title', 'Execution Traces')}
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.traces.subtitle', 'Monitor SubAgent execution history')}
          </p>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={isLoading}
          className="inline-flex items-center gap-2 px-3 py-1.5 text-sm text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white transition-colors"
        >
          <RefreshCw
            size={14}
            className={isLoading ? 'animate-spin motion-reduce:animate-none' : ''}
          />
          {t('common.refresh', 'Refresh')}
        </button>
      </div>

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={16} />
        <input
          type="text"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
          }}
          placeholder={t('tenant.dashboard.traces.searchPlaceholder', 'Search traces...')}
          className="w-full pl-9 pr-3 py-2 text-sm border border-slate-200 dark:border-slate-700 rounded-lg bg-white dark:bg-slate-800 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-primary/30 focus:border-primary outline-none"
        />
      </div>

      {/* Stats Summary */}
      <div className="grid grid-cols-4 gap-4">
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.traces.totalRuns', 'Total Runs')}
          </p>
          <p className="mt-1 text-xl font-bold text-slate-900 dark:text-white">{stats.total}</p>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.traces.running', 'Running')}
          </p>
          <p className="mt-1 text-xl font-bold text-blue-600 dark:text-blue-400">{stats.running}</p>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.traces.completed', 'Completed')}
          </p>
          <p className="mt-1 text-xl font-bold text-green-600 dark:text-green-400">
            {stats.completed}
          </p>
        </div>
        <div className="bg-white dark:bg-slate-800 rounded-lg p-4 border border-slate-200 dark:border-slate-700">
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {t('tenant.dashboard.traces.failed', 'Failed')}
          </p>
          <p className="mt-1 text-xl font-bold text-red-600 dark:text-red-400">{stats.failed}</p>
        </div>
      </div>

      {/* Traces Timeline */}
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin motion-reduce:animate-none" />
          </div>
        ) : filteredRuns.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 text-slate-500 dark:text-slate-400">
            <Activity size={48} className="mb-4 text-slate-300 dark:text-slate-600" />
            <p className="text-lg font-medium">
              {t('tenant.dashboard.traces.noTraces', 'No execution traces')}
            </p>
            <p className="text-sm mt-1">
              {search
                ? t('tenant.dashboard.traces.noResults', 'Try a different search term')
                : t(
                    'tenant.dashboard.traces.emptyHint',
                    'SubAgent execution traces will appear here'
                  )}
            </p>
          </div>
        ) : (
          <TraceTimeline
            runs={filteredRuns}
            selectedRunId={selectedRun?.run_id ?? null}
            onSelectRun={handleSelectRun}
          />
        )}
      </div>

      {/* Selected Run Details */}
      {selectedRun && (
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/50">
            <h3 className="text-sm font-bold uppercase tracking-wider text-slate-400">
              {t('tenant.dashboard.traces.traceDetails', 'Trace Chain Details')}
            </h3>
            <button
              type="button"
              onClick={handleCloseDetails}
              className="p-1 rounded-md text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              <span className="sr-only">{t('common.close', 'Close')}</span>
              <span aria-hidden="true">&times;</span>
            </button>
          </div>
          <div className="p-4">
            <TraceChainView
              data={traceChain}
              isLoading={isChainLoading}
              onSelectRun={handleSelectRun}
            />
          </div>
        </div>
      )}
    </div>
  );
});
DashboardTraces.displayName = 'DashboardTraces';

export default DashboardTraces;

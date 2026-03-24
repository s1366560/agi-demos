/**
 * Dashboard Overview Component
 *
 * Displays stats cards (Total SubAgents, Enabled SubAgents, Active Runs, Total Invocations),
 * recent SubAgent executions, and quick action buttons.
 */

import { memo, useEffect, useMemo } from 'react';
import type { FC } from 'react';

import { useTranslation } from 'react-i18next';

import { Activity, Brain, Cpu, Play, Plus, TrendingUp, Zap } from 'lucide-react';

import {
  useEnabledSubAgentsCount,
  useListSubAgents,
  useSubAgentLoading,
  useSubAgents,
  useTotalInvocations,
} from '../../../stores/subagent';
import {
  useActiveRunCount,
  useFetchActiveRunCount,
  useTraceRuns,
  useTraceLoading,
  useListTraceRuns,
} from '../../../stores/traceStore';

import type { SubAgentRunDTO } from '../../../types/multiAgent';

// ============================================================================
// Stat Card Component
// ============================================================================

interface StatCardProps {
  title: string;
  value: string | number;
  icon: React.ElementType;
  iconClass: string;
  bgClass: string;
  trend?: {
    value: number;
    isPositive: boolean;
  };
}

const StatCard: FC<StatCardProps> = memo(
  ({ title, value, icon: Icon, iconClass, bgClass, trend }) => (
    <div className={`${bgClass} rounded-xl p-4 border border-slate-200 dark:border-slate-700`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wide">
            {title}
          </p>
          <p className="mt-2 text-2xl font-bold text-slate-900 dark:text-white">{value}</p>
          {trend && (
            <p
              className={`mt-1 text-xs flex items-center gap-1 ${
                trend.isPositive
                  ? 'text-green-600 dark:text-green-400'
                  : 'text-red-600 dark:text-red-400'
              }`}
            >
              <TrendingUp size={12} className={trend.isPositive ? '' : 'rotate-180'} />
              {trend.value}%
            </p>
          )}
        </div>
        <div className={`p-2 rounded-lg ${iconClass}`}>
          <Icon size={20} />
        </div>
      </div>
    </div>
  )
);
StatCard.displayName = 'StatCard';

// ============================================================================
// Recent Run Item Component
// ============================================================================

interface RecentRunItemProps {
  run: SubAgentRunDTO;
}

const RecentRunItem: FC<RecentRunItemProps> = memo(({ run }) => {
  const statusColors: Record<string, string> = {
    completed: 'bg-green-500',
    running: 'bg-blue-500 animate-pulse motion-reduce:animate-none',
    failed: 'bg-red-500',
    pending: 'bg-slate-400',
    cancelled: 'bg-amber-500',
  };

  const statusColor = statusColors[run.status] ?? 'bg-slate-400';

  return (
    <div className="flex items-center gap-3 py-2">
      <div className={`w-2 h-2 rounded-full ${statusColor}`} />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-900 dark:text-white truncate">
          {run.subagent_name}
        </p>
        <p className="text-xs text-slate-500 dark:text-slate-400 truncate">{run.task}</p>
      </div>
      <span className="text-xs text-slate-400 dark:text-slate-500">
        {run.execution_time_ms !== null ? `${Math.round(run.execution_time_ms / 1000)}s` : '-'}
      </span>
    </div>
  );
});
RecentRunItem.displayName = 'RecentRunItem';

// ============================================================================
// Quick Action Button Component
// ============================================================================

interface QuickActionProps {
  icon: React.ElementType;
  label: string;
  onClick?: () => void;
}

const QuickAction: FC<QuickActionProps> = memo(({ icon: Icon, label, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
  >
    <Icon size={16} />
    {label}
  </button>
));
QuickAction.displayName = 'QuickAction';

// ============================================================================
// Dashboard Overview Component
// ============================================================================

export const DashboardOverview: FC = memo(() => {
  const { t } = useTranslation();

  const subagents = useSubAgents();
  const isLoadingSubAgents = useSubAgentLoading();
  const listSubAgents = useListSubAgents();
  const enabledCount = useEnabledSubAgentsCount();
  const totalInvocations = useTotalInvocations();

  const runs = useTraceRuns();
  const isLoadingRuns = useTraceLoading();
  void useListTraceRuns(); // Initialize the list function
  const activeRunCount = useActiveRunCount();
  const fetchActiveRunCount = useFetchActiveRunCount();

  useEffect(() => {
    listSubAgents();
    fetchActiveRunCount();
  }, [listSubAgents, fetchActiveRunCount]);

  const recentRuns = useMemo(() => {
    return [...runs]
      .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
      .slice(0, 5);
  }, [runs]);

  const isLoading = isLoadingSubAgents || isLoadingRuns;

  return (
    <div className="space-y-6">
      {/* Stats Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title={t('tenant.dashboard.stats.totalSubAgents', 'Total SubAgents')}
          value={subagents.length}
          icon={Brain}
          iconClass="text-blue-600 dark:text-blue-400 bg-blue-100 dark:bg-blue-900/30"
          bgClass="bg-white dark:bg-slate-800"
        />
        <StatCard
          title={t('tenant.dashboard.stats.enabledSubAgents', 'Enabled SubAgents')}
          value={enabledCount}
          icon={Zap}
          iconClass="text-green-600 dark:text-green-400 bg-green-100 dark:bg-green-900/30"
          bgClass="bg-white dark:bg-slate-800"
        />
        <StatCard
          title={t('tenant.dashboard.stats.activeRuns', 'Active Runs')}
          value={activeRunCount}
          icon={Activity}
          iconClass="text-purple-600 dark:text-purple-400 bg-purple-100 dark:bg-purple-900/30"
          bgClass="bg-white dark:bg-slate-800"
        />
        <StatCard
          title={t('tenant.dashboard.stats.totalInvocations', 'Total Invocations')}
          value={totalInvocations.toLocaleString()}
          icon={Cpu}
          iconClass="text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/30"
          bgClass="bg-white dark:bg-slate-800"
        />
      </div>

      {/* Quick Actions */}
      <div className="flex flex-wrap gap-3">
        <QuickAction
          icon={Plus}
          label={t('tenant.dashboard.actions.createSubAgent', 'Create SubAgent')}
        />
        <QuickAction icon={Play} label={t('tenant.dashboard.actions.runTest', 'Run Test')} />
      </div>

      {/* Recent Executions */}
      <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-bold uppercase tracking-wider text-slate-400">
            {t('tenant.dashboard.recentExecutions', 'Recent Executions')}
          </h3>
          {isLoading && (
            <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin motion-reduce:animate-none" />
          )}
        </div>

        {recentRuns.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-slate-500 dark:text-slate-400">
            <Activity size={32} className="mb-2 text-slate-300 dark:text-slate-600" />
            <p className="text-sm">{t('tenant.dashboard.noExecutions', 'No recent executions')}</p>
            <p className="text-xs mt-1">
              {t('tenant.dashboard.noExecutionsHint', 'SubAgent execution traces will appear here')}
            </p>
          </div>
        ) : (
          <div className="divide-y divide-slate-100 dark:divide-slate-700">
            {recentRuns.map((run) => (
              <RecentRunItem key={run.run_id} run={run} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
});
DashboardOverview.displayName = 'DashboardOverview';

export default DashboardOverview;

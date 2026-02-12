/**
 * SubAgentStats - Statistics cards row for SubAgent management page.
 */

import { memo } from 'react';

import { Bot, CheckCircle2, TrendingUp, Zap } from 'lucide-react';
import { useTranslation } from 'react-i18next';

interface StatsCardProps {
  title: string;
  value: string | number;
  icon: React.ReactNode;
}

const StatsCard = memo<StatsCardProps>(({ title, value, icon }) => (
  <div className="bg-white dark:bg-slate-800 p-5 rounded-xl border border-slate-200 dark:border-slate-700">
    <div className="flex items-center justify-between">
      <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{title}</p>
      <div className="text-slate-400 dark:text-slate-500">{icon}</div>
    </div>
    <p className="text-2xl font-bold text-slate-900 dark:text-white mt-2">{value}</p>
  </div>
));

StatsCard.displayName = 'StatsCard';

interface SubAgentStatsProps {
  total: number;
  enabledCount: number;
  avgSuccessRate: number;
  totalInvocations: number;
}

export const SubAgentStats = memo<SubAgentStatsProps>(
  ({ total, enabledCount, avgSuccessRate, totalInvocations }) => {
    const { t } = useTranslation();

    return (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatsCard
          title={t('tenant.subagents.stats.total', 'Total SubAgents')}
          value={total}
          icon={<Bot size={20} />}
        />
        <StatsCard
          title={t('tenant.subagents.stats.enabled', 'Active')}
          value={`${enabledCount} / ${total}`}
          icon={<CheckCircle2 size={20} className="text-emerald-500" />}
        />
        <StatsCard
          title={t('tenant.subagents.stats.successRate', 'Success Rate')}
          value={`${avgSuccessRate}%`}
          icon={<TrendingUp size={20} className="text-blue-500" />}
        />
        <StatsCard
          title={t('tenant.subagents.stats.invocations', 'Total Runs')}
          value={totalInvocations.toLocaleString()}
          icon={<Zap size={20} className="text-purple-500" />}
        />
      </div>
    );
  },
);

SubAgentStats.displayName = 'SubAgentStats';

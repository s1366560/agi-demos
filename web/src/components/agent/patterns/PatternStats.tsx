/**
 * PatternStats - Statistics cards for workflow patterns
 *
 * Displays key metrics: Total Patterns, Success Rate, Deprecated Patterns.
 */

import { MaterialIcon } from '../shared';

export interface PatternStatsProps {
  /** Total number of patterns */
  totalPatterns?: number | undefined;
  /** Total patterns trend (percentage change) */
  totalTrend?: number | undefined;
  /** Average success rate percentage */
  successRate?: number | undefined;
  /** Success rate trend */
  successTrend?: number | undefined;
  /** Number of deprecated patterns */
  deprecatedCount?: number | undefined;
  /** Deprecated trend */
  deprecatedTrend?: number | undefined;
  /** Whether to show compact version */
  compact?: boolean | undefined;
}

interface StatCard {
  id: string;
  label: string;
  value: string | number;
  icon: string;
  color: string;
  trend?: number | undefined;
}

/**
 * PatternStats component
 *
 * @example
 * <PatternStats
 *   totalPatterns={842}
 *   successRate={76}
 *   deprecatedCount={15}
 * />
 */
export function PatternStats({
  totalPatterns = 0,
  totalTrend = 0,
  successRate = 0,
  successTrend = 0,
  deprecatedCount = 0,
  deprecatedTrend = 0,
  compact = false,
}: PatternStatsProps) {
  const formatTrend = (value: number) => {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value}%`;
  };

  const getTrendIcon = (value: number) => {
    return value >= 0 ? 'trending_up' : 'trending_down';
  };

  const getTrendColor = (value: number, positive: boolean) => {
    if (value === 0) return 'text-slate-400';
    if (positive) {
      return value >= 0 ? 'text-emerald-500' : 'text-red-500';
    }
    return value >= 0 ? 'text-red-500' : 'text-emerald-500';
  };

  const stats: StatCard[] = [
    {
      id: 'total',
      label: 'Total Patterns Learned',
      value: totalPatterns,
      icon: 'account_tree',
      color: 'bg-blue-500',
      trend: totalTrend,
    },
    {
      id: 'success',
      label: 'Avg. Success Rate',
      value: `${successRate}%`,
      icon: 'analytics',
      color: 'bg-emerald-500',
      trend: successTrend,
    },
    {
      id: 'deprecated',
      label: 'Deprecated Patterns',
      value: deprecatedCount,
      icon: 'deprecated',
      color: 'bg-slate-500',
      trend: deprecatedTrend,
    },
  ];

  return (
    <div className={`grid ${compact ? 'grid-cols-3 gap-3' : 'grid-cols-1 md:grid-cols-3 gap-4'}`}>
      {stats.map((stat) => (
        <div
          key={stat.id}
          className="bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-xl p-4"
        >
          <div className="flex items-start justify-between">
            {/* Icon */}
            <div
              className={`w-10 h-10 rounded-lg ${stat.color} flex items-center justify-center text-white`}
            >
              <MaterialIcon name={stat.icon as any} size={20} />
            </div>

            {/* Trend Indicator */}
            {stat.trend !== undefined && (
              <div
                className={`flex items-center gap-1 text-sm font-medium ${getTrendColor(
                  stat.trend,
                  stat.id !== 'deprecated'
                )}`}
              >
                <MaterialIcon name={getTrendIcon(stat.trend) as any} size={16} />
                <span>{formatTrend(stat.trend)}</span>
              </div>
            )}
          </div>

          {/* Value */}
          <div className="mt-3">
            <p className="text-2xl font-bold text-slate-900 dark:text-white">{stat.value}</p>
            <p className="text-xs text-slate-500 mt-0.5">{stat.label}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

export default PatternStats;

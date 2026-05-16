/**
 * ExecutionStatsCard - Statistics visualization component
 *
 * Displays aggregate statistics for agent executions including
 * success/failure rates, tool usage, and performance metrics.
 */

import { useTranslation } from 'react-i18next';

import { BarChart3, PlayCircle, CheckCircle, AlertCircle, Timer, Wrench } from 'lucide-react';

import { useThemeColors } from '@/hooks/useThemeColor';

import {
  LazyCard,
  LazyStatistic,
  LazyRow,
  LazyCol,
  LazyProgress,
  LazyTable,
  Tag,
} from '@/components/ui/lazyAntd';

import type { ExecutionStatsResponse } from '../../types/agent';
import type { TFunction } from 'i18next';

interface ExecutionStatsCardProps {
  stats: ExecutionStatsResponse;
}

function tFallback(t: TFunction, key: string, fallback: string): string {
  const translated = t(key, fallback);
  return translated === key ? fallback : translated;
}

export function ExecutionStatsCard({ stats }: ExecutionStatsCardProps) {
  const { t } = useTranslation();
  const colors = useThemeColors({
    success: '--color-success',
    successDark: '--color-success-dark',
  });

  const successRate =
    stats.total_executions > 0 ? (stats.completed_count / stats.total_executions) * 100 : 0;

  const failureRate =
    stats.total_executions > 0 ? (stats.failed_count / stats.total_executions) * 100 : 0;

  // Tool usage table data
  const toolUsageData = Object.entries(stats.tool_usage)
    .map(([tool, count]) => ({
      key: tool,
      tool,
      count: count,
      percentage: ((count / stats.total_executions) * 100).toFixed(1),
    }))
    .sort((a, b) => b.count - a.count);

  const toolColumns = [
    {
      title: tFallback(t, 'agent.executionStats.tool', 'Tool'),
      dataIndex: 'tool',
      key: 'tool',
      render: (tool: string) => (
        <Tag color="blue" className="font-mono text-xs">
          {tool}
        </Tag>
      ),
    },
    {
      title: tFallback(t, 'agent.executionStats.usageCount', 'Usage Count'),
      dataIndex: 'count',
      key: 'count',
      align: 'right' as const,
    },
    {
      title: tFallback(t, 'agent.executionStats.percentage', 'Percentage'),
      dataIndex: 'percentage',
      key: 'percentage',
      align: 'right' as const,
      render: (percentage: string) => `${percentage}%`,
    },
  ];

  return (
    <LazyCard className="mb-6">
      <div className="mb-4">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
          <BarChart3 size={20} className="text-blue-600" />
          {tFallback(t, 'agent.executionStats.title', 'Execution Statistics')}
        </h3>
      </div>

      {/* Key Metrics */}
      <LazyRow gutter={[16, 16]} className="mb-6">
        <LazyCol xs={24} sm={12} lg={6}>
          <LazyCard className="bg-slate-50 dark:bg-slate-800/50 border-slate-200 dark:border-slate-700">
            <LazyStatistic
              title={tFallback(t, 'agent.executionStats.totalExecutions', 'Total Executions')}
              value={stats.total_executions}
              prefix={<PlayCircle size={20} className="text-slate-600" />}
            />
          </LazyCard>
        </LazyCol>

        <LazyCol xs={24} sm={12} lg={6}>
          <LazyCard className="bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-700">
            <LazyStatistic
              title={tFallback(t, 'agent.executionStats.completed', 'Completed')}
              value={stats.completed_count}
              prefix={<CheckCircle size={20} className="text-green-600" />}
              suffix={<span className="text-sm text-slate-500">({successRate.toFixed(1)}%)</span>}
            />
          </LazyCard>
        </LazyCol>

        <LazyCol xs={24} sm={12} lg={6}>
          <LazyCard className="bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-700">
            <LazyStatistic
              title={tFallback(t, 'agent.executionStats.failed', 'Failed')}
              value={stats.failed_count}
              prefix={<AlertCircle size={20} className="text-red-600" />}
              suffix={<span className="text-sm text-slate-500">({failureRate.toFixed(1)}%)</span>}
            />
          </LazyCard>
        </LazyCol>

        <LazyCol xs={24} sm={12} lg={6}>
          <LazyCard className="bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-700">
            <LazyStatistic
              title={tFallback(t, 'agent.executionStats.avgDuration', 'Avg Duration')}
              value={stats.average_duration_ms.toFixed(0)}
              suffix="ms"
              prefix={<Timer size={20} className="text-amber-600" />}
            />
          </LazyCard>
        </LazyCol>
      </LazyRow>

      {/* Success Rate Progress */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
            {tFallback(t, 'agent.executionStats.successRate', 'Success Rate')}
          </span>
          <span className="text-sm text-slate-500">{successRate.toFixed(1)}%</span>
        </div>
        <LazyProgress
          percent={successRate}
          status={successRate >= 80 ? 'success' : successRate >= 50 ? 'normal' : 'exception'}
          strokeColor={{
            '0%': colors.success,
            '100%': colors.successDark,
          }}
        />
      </div>

      {/* Tool Usage Table */}
      {toolUsageData.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3 flex items-center gap-2">
            <Wrench size={16} />
            {tFallback(t, 'agent.executionStats.toolUsageDistribution', 'Tool Usage Distribution')}
          </h4>
          <LazyTable
            dataSource={toolUsageData}
            columns={toolColumns}
            pagination={false}
            size="small"
            className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden"
          />
        </div>
      )}
    </LazyCard>
  );
}

/**
 * ExecutionStatsCard - Statistics visualization component
 *
 * Displays aggregate statistics for agent executions including
 * success/failure rates, tool usage, and performance metrics.
 */

import {
  LazyCard,
  LazyStatistic,
  LazyRow,
  LazyCol,
  LazyProgress,
  LazyTable,
  Tag,
} from '@/components/ui/lazyAntd';

import { MaterialIcon } from './shared';

import type { ExecutionStatsResponse } from '../../types/agent';

interface ExecutionStatsCardProps {
  stats: ExecutionStatsResponse;
}

export function ExecutionStatsCard({ stats }: ExecutionStatsCardProps) {
  const successRate =
    stats.total_executions > 0 ? (stats.completed_count / stats.total_executions) * 100 : 0;

  const failureRate =
    stats.total_executions > 0 ? (stats.failed_count / stats.total_executions) * 100 : 0;

  // Tool usage table data
  const toolUsageData = Object.entries(stats.tool_usage)
    .map(([tool, count]) => ({
      key: tool,
      tool,
      count: count as number,
      percentage: (((count as number) / stats.total_executions) * 100).toFixed(1),
    }))
    .sort((a, b) => b.count - a.count);

  const toolColumns = [
    {
      title: 'Tool',
      dataIndex: 'tool',
      key: 'tool',
      render: (tool: string) => (
        <Tag color="blue" className="font-mono text-xs">
          {tool}
        </Tag>
      ),
    },
    {
      title: 'Usage Count',
      dataIndex: 'count',
      key: 'count',
      align: 'right' as const,
    },
    {
      title: 'Percentage',
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
          <MaterialIcon name="analytics" size={20} className="text-blue-600" />
          Execution Statistics
        </h3>
      </div>

      {/* Key Metrics */}
      <LazyRow gutter={[16, 16]} className="mb-6">
        <LazyCol xs={24} sm={12} lg={6}>
          <LazyCard className="bg-slate-50 dark:bg-slate-800/50 border-slate-200 dark:border-slate-700">
            <LazyStatistic
              title="Total Executions"
              value={stats.total_executions}
              prefix={<MaterialIcon name="play_circle" size={20} className="text-slate-600" />}
            />
          </LazyCard>
        </LazyCol>

        <LazyCol xs={24} sm={12} lg={6}>
          <LazyCard className="bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-700">
            <LazyStatistic
              title="Completed"
              value={stats.completed_count}
              prefix={<MaterialIcon name="check_circle" size={20} className="text-green-600" />}
              suffix={<span className="text-sm text-slate-500">({successRate.toFixed(1)}%)</span>}
            />
          </LazyCard>
        </LazyCol>

        <LazyCol xs={24} sm={12} lg={6}>
          <LazyCard className="bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-700">
            <LazyStatistic
              title="Failed"
              value={stats.failed_count}
              prefix={<MaterialIcon name="error" size={20} className="text-red-600" />}
              suffix={<span className="text-sm text-slate-500">({failureRate.toFixed(1)}%)</span>}
            />
          </LazyCard>
        </LazyCol>

        <LazyCol xs={24} sm={12} lg={6}>
          <LazyCard className="bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-700">
            <LazyStatistic
              title="Avg Duration"
              value={stats.average_duration_ms.toFixed(0)}
              suffix="ms"
              prefix={<MaterialIcon name="timer" size={20} className="text-amber-600" />}
            />
          </LazyCard>
        </LazyCol>
      </LazyRow>

      {/* Success Rate Progress */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
            Success Rate
          </span>
          <span className="text-sm text-slate-500">{successRate.toFixed(1)}%</span>
        </div>
        <LazyProgress
          percent={successRate}
          status={successRate >= 80 ? 'success' : successRate >= 50 ? 'normal' : 'exception'}
          strokeColor={{
            '0%': '#10b981',
            '100%': '#059669',
          }}
        />
      </div>

      {/* Tool Usage Table */}
      {toolUsageData.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3 flex items-center gap-2">
            <MaterialIcon name="build" size={16} />
            Tool Usage Distribution
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

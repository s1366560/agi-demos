/**
 * ExecutionTimelineChart - Timeline visualization component
 *
 * Displays execution activity over time with count, success, and failure metrics.
 */

import { useTranslation } from 'react-i18next';

import { LineChart } from 'lucide-react';

import { useThemeColors } from '@/hooks/useThemeColor';

import { formatDateTime } from '@/utils/date';

import { LazyCard, LazyEmpty } from '@/components/ui/lazyAntd';

import type { ExecutionStatsResponse } from '../../types/agent';

interface ExecutionTimelineChartProps {
  stats: ExecutionStatsResponse;
}

type TimelineDatum = ExecutionStatsResponse['timeline_data'][number];

export function ExecutionTimelineChart({ stats }: ExecutionTimelineChartProps) {
  const { t } = useTranslation();
  const { timeline_data } = stats;
  const colors = useThemeColors({
    success: '--color-success',
    error: '--color-error',
    info: '--color-info',
  });

  if (timeline_data.length === 0) {
    return (
      <LazyCard className="mb-6">
        <LazyEmpty
          description={t('agent.executionTimelineChart.empty', {
            defaultValue: 'No timeline data available',
          })}
        />
      </LazyCard>
    );
  }

  // Calculate max value for scaling
  const maxCount = Math.max(1, ...timeline_data.map((item: TimelineDatum) => item.count));
  const barHeight = 120;

  return (
    <LazyCard className="mb-6">
      <div className="mb-4">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
          <LineChart size={20} className="text-purple-600" />
          {t('agent.executionTimelineChart.title', { defaultValue: 'Execution Timeline' })}
        </h3>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          {t('agent.executionTimelineChart.description', {
            defaultValue: 'Execution activity grouped by hour',
          })}
        </p>
      </div>

      {/* Timeline Chart */}
      <div className="relative overflow-x-auto">
        <div className="flex items-end gap-2 min-w-max pb-8">
          {timeline_data.map((item: TimelineDatum) => {
            const barHeightPx = (item.count / maxCount) * barHeight;
            const completedHeight =
              item.count > 0 ? (item.completed / item.count) * barHeightPx : 0;
            const failedHeight = item.count > 0 ? (item.failed / item.count) * barHeightPx : 0;
            const otherHeight = barHeightPx - completedHeight - failedHeight;

            return (
              <div key={item.time} className="flex flex-col items-center gap-2">
                {/* Bar */}
                <div
                  className="relative w-16 bg-slate-100 dark:bg-slate-800 rounded-t-lg overflow-hidden border border-slate-200 dark:border-slate-700 hover:shadow-lg transition-shadow cursor-pointer group"
                  style={{ height: `${barHeight.toString()}px` }}
                  title={t('agent.executionTimelineChart.barTitle', {
                    time: item.time,
                    total: item.count,
                    completed: item.completed,
                    failed: item.failed,
                    defaultValue:
                      '{{time}}\nTotal: {{total}}\nCompleted: {{completed}}\nFailed: {{failed}}',
                  })}
                >
                  {/* Stack bars from bottom to top */}
                  <div className="absolute bottom-0 left-0 right-0 flex flex-col-reverse">
                    {/* Completed */}
                    {item.completed > 0 && (
                      <div
                        className="bg-emerald-500 dark:bg-emerald-600 transition-[color,background-color,border-color,box-shadow,opacity,transform]"
                        style={{
                          height: `${completedHeight.toString()}px`,
                          backgroundColor: colors.success,
                        }}
                      />
                    )}
                    {/* Failed */}
                    {item.failed > 0 && (
                      <div
                        className="bg-red-500 dark:bg-red-600 transition-[color,background-color,border-color,box-shadow,opacity,transform]"
                        style={{
                          height: `${failedHeight.toString()}px`,
                          backgroundColor: colors.error,
                        }}
                      />
                    )}
                    {/* Other statuses */}
                    {otherHeight > 0 && (
                      <div
                        className="bg-blue-500 dark:bg-blue-600 transition-[color,background-color,border-color,box-shadow,opacity,transform]"
                        style={{
                          height: `${otherHeight.toString()}px`,
                          backgroundColor: colors.info,
                        }}
                      />
                    )}
                  </div>

                  {/* Count label (appears on hover) */}
                  <div className="absolute top-0 left-0 right-0 opacity-0 group-hover:opacity-100 transition-opacity bg-slate-900/90 text-white text-xs font-semibold text-center py-1">
                    {item.count}
                  </div>
                </div>

                {/* Time label */}
                <div className="text-xs text-slate-600 dark:text-slate-400 transform -rotate-45 origin-top-left whitespace-nowrap">
                  {formatDateTime(item.time)}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-6 mt-4 pt-4 border-t border-slate-200 dark:border-slate-700">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded" style={{ backgroundColor: colors.success }} />
          <span className="text-sm text-slate-600 dark:text-slate-400">
            {t('agent.executionTimelineChart.completed', { defaultValue: 'Completed' })}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded" style={{ backgroundColor: colors.error }} />
          <span className="text-sm text-slate-600 dark:text-slate-400">
            {t('agent.executionTimelineChart.failed', { defaultValue: 'Failed' })}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded" style={{ backgroundColor: colors.info }} />
          <span className="text-sm text-slate-600 dark:text-slate-400">
            {t('agent.executionTimelineChart.other', { defaultValue: 'Other' })}
          </span>
        </div>
      </div>
    </LazyCard>
  );
}

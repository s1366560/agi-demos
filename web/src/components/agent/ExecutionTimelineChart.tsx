/**
 * ExecutionTimelineChart - Timeline visualization component
 *
 * Displays execution activity over time with count, success, and failure metrics.
 */

import { Card, Empty } from 'antd';
import { MaterialIcon } from './shared';
import type { ExecutionStatsResponse } from '../../types/agent';

interface ExecutionTimelineChartProps {
  stats: ExecutionStatsResponse;
}

export function ExecutionTimelineChart({ stats }: ExecutionTimelineChartProps) {
  const { timeline_data } = stats;

  if (!timeline_data || timeline_data.length === 0) {
    return (
      <Card className="mb-6">
        <Empty description="No timeline data available" />
      </Card>
    );
  }

  // Calculate max value for scaling
  const maxCount = Math.max(...timeline_data.map((d: any) => d.count as number));
  const barHeight = 120;

  return (
    <Card className="mb-6">
      <div className="mb-4">
        <h3 className="text-lg font-semibold text-slate-900 dark:text-white flex items-center gap-2">
          <MaterialIcon name="show_chart" size={20} className="text-purple-600" />
          Execution Timeline
        </h3>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          Execution activity grouped by hour
        </p>
      </div>

      {/* Timeline Chart */}
      <div className="relative overflow-x-auto">
        <div className="flex items-end gap-2 min-w-max pb-8">
          {timeline_data.map((item: any, index: number) => {
            const barHeightPx = (item.count / maxCount) * barHeight;
            const completedHeight = (item.completed / item.count) * barHeightPx;
            const failedHeight = (item.failed / item.count) * barHeightPx;
            const otherHeight = barHeightPx - completedHeight - failedHeight;

            return (
              <div key={index} className="flex flex-col items-center gap-2">
                {/* Bar */}
                <div
                  className="relative w-16 bg-slate-100 dark:bg-slate-800 rounded-t-lg overflow-hidden border border-slate-200 dark:border-slate-700 hover:shadow-lg transition-shadow cursor-pointer group"
                  style={{ height: `${barHeight}px` }}
                  title={`${item.time}\nTotal: ${item.count}\nCompleted: ${item.completed}\nFailed: ${item.failed}`}
                >
                  {/* Stack bars from bottom to top */}
                  <div className="absolute bottom-0 left-0 right-0 flex flex-col-reverse">
                    {/* Completed */}
                    {item.completed > 0 && (
                      <div
                        className="bg-emerald-500 dark:bg-emerald-600 transition-all"
                        style={{ height: `${completedHeight}px`, backgroundColor: '#10b981' }}
                      />
                    )}
                    {/* Failed */}
                    {item.failed > 0 && (
                      <div
                        className="bg-red-500 dark:bg-red-600 transition-all"
                        style={{ height: `${failedHeight}px`, backgroundColor: '#ef4444' }}
                      />
                    )}
                    {/* Other statuses */}
                    {otherHeight > 0 && (
                      <div
                        className="bg-blue-500 dark:bg-blue-600 transition-all"
                        style={{ height: `${otherHeight}px`, backgroundColor: '#3b82f6' }}
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
                  {new Date(item.time).toLocaleString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    hour: '2-digit',
                  })}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-6 mt-4 pt-4 border-t border-slate-200 dark:border-slate-700">
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded" style={{ backgroundColor: '#10b981' }} />
          <span className="text-sm text-slate-600 dark:text-slate-400">Completed</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded" style={{ backgroundColor: '#ef4444' }} />
          <span className="text-sm text-slate-600 dark:text-slate-400">Failed</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-4 rounded" style={{ backgroundColor: '#3b82f6' }} />
          <span className="text-sm text-slate-600 dark:text-slate-400">Other</span>
        </div>
      </div>
    </Card>
  );
}

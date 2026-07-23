import React, { useEffect, useState, useCallback, useMemo } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';

import { message, Skeleton } from 'antd';
import { AlertCircle, Gauge, Hourglass, ListTodo, Loader2, Play, RefreshCw } from 'lucide-react';

import { formatTimeOnly } from '@/utils/date';
import { logger } from '@/utils/logger';

import { TaskList } from '../../components/tasks/TaskList';
import { taskAPI } from '../../services/api';
import { useTenantStore } from '../../stores/tenant';

import type { ChartData, ChartOptions, ScriptableContext } from 'chart.js';

// Loading fallback for charts
const ChartLoading: React.FC<{ height?: string | undefined }> = ({ height = '200px' }) => {
  const { t } = useTranslation();

  return (
    <div
      className={`w-full ${height} flex items-center justify-center bg-slate-50 dark:bg-slate-800 rounded-lg`}
    >
      <div className="text-center">
        <Loader2 size={24} className="text-blue-600 animate-spin motion-reduce:animate-none" />
        <p className="text-slate-500 dark:text-slate-400 text-xs mt-1">
          {t('tenant.tasks.charts.loading', { defaultValue: 'Loading chart…' })}
        </p>
      </div>
    </div>
  );
};

// Error fallback for charts when the chart.js bundle fails to load
const ChartLoadError: React.FC<{ onRetry: () => void }> = ({ onRetry }) => {
  const { t } = useTranslation();

  return (
    <div
      role="alert"
      className="w-full flex items-center justify-center bg-slate-50 dark:bg-slate-800 rounded-lg p-6"
    >
      <div className="text-center">
        <AlertCircle size={24} className="text-red-500 mx-auto" aria-hidden="true" />
        <p className="text-slate-600 dark:text-slate-300 text-sm mt-2">
          {t('tenant.tasks.charts.loadFailed', { defaultValue: 'Failed to load charts' })}
        </p>
        <button
          type="button"
          onClick={onRetry}
          className="mt-3 inline-flex items-center gap-2 rounded-md border border-slate-200 dark:border-slate-600 px-3 py-1.5 text-sm font-medium text-slate-700 dark:text-slate-200 transition-colors hover:bg-slate-100 dark:hover:bg-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
        >
          <RefreshCw size={14} />
          {t('common.retry')}
        </button>
      </div>
    </div>
  );
};

interface TaskStats {
  total: number;
  pending: number;
  processing?: number | undefined;
  running?: number | undefined;
  completed: number;
  failed: number;
  throughput_per_minute?: number | undefined;
  error_rate?: number | undefined;
}

interface QueueDepth {
  queues?: Record<string, number> | undefined;
  total?: number | undefined;
  depth?: number | undefined;
  timestamp?: string | undefined;
}

type LineChartComponent = React.ComponentType<{
  data: ChartData<'line', number[], string>;
  options: ChartOptions<'line'>;
}>;

interface ChartComponents {
  Line: LineChartComponent;
}

// Inner component that uses Chart.js
const TaskDashboardInner: React.FC<{
  Line: LineChartComponent;
  stats: TaskStats | null;
  setStats: (s: TaskStats | null) => void;
  queueDepth: QueueDepth | null;
  setQueueDepth: (qd: QueueDepth | null) => void;
  loading: boolean;
  setLoading: (l: boolean) => void;
  refreshing: boolean;
  setRefreshing: (r: boolean) => void;
  loadError: string | null;
  setLoadError: (e: string | null) => void;
  queueHistory: { time: string; count: number }[];
  setQueueHistory: (
    h:
      | { time: string; count: number }[]
      | ((prev: { time: string; count: number }[]) => { time: string; count: number }[])
  ) => void;
}> = ({
  Line,
  stats,
  setStats,
  queueDepth,
  setQueueDepth,
  loading,
  setLoading,
  refreshing,
  setRefreshing,
  loadError,
  setLoadError,
  queueHistory,
  setQueueHistory,
}) => {
  const { t } = useTranslation();
  const [resuming, setResuming] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
  const { tenantId: routeTenantId } = useParams<{ tenantId?: string | undefined }>();
  const currentTenantId = useTenantStore((state) => state.currentTenant?.id ?? null);
  const tenantId = routeTenantId ?? currentTenantId ?? null;
  const deadLetterQueuePath = tenantId
    ? `/tenant/${tenantId}/dead-letter-queue`
    : '/tenant/dead-letter-queue';

  const fetchData = useCallback(async () => {
    try {
      const [statsData, queueData] = await Promise.all([
        taskAPI.getStats(),
        taskAPI.getQueueDepth(),
      ]);

      setStats(statsData);
      setQueueDepth(queueData);
      setLoadError(null);
      setLastUpdatedAt(new Date());

      // Update queue history for chart
      setQueueHistory((prev: { time: string; count: number }[]) => {
        const now = new Date();
        const total = (queueData as { total?: number | undefined }).total;
        const depth = (queueData as { depth?: number | undefined }).depth;
        const count = total ?? depth ?? 0;
        const newPoint = {
          time: formatTimeOnly(now),
          count,
        };
        const newHistory = [...prev, newPoint];
        if (newHistory.length > 20) newHistory.shift(); // Keep last 20 points
        return newHistory;
      });

      setLoading(false);
      setRefreshing(false);
    } catch (error) {
      logger.error('Failed to fetch task dashboard data', error);
      setLoadError(t('tenant.tasks.loadFailed'));
      setLoading(false);
      setRefreshing(false);
    }
  }, [setStats, setQueueDepth, setQueueHistory, setLoading, setRefreshing, setLoadError, t]);

  useEffect(() => {
    void fetchData();
    const interval = setInterval(() => {
      if (document.hidden) return;
      void fetchData();
    }, 5000);
    return () => {
      clearInterval(interval);
    };
  }, [fetchData]);

  const handleRefresh = () => {
    setRefreshing(true);
    void fetchData();
  };

  const handleResumePending = async () => {
    setResuming(true);
    try {
      const result = await taskAPI.retryPendingTasks({ limit: 5 });
      void message.success(
        t('tenant.tasks.resumeSubmitted', {
          count: result.submitted,
          defaultValue: 'Submitted {{count}} pending tasks',
        })
      );
      await fetchData();
    } catch (error) {
      console.error('Failed to resume pending tasks:', error);
      void message.error(
        t('tenant.tasks.resumeFailed', {
          defaultValue: 'Failed to resume pending tasks',
        })
      );
    } finally {
      setResuming(false);
    }
  };

  // Chart Configurations
  const lineChartOptions = useMemo<ChartOptions<'line'>>(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false,
        },
        tooltip: {
          mode: 'index' as const,
          intersect: false,
        },
      },
      scales: {
        x: {
          grid: {
            display: false,
          },
          ticks: {
            color: '#64748b',
            font: {
              size: 11,
            },
          },
        },
        y: {
          beginAtZero: true,
          grid: {
            color: 'rgba(226, 232, 240, 0.5)',
          },
          ticks: {
            color: '#64748b',
            font: {
              size: 11,
            },
          },
        },
      },
      elements: {
        line: {
          tension: 0.4,
        },
        point: {
          radius: 0,
          hitRadius: 10,
          hoverRadius: 4,
        },
      },
      interaction: {
        mode: 'nearest' as const,
        axis: 'x' as const,
        intersect: false,
      },
    }),
    []
  );

  const lineChartData = useMemo<ChartData<'line', number[], string>>(
    () => ({
      labels: queueHistory.map((h) => h.time),
      datasets: [
        {
          label: t('tenant.tasks.charts.pending_tasks'),
          data: queueHistory.map((h) => h.count),
          borderColor: '#2563eb',
          backgroundColor: (context: ScriptableContext<'line'>) => {
            const ctx = context.chart.ctx;
            const gradient = ctx.createLinearGradient(0, 0, 0, 200);
            gradient.addColorStop(0, 'rgba(37, 99, 235, 0.2)');
            gradient.addColorStop(1, 'rgba(37, 99, 235, 0)');
            return gradient;
          },
          fill: true,
          borderWidth: 2,
        },
      ],
    }),
    [queueHistory, t]
  );

  if (loading && !stats) {
    return (
      <div
        className="mx-auto max-w-full flex flex-col gap-6 py-2"
        role="status"
        aria-label={t('common.loading')}
      >
        <Skeleton active title={{ width: '30%' }} paragraph={{ rows: 6 }} />
        <Skeleton active title={false} paragraph={{ rows: 4 }} />
      </div>
    );
  }

  if (!stats && loadError) {
    return (
      <div className="mx-auto max-w-full flex flex-col gap-6">
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300"
        >
          <div className="flex items-center gap-2">
            <AlertCircle size={16} aria-hidden="true" />
            <span>{loadError}</span>
          </div>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-2 rounded-md border border-red-200 px-3 py-1 text-sm font-medium transition-colors hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 disabled:opacity-50 dark:border-red-800 dark:hover:bg-red-900/40"
          >
            <RefreshCw
              className={`size-4 ${refreshing ? 'animate-spin motion-reduce:animate-none' : ''}`}
            />
            {t('common.retry')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-full flex flex-col gap-6">
      {/* Page Heading */}
      <div className="flex flex-wrap justify-between items-end gap-4 py-2">
        <div className="flex flex-col gap-1">
          <h1 className="text-slate-900 dark:text-white tracking-tight text-[32px] font-bold leading-tight">
            {t('tenant.tasks.title')}
          </h1>
          <p className="text-slate-500 dark:text-slate-400 text-sm font-normal leading-normal">
            {t('tenant.tasks.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdatedAt ? (
            <span className="text-xs tabular-nums text-slate-400 dark:text-slate-500">
              {t('tenant.tasks.lastUpdated', {
                time: formatTimeOnly(lastUpdatedAt),
                defaultValue: 'Updated {{time}}',
              })}
            </span>
          ) : null}
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => {
                void handleResumePending();
              }}
              disabled={resuming || refreshing || !stats?.pending}
              title={t('tenant.tasks.resumePendingHint', {
                defaultValue: 'Resumes up to 5 pending tasks per run',
              })}
              className="bg-slate-900 dark:bg-white border border-slate-900 dark:border-white text-white dark:text-slate-950 px-4 py-2 rounded text-sm font-medium hover:bg-slate-700 dark:hover:bg-slate-200 flex items-center gap-2 transition-colors disabled:opacity-50"
            >
              <Play
                className={`size-4 ${resuming ? 'animate-pulse motion-reduce:animate-none' : ''}`}
              />
              {t('tenant.tasks.resumePending', { defaultValue: 'Resume pending' })}
            </button>
            <button
              type="button"
              onClick={handleRefresh}
              disabled={refreshing}
              className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white px-4 py-2 rounded text-sm font-medium shadow-sm hover:bg-slate-50 dark:hover:bg-slate-700 flex items-center gap-2 transition-colors disabled:opacity-50"
            >
              <RefreshCw
                className={`size-5 ${refreshing ? 'animate-spin motion-reduce:animate-none' : ''}`}
              />
              {t('tenant.tasks.refresh')}
            </button>
          </div>
        </div>
      </div>

      {/* KPI Stats Cards */}
      {loadError ? (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-red-200 bg-red-50 p-4 text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300"
        >
          <div className="flex items-center gap-2">
            <AlertCircle size={16} aria-hidden="true" />
            <span>{loadError}</span>
          </div>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing}
            className="flex items-center gap-2 rounded-md border border-red-200 px-3 py-1 text-sm font-medium transition-colors hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 disabled:opacity-50 dark:border-red-800 dark:hover:bg-red-900/40"
          >
            <RefreshCw
              className={`size-4 ${refreshing ? 'animate-spin motion-reduce:animate-none' : ''}`}
            />
            {t('common.retry')}
          </button>
        </div>
      ) : null}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Total Tasks */}
        <div className="flex flex-col gap-2 rounded-xl p-5 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm">
          <div className="flex justify-between items-start">
            <p className="text-slate-500 dark:text-slate-400 text-sm font-medium">
              {t('tenant.tasks.stats.total')}
            </p>
            <ListTodo className="text-slate-400 dark:text-slate-500 size-5" />
          </div>
          <div className="flex items-end gap-2 mt-2">
            <p className="text-slate-900 dark:text-white text-2xl font-bold leading-none tabular-nums">
              {stats?.total.toLocaleString()}
            </p>
          </div>
        </div>

        {/* Throughput */}
        <div className="flex flex-col gap-2 rounded-xl p-5 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm">
          <div className="flex justify-between items-start">
            <p className="text-slate-500 dark:text-slate-400 text-sm font-medium">
              {t('tenant.tasks.stats.throughput')}
            </p>
            <Gauge className="text-slate-400 dark:text-slate-500 size-5" />
          </div>
          <div className="flex items-end gap-2 mt-2">
            <p className="text-slate-900 dark:text-white text-2xl font-bold leading-none tabular-nums">
              {stats?.throughput_per_minute?.toFixed(1) || '0.0'}/min
            </p>
          </div>
        </div>

        {/* Pending */}
        <div className="flex flex-col gap-2 rounded-xl p-5 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm">
          <div className="flex justify-between items-start">
            <p className="text-slate-500 dark:text-slate-400 text-sm font-medium">
              {t('tenant.tasks.stats.pending')}
            </p>
            <Hourglass className="text-slate-400 dark:text-slate-500 size-5" />
          </div>
          <div className="flex items-end gap-2 mt-2">
            <p className="text-slate-900 dark:text-white text-2xl font-bold leading-none tabular-nums">
              {stats?.pending.toLocaleString()}
            </p>
          </div>
        </div>

        {/* Failed */}
        <div className="flex flex-col gap-2 rounded-xl p-5 bg-white dark:bg-slate-800 border border-red-200 dark:border-red-900/60 shadow-sm">
          <div className="flex justify-between items-start">
            <p className="text-slate-500 dark:text-slate-400 text-sm font-medium">
              {t('tenant.tasks.stats.failed')}
            </p>
            <AlertCircle className="text-red-500 size-5" />
          </div>
          <div className="flex items-end gap-2 mt-2">
            <p className="text-slate-900 dark:text-white text-2xl font-bold leading-none tabular-nums">
              {stats?.failed.toLocaleString()}
            </p>
            <span className="text-slate-500 dark:text-slate-400 text-xs font-normal">
              {stats?.error_rate?.toFixed(1) || '0.0'}% {t('tenant.tasks.stats.rate')}
            </span>
          </div>
          <Link
            to={deadLetterQueuePath}
            className="mt-1 text-xs font-medium text-red-600 transition-colors hover:text-red-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400 dark:text-red-400 dark:hover:text-red-300"
          >
            {t('tenant.tasks.viewDeadLetterQueue', { defaultValue: 'View dead letter queue' })}
          </Link>
        </div>
      </div>

      {/* Charts Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Queue Depth Chart */}
        <div className="lg:col-span-2 flex flex-col gap-4 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-6 shadow-sm">
          <div className="flex justify-between items-center">
            <div>
              <p className="text-slate-900 dark:text-white text-lg font-semibold leading-normal">
                {t('tenant.tasks.charts.queue_depth')}
              </p>
              <p className="text-slate-500 dark:text-slate-400 text-sm font-normal">
                {t('tenant.tasks.charts.queue_desc')}
              </p>
            </div>
            <div className="text-right">
              <p className="text-slate-900 dark:text-white text-2xl font-bold">
                {t('tenant.tasks.charts.current')}: {queueDepth?.total ?? queueDepth?.depth ?? 0}
              </p>
            </div>
          </div>
          <div className="w-full h-50 mt-2 relative">
            <Line options={lineChartOptions} data={lineChartData} />
          </div>
        </div>

        {/* Task Breakdown (Progress Bars) */}
        <div className="flex flex-col gap-4 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-6 shadow-sm">
          <div>
            <p className="text-slate-900 dark:text-white text-lg font-semibold leading-normal">
              {t('tenant.tasks.charts.status_dist')}
            </p>
            <p className="text-slate-500 dark:text-slate-400 text-sm font-normal">
              {t('tenant.tasks.charts.dist_desc')}
            </p>
          </div>
          <div className="flex flex-col justify-center flex-1 gap-5">
            {[
              {
                label: t('common.status.completed'),
                value: stats?.completed || 0,
                color: 'bg-green-600',
                total: stats?.total || 1,
              },
              {
                label: t('common.status.processing'),
                value: stats?.processing || 0,
                color: 'bg-blue-600',
                total: stats?.total || 1,
              },
              {
                label: t('common.status.failed'),
                value: stats?.failed || 0,
                color: 'bg-red-500',
                total: stats?.total || 1,
              },
              {
                label: t('common.status.pending'),
                value: stats?.pending || 0,
                color: 'bg-yellow-500',
                total: stats?.total || 1,
              },
            ].map((item) => (
              <div key={item.label} className="space-y-1">
                <div className="flex justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400 font-medium">
                    {item.label}
                  </span>
                  <span className="text-slate-900 dark:text-white font-bold">
                    {item.value.toLocaleString()}
                  </span>
                </div>
                <div className="h-2 w-full bg-slate-100 dark:bg-slate-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full ${item.color} rounded-full transition-[width] duration-500`}
                    style={{
                      width:
                        item.value === 0
                          ? '0%'
                          : `${Math.max(2, (item.value / item.total) * 100).toString()}%`,
                    }}
                  ></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Reusable Task List */}
      <TaskList />
    </div>
  );
};

// Chart.js wrapper component - lazy loaded
const ChartJSLib: React.FC<{ children: (props: ChartComponents) => React.ReactNode }> = ({
  children,
}) => {
  return (
    <React.Suspense fallback={<ChartLoading />}>
      <ChartJSLibInner>{children}</ChartJSLibInner>
    </React.Suspense>
  );
};

const ChartJSLibInner: React.FC<{ children: (props: ChartComponents) => React.ReactNode }> = ({
  children,
}) => {
  const [chartComponents, setChartComponents] = React.useState<ChartComponents | null>(null);
  const [chartLoadFailed, setChartLoadFailed] = React.useState(false);
  const [chartRetryKey, setChartRetryKey] = React.useState(0);

  React.useEffect(() => {
    let mounted = true;
    void Promise.all([import('chart.js'), import('react-chartjs-2')])
      .then(([chartJsModule, reactChartModule]) => {
        if (mounted) {
          const {
            Chart: ChartJS,
            CategoryScale,
            LinearScale,
            PointElement,
            LineElement,
            Title,
            Tooltip,
            Legend,
            Filler,
          } = chartJsModule;

          ChartJS.register(
            CategoryScale,
            LinearScale,
            PointElement,
            LineElement,
            Title,
            Tooltip,
            Legend,
            Filler
          );

          setChartComponents({ Line: reactChartModule.Line as LineChartComponent });
        }
      })
      .catch((error: unknown) => {
        logger.error('Failed to load chart modules', error);
        if (mounted) {
          setChartLoadFailed(true);
        }
      });
    return () => {
      mounted = false;
    };
  }, [chartRetryKey]);

  if (chartLoadFailed) {
    return (
      <ChartLoadError
        onRetry={() => {
          setChartLoadFailed(false);
          setChartComponents(null);
          setChartRetryKey((key) => key + 1);
        }}
      />
    );
  }

  if (!chartComponents) {
    return <ChartLoading />;
  }

  return <>{children(chartComponents)}</>;
};

// Public TaskDashboard component with lazy loaded charts
export const TaskDashboard: React.FC = () => {
  const [stats, setStats] = useState<TaskStats | null>(null);
  const [queueDepth, setQueueDepth] = useState<QueueDepth | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [queueHistory, setQueueHistory] = useState<{ time: string; count: number }[]>([]);

  // Only render charts on client-side to avoid hydration issues (rendering-hydration-no-flicker)
  const [isClient, setIsClient] = useState(false);

  useEffect(() => {
    queueMicrotask(() => {
      setIsClient(true);
    });
  }, []);

  if (!isClient) {
    return (
      <div className="flex items-center justify-center h-full" role="status">
        <div className="animate-spin motion-reduce:animate-none rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  return (
    <ChartJSLib>
      {({ Line }) => (
        <TaskDashboardInner
          Line={Line}
          stats={stats}
          setStats={setStats}
          queueDepth={queueDepth}
          setQueueDepth={setQueueDepth}
          loading={loading}
          setLoading={setLoading}
          refreshing={refreshing}
          setRefreshing={setRefreshing}
          loadError={loadError}
          setLoadError={setLoadError}
          queueHistory={queueHistory}
          setQueueHistory={setQueueHistory}
        />
      )}
    </ChartJSLib>
  );
};

export default TaskDashboard;

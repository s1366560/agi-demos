import React, { useEffect, useState, useCallback, useMemo } from 'react';

import { useTranslation } from 'react-i18next';

import { RefreshCw, Plus, ListTodo, Gauge, Hourglass, AlertCircle } from 'lucide-react';

import { formatTimeOnly } from '@/utils/date';

import { TaskList } from '../../components/tasks/TaskList';
import { taskAPI } from '../../services/api';

// Loading fallback for charts
const ChartLoading: React.FC<{ height?: string }> = ({ height = '200px' }) => (
  <div
    className={`w-full ${height} flex items-center justify-center bg-slate-50 dark:bg-slate-800 rounded-lg`}
  >
    <div className="text-center">
      <span className="material-symbols-outlined text-2xl text-blue-600 animate-spin">
        progress_activity
      </span>
      <p className="text-slate-500 dark:text-slate-400 text-xs mt-1">Loading chart...</p>
    </div>
  </div>
);

interface TaskStats {
  total: number;
  pending: number;
  processing?: number;
  running?: number;
  completed: number;
  failed: number;
  throughput_per_minute?: number;
  error_rate?: number;
}

interface QueueDepth {
  queues?: Record<string, number>;
  total?: number;
  depth?: number;
  timestamp?: string;
}

// Inner component that uses Chart.js
const TaskDashboardInner: React.FC<{
  ChartJS: any;
  Line: any;
  stats: TaskStats | null;
  setStats: (s: TaskStats | null) => void;
  queueDepth: QueueDepth | null;
  setQueueDepth: (qd: QueueDepth | null) => void;
  loading: boolean;
  setLoading: (l: boolean) => void;
  refreshing: boolean;
  setRefreshing: (r: boolean) => void;
  queueHistory: { time: string; count: number }[];
  setQueueHistory: (
    h:
      | { time: string; count: number }[]
      | ((prev: { time: string; count: number }[]) => { time: string; count: number }[])
  ) => void;
}> = ({
  ChartJS: _ChartJS,
  Line,
  stats,
  setStats,
  queueDepth,
  setQueueDepth,
  loading,
  setLoading,
  refreshing,
  setRefreshing,
  queueHistory,
  setQueueHistory,
}) => {
  const { t } = useTranslation();

  const fetchData = useCallback(async () => {
    try {
      const [statsData, queueData] = await Promise.all([
        taskAPI.getStats(),
        taskAPI.getQueueDepth(),
      ]);

      setStats(statsData);
      setQueueDepth(queueData);

      // Update queue history for chart
      setQueueHistory((prev: { time: string; count: number }[]) => {
        const now = new Date();
        const total = (queueData as { total?: number }).total;
        const depth = (queueData as { depth?: number }).depth;
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
      console.error('Failed to fetch task dashboard data:', error);
      setLoading(false);
      setRefreshing(false);
    }
  }, [setStats, setQueueDepth, setQueueHistory, setLoading, setRefreshing]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => { clearInterval(interval); };
  }, [fetchData]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  // Chart Configurations
  const lineChartOptions = useMemo(
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

  const lineChartData = useMemo(
    () => ({
      labels: queueHistory.map((h) => h.time),
      datasets: [
        {
          label: t('tenant.tasks.charts.pending_tasks'),
          data: queueHistory.map((h) => h.count),
          borderColor: '#2563eb',
          backgroundColor: (context: any) => {
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
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-full flex flex-col gap-6">
      {/* Page Heading */}
      <div className="flex flex-wrap justify-between items-end gap-4 py-2">
        <div className="flex flex-col gap-1">
          <h2 className="text-slate-900 dark:text-white tracking-tight text-[32px] font-bold leading-tight">
            {t('tenant.tasks.title')}
          </h2>
          <p className="text-slate-500 dark:text-slate-400 text-sm font-normal leading-normal">
            {t('tenant.tasks.subtitle')}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-900 dark:text-white px-4 py-2 rounded-lg text-sm font-medium shadow-sm hover:bg-slate-50 dark:hover:bg-slate-700 flex items-center gap-2 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`size-5 ${refreshing ? 'animate-spin' : ''}`} />
            {t('tenant.tasks.refresh')}
          </button>
          <button className="bg-primary text-white px-4 py-2 rounded-lg text-sm font-medium shadow-sm hover:bg-blue-700 flex items-center gap-2 transition-colors">
            <Plus className="size-5" />
            {t('tenant.tasks.new_task')}
          </button>
        </div>
      </div>

      {/* KPI Stats Cards */}
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
            <p className="text-slate-900 dark:text-white text-2xl font-bold leading-none">
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
            <p className="text-slate-900 dark:text-white text-2xl font-bold leading-none">
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
            <p className="text-slate-900 dark:text-white text-2xl font-bold leading-none">
              {stats?.pending.toLocaleString()}
            </p>
          </div>
        </div>

        {/* Failed */}
        <div className="flex flex-col gap-2 rounded-xl p-5 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-sm relative overflow-hidden">
          <div className="absolute right-0 top-0 h-full w-1 bg-red-500"></div>
          <div className="flex justify-between items-start">
            <p className="text-slate-500 dark:text-slate-400 text-sm font-medium">
              {t('tenant.tasks.stats.failed')}
            </p>
            <AlertCircle className="text-red-500 size-5" />
          </div>
          <div className="flex items-end gap-2 mt-2">
            <p className="text-slate-900 dark:text-white text-2xl font-bold leading-none">
              {stats?.failed.toLocaleString()}
            </p>
            <span className="text-slate-500 dark:text-slate-400 text-xs font-normal">
              {stats?.error_rate?.toFixed(1) || '0.0'}% {t('tenant.tasks.stats.rate')}
            </span>
          </div>
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
                {t('tenant.tasks.charts.current')}: {queueDepth?.total}
              </p>
            </div>
          </div>
          <div className="w-full h-[200px] mt-2 relative">
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
                    className={`h-full ${item.color} rounded-full transition-all duration-500`}
                    style={{ width: `${Math.max(2, (item.value / item.total) * 100)}%` }}
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
const ChartJSLib: React.FC<{ children: (props: any) => React.ReactNode }> = ({ children }) => {
  return (
    <React.Suspense fallback={<ChartLoading />}>
      <ChartJSLibInner>{children}</ChartJSLibInner>
    </React.Suspense>
  );
};

const ChartJSLibInner: React.FC<{ children: (props: any) => React.ReactNode }> = ({ children }) => {
  const [ChartJSModule, setChartJSModule] = React.useState<any>(null);

  React.useEffect(() => {
    let mounted = true;
    Promise.all([import('chart.js'), import('react-chartjs-2')]).then(
      ([chartJsModule, reactChartModule]) => {
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

          setChartJSModule({ ChartJS, Line: reactChartModule.Line });
        }
      }
    );
    return () => {
      mounted = false;
    };
  }, []);

  if (!ChartJSModule) {
    return <ChartLoading />;
  }

  return <>{children({ ChartJS: ChartJSModule.ChartJS, Line: ChartJSModule.Line })}</>;
};

// Public TaskDashboard component with lazy loaded charts
export const TaskDashboard: React.FC = () => {
  const [stats, setStats] = useState<TaskStats | null>(null);
  const [queueDepth, setQueueDepth] = useState<QueueDepth | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [queueHistory, setQueueHistory] = useState<{ time: string; count: number }[]>([]);

  // Only render charts on client-side to avoid hydration issues (rendering-hydration-no-flicker)
  const [isClient, setIsClient] = useState(false);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- Necessary for client-side hydration check
  useEffect(() => { setIsClient(true); }, []);

  if (!isClient) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  return (
    <ChartJSLib>
      {({ ChartJS, Line }: any) => (
        <TaskDashboardInner
          ChartJS={ChartJS}
          Line={Line}
          stats={stats}
          setStats={setStats}
          queueDepth={queueDepth}
          setQueueDepth={setQueueDepth}
          loading={loading}
          setLoading={setLoading}
          refreshing={refreshing}
          setRefreshing={setRefreshing}
          queueHistory={queueHistory}
          setQueueHistory={setQueueHistory}
        />
      )}
    </ChartJSLib>
  );
};

export default TaskDashboard;

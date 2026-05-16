import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import {
  BadgeCheck,
  Database,
  Diamond,
  FolderOpen,
  Globe,
  MoreVertical,
  Plug,
  Users,
} from 'lucide-react';

import { tenantAPI } from '../../services/api';
import { useTenantStore } from '../../stores/tenant';

interface TenantOverviewProject {
  id: string;
  name: string;
  owner: string;
  memory_consumed: string;
  status?: string | null;
}

interface TenantMemoryHistoryPoint {
  date: string;
  used: number;
  daily_added: number;
  memory_count: number;
  percentage: number;
}

interface TenantOverviewStats {
  storage: {
    used: number;
    total: number;
    percentage: number;
  };
  projects: {
    active: number;
    new_this_week: number;
    list: TenantOverviewProject[];
  };
  members: {
    total: number;
    new_added: number;
  };
  memory_history?: TenantMemoryHistoryPoint[];
  tenant_info: {
    organization_id: string;
    plan: string;
    region?: string | null;
    next_billing_date?: string | null;
  };
}

const clampPercent = (value: number): number => Math.max(0, Math.min(100, value));

const formatStorage = (bytes: number) => {
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = bytes / (1024 * 1024);
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  const tb = bytes / (1024 * 1024 * 1024 * 1024);
  if (tb >= 1) return `${tb.toFixed(1)} TB`;
  const gb = bytes / (1024 * 1024 * 1024);
  return `${gb.toFixed(1)} GB`;
};

const isActiveProject = (status?: string | null): boolean => status?.toLowerCase() === 'active';

const hasValue = (value?: string | null): value is string => Boolean(value?.trim());

const buildMemoryChartPoints = (history: TenantMemoryHistoryPoint[]) => {
  if (history.length === 0) return [];

  const lastIndex = Math.max(history.length - 1, 1);
  return history.map((point, index) => ({
    x: (index / lastIndex) * 100,
    y: 50 - (clampPercent(point.percentage) / 100) * 44,
  }));
};

const buildLinePath = (points: Array<{ x: number; y: number }>) =>
  points
    .map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(2)},${point.y.toFixed(2)}`)
    .join(' ');

const buildAreaPath = (points: Array<{ x: number; y: number }>) => {
  if (points.length === 0) return '';
  return `${buildLinePath(points)} L100,50 L0,50 Z`;
};

const getStorageTrendLabel = (history: TenantMemoryHistoryPoint[]): string => {
  if (history.length < 2) return '0.0%';

  const current = history[history.length - 1]?.percentage ?? 0;
  const previous = history[Math.max(0, history.length - 8)]?.percentage ?? 0;
  const delta = current - previous;
  const prefix = delta > 0 ? '+' : '';
  return `${prefix}${delta.toFixed(1)}%`;
};

export const TenantOverview: React.FC = () => {
  const { t } = useTranslation();
  const { currentTenant, tenants, listTenants, setCurrentTenant } = useTenantStore();
  const [stats, setStats] = useState<TenantOverviewStats | null>(null);
  const [isLoadingStats, setIsLoadingStats] = useState(false);

  useEffect(() => {
    const init = async () => {
      if (tenants.length === 0) {
        await listTenants();
      }
    };
    void init();
  }, [listTenants, tenants.length]);

  useEffect(() => {
    if (!currentTenant && tenants.length > 0) {
      setCurrentTenant(tenants[0] ?? null);
    }
  }, [currentTenant, tenants, setCurrentTenant]);

  useEffect(() => {
    let isCurrent = true;

    const fetchStats = async () => {
      if (currentTenant) {
        setIsLoadingStats(true);
        try {
          const data = await tenantAPI.getStats(currentTenant.id);
          if (isCurrent) {
            setStats(data as TenantOverviewStats);
          }
        } catch (error) {
          console.error('Failed to fetch tenant stats:', error);
        } finally {
          if (isCurrent) {
            setIsLoadingStats(false);
          }
        }
      }
    };

    void fetchStats();

    return () => {
      isCurrent = false;
    };
  }, [currentTenant]);

  if (!currentTenant) {
    return <div className="p-8 text-center text-slate-500">{t('tenant.overview.loading')}</div>;
  }

  if (isLoadingStats || !stats) {
    return <div className="p-8 text-center text-slate-500">{t('common.loading')}</div>;
  }

  const storagePercentage = clampPercent(stats.storage.percentage);
  const memoryHistory =
    stats.memory_history && stats.memory_history.length > 0
      ? stats.memory_history
      : [
          {
            date: new Date().toISOString().slice(0, 10),
            used: stats.storage.used,
            daily_added: 0,
            memory_count: 0,
            percentage: stats.storage.percentage,
          },
        ];
  const latestMemoryUsage = memoryHistory[memoryHistory.length - 1]?.used ?? stats.storage.used;
  const chartPoints = buildMemoryChartPoints(memoryHistory);
  const chartLinePath = buildLinePath(chartPoints);
  const chartAreaPath = buildAreaPath(chartPoints);
  const regionLabel = hasValue(stats.tenant_info.region)
    ? stats.tenant_info.region
    : t('common.status.unavailable');
  const nextBillingLabel = hasValue(stats.tenant_info.next_billing_date)
    ? stats.tenant_info.next_billing_date
    : t('common.status.unavailable');

  return (
    <div className="max-w-full mx-auto flex flex-col gap-8">
      {/* Page Heading */}
      <div className="flex flex-col gap-1">
        <h2 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">
          {t('tenant.overview.title')}
        </h2>
        <p className="text-slate-500 dark:text-slate-400">{t('tenant.overview.subtitle')}</p>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="flex min-h-44 flex-col justify-between rounded-lg border border-slate-200 bg-surface-light p-5 shadow-sm transition-colors duration-150 hover:border-slate-300 dark:border-slate-800 dark:bg-surface-dark dark:hover:border-slate-700">
          <div className="flex items-start justify-between gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
              <Database size={16} />
            </div>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {getStorageTrendLabel(memoryHistory)}
            </span>
          </div>
          <div>
            <p className="mb-1 text-sm font-medium text-slate-500 dark:text-slate-400">
              {t('tenant.overview.totalStorage')}
            </p>
            <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
              <h3 className="text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">
                {formatStorage(stats.storage.used)}
              </h3>
              <span className="text-sm text-slate-500 dark:text-slate-400">
                / {formatStorage(stats.storage.total)}
              </span>
            </div>
          </div>
          <div className="h-1.5 w-full rounded-full bg-slate-100 dark:bg-slate-800">
            <div
              className="h-1.5 rounded-full bg-primary"
              style={{ width: `${storagePercentage.toString()}%` }}
            ></div>
          </div>
        </div>

        <div className="flex min-h-44 flex-col justify-between rounded-lg border border-slate-200 bg-surface-light p-5 shadow-sm transition-colors duration-150 hover:border-slate-300 dark:border-slate-800 dark:bg-surface-dark dark:hover:border-slate-700">
          <div className="flex items-start justify-between gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
              <FolderOpen size={16} />
            </div>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {stats.projects.active} {t('common.status.active')}
            </span>
          </div>
          <div>
            <p className="mb-1 text-sm font-medium text-slate-500 dark:text-slate-400">
              {t('tenant.overview.activeProjects')}
            </p>
            <h3 className="text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">
              {stats.projects.active}
            </h3>
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.overview.newProjectThisWeek', { count: stats.projects.new_this_week })}
          </p>
        </div>

        <div className="flex min-h-44 flex-col justify-between rounded-lg border border-slate-200 bg-surface-light p-5 shadow-sm transition-colors duration-150 hover:border-slate-300 dark:border-slate-800 dark:bg-surface-dark dark:hover:border-slate-700">
          <div className="flex items-start justify-between gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-700 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
              <Users size={16} />
            </div>
            <span className="rounded-full border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-medium text-slate-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
              {t('common.stats.total')} {stats.members.total}
            </span>
          </div>
          <div>
            <p className="mb-1 text-sm font-medium text-slate-500 dark:text-slate-400">
              {t('tenant.overview.teamMembers')}
            </p>
            <h3 className="text-2xl font-semibold tracking-tight text-slate-950 dark:text-slate-50">
              {stats.members.total}
            </h3>
          </div>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {t('tenant.overview.newMembers', { count: stats.members.new_added })}
          </p>
        </div>
      </div>

      {/* Middle Row: Chart & Tenant Info */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-surface-light dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 p-6 flex flex-col">
          <div className="flex flex-wrap justify-between items-center gap-3 mb-6">
            <div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-white">
                {t('tenant.overview.memoryUsageHistory')}
              </h3>
              <p className="text-sm text-slate-500">{t('tenant.overview.last30Days')}</p>
            </div>
            <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-right dark:border-slate-700 dark:bg-slate-800">
              <p className="text-xs font-medium uppercase text-slate-500">
                {t('tenant.overview.latestUsage')}
              </p>
              <p className="text-sm font-semibold text-slate-900 dark:text-white">
                {formatStorage(latestMemoryUsage)}
              </p>
            </div>
          </div>
          <div className="flex-1 w-full min-h-60 relative">
            <div className="absolute inset-0 flex flex-col justify-between text-xs text-slate-400">
              <div className="flex w-full items-center">
                <span className="w-8 text-right pr-2">100%</span>
                <div className="h-px bg-slate-100 dark:bg-slate-800 flex-1"></div>
              </div>
              <div className="flex w-full items-center">
                <span className="w-8 text-right pr-2">75%</span>
                <div className="h-px bg-slate-100 dark:bg-slate-800 flex-1"></div>
              </div>
              <div className="flex w-full items-center">
                <span className="w-8 text-right pr-2">50%</span>
                <div className="h-px bg-slate-100 dark:bg-slate-800 flex-1"></div>
              </div>
              <div className="flex w-full items-center">
                <span className="w-8 text-right pr-2">25%</span>
                <div className="h-px bg-slate-100 dark:bg-slate-800 flex-1"></div>
              </div>
              <div className="flex w-full items-center">
                <span className="w-8 text-right pr-2">0%</span>
                <div className="h-px bg-slate-100 dark:bg-slate-800 flex-1"></div>
              </div>
            </div>
            {chartPoints.length > 0 ? (
              <svg
                aria-label={t('tenant.overview.memoryChartAria')}
                className="absolute inset-0 h-full w-full pl-8 pb-4 pt-2"
                preserveAspectRatio="none"
                role="img"
                viewBox="0 0 100 50"
              >
                <defs>
                  <linearGradient id="tenantMemoryChartGradient" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor="#1e3fae" stopOpacity="0.22"></stop>
                    <stop offset="100%" stopColor="#1e3fae" stopOpacity="0"></stop>
                  </linearGradient>
                </defs>
                <path d={chartAreaPath} fill="url(#tenantMemoryChartGradient)"></path>
                <path
                  d={chartLinePath}
                  fill="none"
                  stroke="#1e3fae"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth="0.8"
                  vectorEffect="non-scaling-stroke"
                ></path>
                {chartPoints.map((point, index) => {
                  if (index !== 0 && index !== chartPoints.length - 1) return null;
                  return (
                    <circle
                      key={`${point.x.toFixed(2)}-${point.y.toFixed(2)}`}
                      cx={point.x}
                      cy={point.y}
                      fill="#1e3fae"
                      r="1.2"
                      vectorEffect="non-scaling-stroke"
                    />
                  );
                })}
              </svg>
            ) : (
              <div className="absolute inset-0 flex items-center justify-center pl-8 pb-4 pt-2 text-sm text-slate-500">
                {t('tenant.overview.noMemoryHistory')}
              </div>
            )}
          </div>
        </div>

        {/* Tenant Details */}
        <div className="bg-surface-light dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 p-6">
          <h3 className="text-lg font-bold text-slate-900 dark:text-white mb-6">
            {t('tenant.overview.tenantInfo')}
          </h3>
          <div className="flex flex-col gap-6">
            <div className="flex items-center gap-4">
              <div className="bg-blue-50 dark:bg-blue-900/30 p-3 rounded-lg text-primary">
                <BadgeCheck size={16} />
              </div>
              <div>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t('tenant.overview.orgId')}
                </p>
                <p className="text-slate-900 dark:text-white font-mono font-medium">
                  {stats.tenant_info.organization_id}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="bg-purple-50 dark:bg-purple-900/30 p-3 rounded-lg text-purple-600">
                <Diamond size={16} />
              </div>
              <div>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t('tenant.overview.currentPlan')}
                </p>
                <p className="text-slate-900 dark:text-white font-medium capitalize">
                  {stats.tenant_info.plan}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="bg-emerald-50 dark:bg-emerald-900/30 p-3 rounded-lg text-emerald-600">
                <Globe size={16} />
              </div>
              <div>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t('tenant.overview.region')}
                </p>
                <p className="text-slate-900 dark:text-white font-medium">{regionLabel}</p>
              </div>
            </div>
            <div className="h-px w-full bg-slate-100 dark:bg-slate-800 my-2"></div>
            <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-100 dark:border-slate-800">
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm text-slate-500">
                  {t('tenant.overview.nextBillingDate')}
                </span>
                <span className="text-sm font-semibold text-slate-900 dark:text-white">
                  {nextBillingLabel}
                </span>
              </div>
              <Link
                to="/tenant/billing"
                className="block w-full rounded-md border border-slate-200 bg-white px-4 py-2 text-center text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-700 dark:text-slate-200 dark:hover:bg-slate-600"
              >
                {t('tenant.overview.viewInvoice')}
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom Row: Recent Active Projects */}
      <div className="bg-surface-light dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 flex flex-col overflow-hidden">
        <div className="p-6 border-b border-slate-100 dark:border-slate-800 flex flex-wrap gap-4 items-center justify-between">
          <h3 className="text-lg font-bold text-slate-900 dark:text-white">
            {t('tenant.overview.mostActiveProjects')}
          </h3>
          <Link
            to={`/tenant/${currentTenant.id}/projects`}
            className="text-primary text-sm font-medium hover:underline"
          >
            {t('common.actions.viewAll')}
          </Link>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-100 dark:border-slate-800">
                <th className="py-4 px-6 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  {t('tenant.overview.projectName')}
                </th>
                <th className="py-4 px-6 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  {t('common.stats.owner')}
                </th>
                <th className="py-4 px-6 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  {t('tenant.overview.memoryConsumed')}
                </th>
                <th className="py-4 px-6 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">
                  {t('common.forms.status')}
                </th>
                <th className="py-4 px-6 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">
                  {t('tenant.overview.actions')}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {stats.projects.list.map((project) => (
                <tr
                  key={project.id}
                  className="hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors"
                >
                  <td className="py-4 px-6">
                    <div className="flex items-center gap-3">
                      <div className="bg-primary/10 text-primary p-2 rounded-lg">
                        <Plug size={20} />
                      </div>
                      <div>
                        <p className="font-medium text-slate-900 dark:text-white">{project.name}</p>
                        <p className="text-xs text-slate-500">ID: #{project.id.slice(0, 8)}</p>
                      </div>
                    </div>
                  </td>
                  <td className="py-4 px-6">
                    <div className="flex items-center gap-2">
                      <div className="size-6 rounded-full bg-cover bg-center bg-slate-200"></div>
                      <span className="text-sm text-slate-700 dark:text-slate-300">
                        {project.owner}
                      </span>
                    </div>
                  </td>
                  <td className="py-4 px-6">
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                      {project.memory_consumed}
                    </span>
                  </td>
                  <td className="py-4 px-6 text-right">
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        isActiveProject(project.status)
                          ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400'
                          : hasValue(project.status)
                            ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400'
                            : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
                      }`}
                    >
                      <span
                        className={`size-1.5 rounded-full ${
                          isActiveProject(project.status)
                            ? 'bg-emerald-500'
                            : hasValue(project.status)
                              ? 'bg-amber-500'
                              : 'bg-slate-400'
                        }`}
                      ></span>
                      {hasValue(project.status) ? project.status : t('common.status.unavailable')}
                    </span>
                  </td>
                  <td className="py-4 px-6 text-right">
                    <Link
                      to={`/tenant/${currentTenant.id}/project/${project.id}`}
                      aria-label={t('tenant.overview.openProject', {
                        name: project.name,
                      })}
                      title={t('tenant.overview.openProject', {
                        name: project.name,
                      })}
                      className="inline-flex justify-end text-slate-400 transition-colors hover:text-primary"
                    >
                      <MoreVertical size={20} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

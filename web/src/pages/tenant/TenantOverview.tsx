import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { tenantAPI } from '../../services/api';
import { useTenantStore } from '../../stores/tenant';

export const TenantOverview: React.FC = () => {
  const { t } = useTranslation();
  const { currentTenant, tenants, listTenants, setCurrentTenant } = useTenantStore();
  const [stats, setStats] = useState<any>(null);
  const [isLoadingStats, setIsLoadingStats] = useState(false);

  useEffect(() => {
    const init = async () => {
      if (tenants.length === 0) {
        await listTenants();
      }
    };
    init();
  }, [listTenants, tenants.length]);

  useEffect(() => {
    if (!currentTenant && tenants.length > 0) {
      setCurrentTenant(tenants[0]);
    }
  }, [currentTenant, tenants, setCurrentTenant]);

  useEffect(() => {
    const fetchStats = async () => {
      if (currentTenant) {
        setIsLoadingStats(true);
        try {
          const data = await tenantAPI.getStats(currentTenant.id);
          setStats(data);
        } catch (error) {
          console.error('Failed to fetch tenant stats:', error);
        } finally {
          setIsLoadingStats(false);
        }
      }
    };
    fetchStats();
  }, [currentTenant]);

  if (!currentTenant) {
    return <div className="p-8 text-center text-slate-500">{t('tenant.overview.loading')}</div>;
  }

  if (isLoadingStats || !stats) {
    return <div className="p-8 text-center text-slate-500">{t('common.loading')}</div>;
  }

  const formatStorage = (bytes: number) => {
    const tb = bytes / (1024 * 1024 * 1024 * 1024);
    if (tb >= 1) return `${tb.toFixed(1)} TB`;
    const gb = bytes / (1024 * 1024 * 1024);
    return `${gb.toFixed(1)} GB`;
  };

  return (
    <div className="max-w-full mx-auto flex flex-col gap-8">
      {/* Page Heading */}
      <div className="flex flex-col gap-1">
        <h2 className="text-3xl font-bold text-slate-900 dark:text-white tracking-tight">
          {t('tenant.overview.title')}
        </h2>
        <p className="text-slate-500 dark:text-slate-400">{t('tenant.overview.subtitle')}</p>
      </div>

      {/* Stats Cards (Gradient) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Card 1 */}
        <div className="relative overflow-hidden rounded-xl p-6 shadow-lg bg-gradient-to-br from-[#1e3fae] to-[#3b82f6] text-white group hover:shadow-xl transition-shadow duration-300">
          <div className="absolute right-0 top-0 h-full w-1/2 bg-white/5 skew-x-12 -mr-10"></div>
          <div className="relative z-10 flex flex-col justify-between h-full gap-4">
            <div className="flex items-start justify-between">
              <div className="p-2 bg-white/20 rounded-lg backdrop-blur-sm">
                <span className="material-symbols-outlined text-white">database</span>
              </div>
              <span className="text-xs font-medium bg-white/20 px-2 py-1 rounded text-white backdrop-blur-sm">
                +12%
              </span>
            </div>
            <div>
              <p className="text-blue-100 text-sm font-medium mb-1">
                {t('tenant.overview.totalStorage')}
              </p>
              <div className="flex items-baseline gap-2">
                <h3 className="text-3xl font-bold tracking-tight">
                  {formatStorage(stats.storage.used)}
                </h3>
                <span className="text-blue-200 text-sm">
                  / {formatStorage(stats.storage.total)}
                </span>
              </div>
            </div>
            <div className="w-full bg-black/20 rounded-full h-1.5 mt-1">
              <div
                className="bg-white h-1.5 rounded-full"
                style={{ width: `${stats.storage.percentage}%` }}
              ></div>
            </div>
          </div>
        </div>

        {/* Card 2 */}
        <div className="relative overflow-hidden rounded-xl p-6 shadow-lg bg-gradient-to-br from-indigo-600 to-violet-500 text-white group hover:shadow-xl transition-shadow duration-300">
          <div className="absolute right-0 top-0 h-full w-1/2 bg-white/5 skew-x-12 -mr-10"></div>
          <div className="relative z-10 flex flex-col justify-between h-full gap-4">
            <div className="flex items-start justify-between">
              <div className="p-2 bg-white/20 rounded-lg backdrop-blur-sm">
                <span className="material-symbols-outlined text-white">folder_open</span>
              </div>
              <span className="text-xs font-medium bg-white/20 px-2 py-1 rounded text-white backdrop-blur-sm">
                {stats.projects.active} {t('common.status.active')}
              </span>
            </div>
            <div>
              <p className="text-indigo-100 text-sm font-medium mb-1">
                {t('tenant.overview.activeProjects')}
              </p>
              <h3 className="text-3xl font-bold tracking-tight">{stats.projects.active}</h3>
            </div>
            <p className="text-indigo-100 text-sm">
              {t('tenant.overview.newProjectThisWeek', { count: stats.projects.new_this_week })}
            </p>
          </div>
        </div>

        {/* Card 3 */}
        <div className="relative overflow-hidden rounded-xl p-6 shadow-lg bg-gradient-to-br from-slate-700 to-slate-600 text-white group hover:shadow-xl transition-shadow duration-300">
          <div className="absolute right-0 top-0 h-full w-1/2 bg-white/5 skew-x-12 -mr-10"></div>
          <div className="relative z-10 flex flex-col justify-between h-full gap-4">
            <div className="flex items-start justify-between">
              <div className="p-2 bg-white/20 rounded-lg backdrop-blur-sm">
                <span className="material-symbols-outlined text-white">group</span>
              </div>
              <span className="text-xs font-medium bg-white/20 px-2 py-1 rounded text-white backdrop-blur-sm">
                {t('common.stats.total')} {stats.members.total}
              </span>
            </div>
            <div>
              <p className="text-slate-200 text-sm font-medium mb-1">
                {t('tenant.overview.teamMembers')}
              </p>
              <h3 className="text-3xl font-bold tracking-tight">{stats.members.total}</h3>
            </div>
            <div className="flex -space-x-2 overflow-hidden mt-1">
              <div className="h-6 w-6 rounded-full bg-slate-500 ring-2 ring-slate-600 flex items-center justify-center text-[10px] font-medium">
                +{stats.members.new_added}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Middle Row: Chart & Tenant Info */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Chart Area - Placeholder for now */}
        <div className="lg:col-span-2 bg-surface-light dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 p-6 flex flex-col">
          <div className="flex justify-between items-center mb-6">
            <div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-white">
                {t('tenant.overview.memoryUsageHistory')}
              </h3>
              <p className="text-sm text-slate-500">{t('tenant.overview.last30Days')}</p>
            </div>
            <select className="bg-slate-50 dark:bg-slate-800 border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300 text-sm rounded-lg py-1.5 px-3 focus:ring-primary focus:border-primary outline-none">
              <option>{t('tenant.overview.last30Days')}</option>
              <option>Last 7 Days</option>
              <option>Last 24 Hours</option>
            </select>
          </div>
          {/* Simulated Chart using SVG */}
          <div className="flex-1 w-full min-h-[240px] relative">
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
            <svg
              className="absolute inset-0 h-full w-full pl-8 pb-4 pt-2"
              preserveAspectRatio="none"
              viewBox="0 0 100 50"
            >
              <defs>
                <linearGradient id="chartGradient" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="#1e3fae" stopOpacity="0.2"></stop>
                  <stop offset="100%" stopColor="#1e3fae" stopOpacity="0"></stop>
                </linearGradient>
              </defs>
              <path
                d="M0,45 C10,40 15,35 20,38 C25,41 30,20 40,22 C50,24 55,30 60,25 C65,20 75,15 80,18 C85,21 90,10 100,5 V50 H0 Z"
                fill="url(#chartGradient)"
              ></path>
              <path
                d="M0,45 C10,40 15,35 20,38 C25,41 30,20 40,22 C50,24 55,30 60,25 C65,20 75,15 80,18 C85,21 90,10 100,5"
                fill="none"
                stroke="#1e3fae"
                strokeWidth="0.5"
                vectorEffect="non-scaling-stroke"
              ></path>
            </svg>
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
                <span className="material-symbols-outlined">badge</span>
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
                <span className="material-symbols-outlined">diamond</span>
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
                <span className="material-symbols-outlined">public</span>
              </div>
              <div>
                <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t('tenant.overview.region')}
                </p>
                <p className="text-slate-900 dark:text-white font-medium">
                  {stats.tenant_info.region}
                </p>
              </div>
            </div>
            <div className="h-px w-full bg-slate-100 dark:bg-slate-800 my-2"></div>
            <div className="bg-slate-50 dark:bg-slate-800/50 rounded-lg p-4 border border-slate-100 dark:border-slate-800">
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm text-slate-500">
                  {t('tenant.overview.nextBillingDate')}
                </span>
                <span className="text-sm font-semibold text-slate-900 dark:text-white">
                  {stats.tenant_info.next_billing_date}
                </span>
              </div>
              <button className="w-full py-2 px-4 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-md text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-600 transition-colors">
                {t('tenant.overview.viewInvoice')}
              </button>
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
          <Link to="/tenant/projects" className="text-primary text-sm font-medium hover:underline">
            {t('common.actions.viewAll')}
          </Link>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 dark:bg-slate-800/50 border-b border-slate-100 dark:border-slate-800">
                <th className="py-4 px-6 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Project Name
                </th>
                <th className="py-4 px-6 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  {t('common.stats.owner')}
                </th>
                <th className="py-4 px-6 text-xs font-semibold text-slate-500 uppercase tracking-wider">
                  Memory Consumed
                </th>
                <th className="py-4 px-6 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">
                  Status
                </th>
                <th className="py-4 px-6 text-xs font-semibold text-slate-500 uppercase tracking-wider text-right">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {stats.projects.list.map((project: any) => (
                <tr
                  key={project.id}
                  className="hover:bg-slate-50 dark:hover:bg-slate-800/30 transition-colors"
                >
                  <td className="py-4 px-6">
                    <div className="flex items-center gap-3">
                      <div className="bg-primary/10 text-primary p-2 rounded-lg">
                        <span className="material-symbols-outlined text-[20px]">api</span>
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
                    <div className="flex items-center gap-2">
                      <div className="w-24 bg-slate-100 dark:bg-slate-700 rounded-full h-1.5 overflow-hidden">
                        <div
                          className="bg-primary h-1.5 rounded-full"
                          style={{ width: '75%' }}
                        ></div>
                      </div>
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
                        {project.memory_consumed}
                      </span>
                    </div>
                  </td>
                  <td className="py-4 px-6 text-right">
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium ${
                        project.status === 'Active'
                          ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400'
                          : 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400'
                      }`}
                    >
                      <span
                        className={`size-1.5 rounded-full ${
                          project.status === 'Active' ? 'bg-emerald-500' : 'bg-amber-500'
                        }`}
                      ></span>
                      {project.status}
                    </span>
                  </td>
                  <td className="py-4 px-6 text-right">
                    <button className="text-slate-400 hover:text-primary transition-colors">
                      <span className="material-symbols-outlined text-[20px]">more_vert</span>
                    </button>
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

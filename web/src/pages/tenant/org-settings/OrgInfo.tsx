/**
 * Organization Info Page
 *
 * Read-only organization overview (name, description, statistics).
 * Editing is consolidated into the Tenant Settings page, which has
 * dirty tracking, unsaved-changes warning, and the danger zone.
 */

import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';

import { ArrowRight, BarChart3, Building2, Cloud, Database, FolderOpen, Users } from 'lucide-react';

import { useTenantStore } from '@/stores/tenant';

import { tenantAPI } from '@/services/api';

import { formatStorage } from '@/hooks/useDateFormatter';

import { formatDateOnly } from '@/utils/date';
import { logger } from '@/utils/logger';

import type { Tenant } from '@/types/memory';

interface OrgStatsResponse {
  storage?: {
    used?: number | undefined;
    percentage?: number | undefined;
  };
  projects?: {
    active?: number | undefined;
  };
  members?: {
    total?: number | undefined;
  };
  clusters?: {
    total?: number | undefined;
  };
}

const OrgInfoSummary: React.FC<{ tenant: Tenant }> = ({ tenant }) => {
  const { t } = useTranslation();

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4 min-w-0">
          <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-lg bg-slate-100 dark:bg-slate-800">
            {tenant.name ? (
              <span className="text-2xl font-bold text-primary-600 dark:text-primary-400">
                {tenant.name.charAt(0).toUpperCase()}
              </span>
            ) : (
              <Building2 size={24} className="text-slate-400" />
            )}
          </div>
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 break-words">
              {tenant.name}
            </h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 break-words">
              {tenant.description?.trim()
                ? tenant.description
                : t('tenant.orgSettings.info.noDescription', {
                    defaultValue: 'No description provided.',
                  })}
            </p>
          </div>
        </div>
        <Link
          to="../../settings"
          className="inline-flex shrink-0 items-center gap-2 px-4 py-2 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors text-sm font-medium"
        >
          {t('tenant.orgSettings.info.editInSettings', {
            defaultValue: 'Edit in Tenant Settings',
          })}
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </div>
    </div>
  );
};

const OrgStatistics: React.FC<{ tenant: Tenant }> = ({ tenant }) => {
  const { t } = useTranslation();
  const [stats, setStats] = useState<OrgStatsResponse | null>(null);
  const [isLoadingStats, setIsLoadingStats] = useState(false);

  useEffect(() => {
    let isCurrent = true;

    const fetchStats = async () => {
      setIsLoadingStats(true);
      try {
        const response = (await tenantAPI.getStats(tenant.id)) as OrgStatsResponse;
        if (isCurrent) {
          setStats(response);
        }
      } catch (error) {
        logger.error('Failed to fetch organization statistics', error);
        if (isCurrent) {
          setStats(null);
        }
      } finally {
        if (isCurrent) {
          setIsLoadingStats(false);
        }
      }
    };

    void fetchStats();

    return () => {
      isCurrent = false;
    };
  }, [tenant.id]);

  const unavailable = t('tenant.orgSettings.info.stats.unavailable');
  const loading = t('common.loading');
  const formatStat = (value: number | undefined) =>
    isLoadingStats ? loading : value === undefined ? unavailable : String(value);
  const storageValue = isLoadingStats
    ? loading
    : stats?.storage?.used !== undefined
      ? formatStorage(stats.storage.used)
      : stats?.storage?.percentage !== undefined
        ? `${String(Math.round(stats.storage.percentage))}%`
        : unavailable;

  const statCards = [
    {
      label: t('tenant.orgSettings.info.stats.projects'),
      value: formatStat(stats?.projects?.active),
      icon: FolderOpen,
      color: 'text-blue-600 dark:text-blue-400',
      bg: 'bg-blue-50 dark:bg-blue-950/40',
    },
    {
      label: t('tenant.orgSettings.info.stats.members'),
      value: formatStat(stats?.members?.total),
      icon: Users,
      color: 'text-green-600 dark:text-green-400',
      bg: 'bg-green-50 dark:bg-green-950/40',
    },
    {
      label: t('tenant.orgSettings.info.stats.clusters'),
      value: formatStat(stats?.clusters?.total),
      icon: Cloud,
      color: 'text-purple-600 dark:text-purple-400',
      bg: 'bg-purple-50 dark:bg-purple-950/40',
    },
    {
      label: t('tenant.orgSettings.info.stats.storage'),
      value: storageValue,
      icon: Database,
      color: 'text-orange-600 dark:text-orange-400',
      bg: 'bg-orange-50 dark:bg-orange-950/40',
    },
  ];

  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 dark:border-slate-700 dark:bg-slate-900 p-6 mt-6">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-6 flex items-center gap-2">
        <BarChart3 size={16} className="text-primary" />
        {t('tenant.orgSettings.info.statistics')}
      </h2>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {statCards.map((stat) => {
          const Icon = stat.icon;
          return (
            <div
              key={stat.label}
              className="rounded-lg border border-slate-200 bg-slate-100 p-4 dark:border-slate-700 dark:bg-slate-800"
            >
              <div className="flex items-center gap-3">
                <div className={`shrink-0 p-2 rounded-lg ${stat.bg}`}>
                  <Icon size={20} className={stat.color} />
                </div>
                <div className="min-w-0">
                  <p className="break-words text-2xl font-bold leading-tight text-slate-900 dark:text-slate-100">
                    {stat.value}
                  </p>
                  <p className="text-xs text-slate-500 dark:text-slate-400">{stat.label}</p>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-6 pt-6 border-t border-slate-200 dark:border-slate-700">
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
          <div>
            <p className="text-slate-500 dark:text-slate-400">
              {t('tenant.orgSettings.info.created')}
            </p>
            <p className="font-medium text-slate-900 dark:text-slate-100">
              {formatDateOnly(tenant.created_at)}
            </p>
          </div>
          <div>
            <p className="text-slate-500 dark:text-slate-400">
              {t('tenant.orgSettings.info.plan')}
            </p>
            <p className="font-medium text-slate-900 dark:text-slate-100 capitalize">
              {tenant.plan}
            </p>
          </div>
          <div>
            <p className="text-slate-500 dark:text-slate-400">
              {t('tenant.orgSettings.info.tenantId')}
            </p>
            <p className="break-all font-mono text-xs text-slate-700 dark:text-slate-300">
              {tenant.id}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export const OrgInfo: React.FC = () => {
  const currentTenant = useTenantStore((state) => state.currentTenant);

  if (!currentTenant) return null;

  return (
    <div className="space-y-6">
      <OrgInfoSummary tenant={currentTenant} />
      <OrgStatistics tenant={currentTenant} />
    </div>
  );
};

export default OrgInfo;

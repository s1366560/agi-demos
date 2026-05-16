/**
 * Organization Info Page
 *
 * Displays and allows editing of organization name, logo, description.
 * Shows organization statistics.
 */

import React, { useCallback, useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';

import {
  AlertCircle,
  BarChart3,
  Building2,
  CheckCircle,
  Cloud,
  Database,
  FolderOpen,
  Loader2,
  Settings,
  Users,
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useTenantStore } from '@/stores/tenant';

import { tenantAPI } from '@/services/api';

import { formatDateOnly } from '@/utils/date';

import type { Tenant } from '@/types/memory';

interface OrgInfoFormProps {
  tenant: Tenant;
}

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

function formatStorage(bytes: number): string {
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1)} KB`;
  const mb = bytes / (1024 * 1024);
  if (mb < 1024) return `${mb.toFixed(1)} MB`;
  const gb = bytes / (1024 * 1024 * 1024);
  return `${gb.toFixed(1)} GB`;
}

const OrgInfoForm: React.FC<OrgInfoFormProps> = ({ tenant }) => {
  const { t } = useTranslation();
  const { updateTenant, isLoading } = useTenantStore(
    useShallow((state) => ({
      updateTenant: state.updateTenant,
      isLoading: state.isLoading,
    }))
  );
  const [name, setName] = useState(tenant.name);
  const [description, setDescription] = useState(tenant.description || '');
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const handleSave = useCallback(async () => {
    setMessage(null);
    try {
      await updateTenant(tenant.id, { name, description });
      setMessage({ type: 'success', text: t('tenant.settings.success') });
    } catch (error) {
      console.error('Failed to update organization:', error);
      setMessage({ type: 'error', text: t('tenant.settings.error') });
    }
  }, [tenant.id, name, description, updateTenant, t]);

  return (
    <div className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 p-6">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-6 flex items-center gap-2">
        <Settings size={16} className="text-primary" />
        {t('tenant.orgSettings.info.general')}
      </h2>

      <div className="flex flex-col gap-6 max-w-2xl">
        <div>
          <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
            {t('tenant.orgSettings.info.logo')}
          </label>
          <div className="flex items-center gap-4">
            <div className="w-20 h-20 rounded-xl bg-slate-100 dark:bg-slate-700 flex items-center justify-center">
              {tenant.name ? (
                <span className="text-2xl font-bold text-primary-600 dark:text-primary-400">
                  {tenant.name.charAt(0).toUpperCase()}
                </span>
              ) : (
                <Building2 size={16} className="text-slate-400 text-3xl" />
              )}
            </div>
            <div>
              <button
                className="px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-lg text-sm font-medium text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800 cursor-not-allowed"
                disabled
                title={t('tenant.orgSettings.info.logoUnavailable')}
                type="button"
              >
                {t('tenant.orgSettings.info.uploadLogo')}
              </button>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                {t('tenant.orgSettings.info.logoUnavailable')}
              </p>
            </div>
          </div>
        </div>

        <div>
          <label
            className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
            htmlFor="org-name"
          >
            {t('tenant.orgSettings.info.name')}
          </label>
          <input
            className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors outline-none"
            id="org-name"
            type="text"
            value={name}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
        </div>

        <div>
          <label
            className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
            htmlFor="org-description"
          >
            {t('tenant.orgSettings.info.description')}
          </label>
          <textarea
            className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-colors outline-none resize-none"
            id="org-description"
            rows={3}
            value={description}
            onChange={(event) => {
              setDescription(event.target.value);
            }}
          />
        </div>

        {message ? (
          <div
            className={`p-4 rounded-lg flex items-center gap-3 ${
              message.type === 'success'
                ? 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-300'
                : 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-300'
            }`}
            role="status"
          >
            {message.type === 'success' ? <CheckCircle size={20} /> : <AlertCircle size={20} />}
            {message.text}
          </div>
        ) : null}

        <div>
          <button
            className="bg-primary hover:bg-primary-dark text-white px-6 py-2.5 rounded-lg font-medium transition-colors disabled:opacity-70 disabled:cursor-not-allowed flex items-center gap-2"
            disabled={isLoading}
            type="button"
            onClick={() => {
              void handleSave();
            }}
          >
            {isLoading ? (
              <Loader2 size={20} className="animate-spin motion-reduce:animate-none" />
            ) : null}
            {t('common.save')}
          </button>
        </div>
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
        console.error('Failed to fetch organization statistics:', error);
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
      bg: 'bg-blue-100 dark:bg-blue-900/30',
    },
    {
      label: t('tenant.orgSettings.info.stats.members'),
      value: formatStat(stats?.members?.total),
      icon: Users,
      color: 'text-green-600 dark:text-green-400',
      bg: 'bg-green-100 dark:bg-green-900/30',
    },
    {
      label: t('tenant.orgSettings.info.stats.clusters'),
      value: formatStat(stats?.clusters?.total),
      icon: Cloud,
      color: 'text-purple-600 dark:text-purple-400',
      bg: 'bg-purple-100 dark:bg-purple-900/30',
    },
    {
      label: t('tenant.orgSettings.info.stats.storage'),
      value: storageValue,
      icon: Database,
      color: 'text-orange-600 dark:text-orange-400',
      bg: 'bg-orange-100 dark:bg-orange-900/30',
    },
  ];

  return (
    <div className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 p-6 mt-6">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-6 flex items-center gap-2">
        <BarChart3 size={16} className="text-primary" />
        {t('tenant.orgSettings.info.statistics')}
      </h2>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        {statCards.map((stat) => {
          const Icon = stat.icon;
          return (
            <div
              key={stat.label}
              className="p-4 bg-slate-50 dark:bg-slate-700/50 rounded-xl border border-slate-100 dark:border-slate-600"
            >
              <div className="flex items-center gap-3">
                <div className={`shrink-0 p-2 rounded-lg ${stat.bg}`}>
                  <Icon size={20} className={stat.color} />
                </div>
                <div className="min-w-0">
                  <p className="break-words text-2xl font-bold leading-tight text-slate-900 dark:text-white">
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
            <p className="font-medium text-slate-900 dark:text-white">
              {formatDateOnly(tenant.created_at)}
            </p>
          </div>
          <div>
            <p className="text-slate-500 dark:text-slate-400">
              {t('tenant.orgSettings.info.plan')}
            </p>
            <p className="font-medium text-slate-900 dark:text-white capitalize">{tenant.plan}</p>
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
      <OrgInfoForm tenant={currentTenant} />
      <OrgStatistics tenant={currentTenant} />
    </div>
  );
};

export default OrgInfo;

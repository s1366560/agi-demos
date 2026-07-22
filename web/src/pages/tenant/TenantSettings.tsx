import React, { useEffect, useState } from 'react';

import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';

import {
  AlertCircle,
  AlertTriangle,
  ArrowRight,
  CheckCircle,
  CreditCard,
  Loader2,
  Settings,
} from 'lucide-react';
import { useShallow } from 'zustand/react/shallow';

import { useTenantStore } from '@/stores/tenant';

import { tenantAPI } from '@/services/api';

import { useUnsavedChangesWarning } from '@/hooks/useUnsavedChangesWarning';

import { confirmAction } from '@/utils/confirmAction';
import { formatDateOnly } from '@/utils/date';
import { logger } from '@/utils/logger';

import type { Tenant } from '@/types/memory';

interface TenantSettingsStats {
  storage?: {
    percentage?: number | undefined;
  };
  projects?: {
    active?: number | undefined;
  };
}

const clampPercent = (value: number): number => Math.max(0, Math.min(100, value));

const TenantSettingsForm: React.FC<{ tenant: Tenant }> = ({ tenant }) => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { updateTenant, deleteTenant, isLoading } = useTenantStore(
    useShallow((state) => ({
      updateTenant: state.updateTenant,
      deleteTenant: state.deleteTenant,
      isLoading: state.isLoading,
    }))
  );
  const [name, setName] = useState(tenant.name);
  const [description, setDescription] = useState(tenant.description || '');
  const [stats, setStats] = useState<TenantSettingsStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  useEffect(() => {
    let isCurrent = true;

    const fetchStats = async () => {
      setStatsLoading(true);
      try {
        const response = (await tenantAPI.getStats(tenant.id)) as TenantSettingsStats;
        if (isCurrent) {
          setStats(response);
        }
      } catch (error) {
        logger.error('Failed to fetch tenant settings stats', error);
        if (isCurrent) {
          setStats(null);
        }
      } finally {
        if (isCurrent) {
          setStatsLoading(false);
        }
      }
    };

    void fetchStats();

    return () => {
      isCurrent = false;
    };
  }, [tenant.id]);

  const isDirty = name !== tenant.name || description !== (tenant.description || '');
  useUnsavedChangesWarning(isDirty);

  const handleSave = async () => {
    if (!name.trim()) return;
    setMessage(null);
    try {
      await updateTenant(tenant.id, {
        name: name.trim(),
        description,
      });
      setMessage({ type: 'success', text: t('tenant.settings.success') });
    } catch (error) {
      logger.error('Failed to update tenant', error);
      setMessage({ type: 'error', text: t('tenant.settings.error') });
    }
  };

  const handleDelete = async () => {
    const confirmed = await confirmAction({
      title: t('tenant.settings.danger.delete_confirm', { name: tenant.name }),
      danger: true,
    });
    if (!confirmed) return;

    setIsDeleting(true);
    setMessage(null);
    try {
      await deleteTenant(tenant.id);
      void navigate('/tenant', { replace: true });
    } catch (error) {
      logger.error('Failed to delete tenant', error);
      setMessage({ type: 'error', text: t('tenant.settings.danger.delete_error') });
    } finally {
      setIsDeleting(false);
    }
  };

  const activeProjects = stats?.projects?.active;
  const projectLimit = Math.max(tenant.max_projects, 0);
  const projectUsagePercent =
    activeProjects !== undefined && projectLimit > 0
      ? clampPercent((activeProjects / projectLimit) * 100)
      : 0;
  const storageUsage = stats?.storage?.percentage;
  const storageUsagePercent =
    storageUsage !== undefined ? clampPercent(Math.round(storageUsage)) : null;
  const usageUnavailable = t('tenant.settings.plan.usage_unavailable');

  return (
    <div className="max-w-full mx-auto flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          {t('tenant.settings.title')}
        </h1>
        <p className="text-slate-500 dark:text-slate-400 mt-1">{t('tenant.settings.subtitle')}</p>
      </div>

      <div className="bg-white dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 p-6 md:p-8">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-6 flex items-center gap-2">
          <Settings size={16} className="text-primary" />
          {t('tenant.settings.general.title')}
        </h2>

        <div className="flex flex-col gap-6 max-w-2xl">
          <div>
            <label
              htmlFor="tenant-settings-name"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
            >
              {t('tenant.settings.general.name')}
            </label>
            <input
              id="tenant-settings-name"
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-[color,background-color,border-color,box-shadow,opacity,transform] outline-none"
              type="text"
              name="name"
              autoComplete="organization"
              spellCheck={false}
              value={name}
              onChange={(event) => {
                setName(event.target.value);
              }}
            />
          </div>
          <div>
            <label
              htmlFor="tenant-settings-description"
              className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2"
            >
              {t('tenant.settings.general.description')}
            </label>
            <textarea
              id="tenant-settings-description"
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-[color,background-color,border-color,box-shadow,opacity,transform] outline-none resize-none"
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
              disabled={isLoading || !name.trim()}
              type="button"
              onClick={() => {
                void handleSave();
              }}
            >
              {isLoading ? (
                <Loader2 size={20} className="animate-spin motion-reduce:animate-none" />
              ) : null}
              {t('tenant.settings.save')}
            </button>
          </div>
        </div>
      </div>

      <div className="bg-white dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 p-6 md:p-8">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-6 flex items-center gap-2">
          <CreditCard size={16} className="text-primary" />
          {t('tenant.settings.plan.title')}
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
          <div className="p-6 bg-slate-50 dark:bg-slate-800/50 rounded-xl border border-slate-100 dark:border-slate-800">
            <div className="flex justify-between items-start mb-4">
              <div>
                <h3 className="text-sm font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  {t('tenant.settings.plan.current')}
                </h3>
                <p className="text-3xl font-bold text-slate-900 dark:text-white mt-2 capitalize">
                  {tenant.plan}
                </p>
              </div>
              <span className="bg-primary/10 text-primary px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wide">
                {t('common.status.active')}
              </span>
            </div>
            <p className="text-sm text-slate-500 mb-6">
              {t('tenant.settings.plan.active_since', {
                date: formatDateOnly(tenant.created_at),
              })}
            </p>
            <Link
              className="text-primary hover:text-primary-dark font-medium text-sm inline-flex items-center gap-1"
              to="/tenant/billing"
            >
              {t('tenant.settings.plan.change')}
              <ArrowRight size={16} />
            </Link>
          </div>

          <div className="flex flex-col gap-4">
            <h3 className="text-sm font-medium text-slate-900 dark:text-white">
              {t('tenant.settings.plan.limits')}
            </h3>
            <div className="space-y-4">
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-slate-600 dark:text-slate-300">
                    {t('tenant.settings.plan.projects')}
                  </span>
                  <span className="font-medium text-slate-900 dark:text-white">
                    {statsLoading
                      ? t('common.loading')
                      : activeProjects === undefined
                        ? usageUnavailable
                        : `${String(activeProjects)} / ${String(projectLimit)}`}
                  </span>
                </div>
                <div
                  className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden"
                  role="progressbar"
                  aria-valuenow={Math.round(projectUsagePercent)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={t('tenant.settings.plan.projects')}
                >
                  <div
                    className="h-full bg-blue-500"
                    style={{ width: `${String(projectUsagePercent)}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-slate-600 dark:text-slate-300">
                    {t('tenant.settings.plan.storage')}
                  </span>
                  <span className="font-medium text-slate-900 dark:text-white">
                    {statsLoading
                      ? t('common.loading')
                      : storageUsagePercent === null
                        ? usageUnavailable
                        : `${String(storageUsagePercent)}%`}
                  </span>
                </div>
                <div
                  className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden"
                  role="progressbar"
                  aria-valuenow={storageUsagePercent ?? 0}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label={t('tenant.settings.plan.storage')}
                >
                  <div
                    className="h-full bg-purple-500"
                    style={{ width: `${String(storageUsagePercent ?? 0)}%` }}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="bg-red-50 dark:bg-red-900/10 rounded-xl border border-red-200 dark:border-red-900/30 p-6 md:p-8">
        <h2 className="text-lg font-semibold text-red-700 dark:text-red-400 mb-2 flex items-center gap-2">
          <AlertTriangle size={16} />
          {t('tenant.settings.danger.title')}
        </h2>
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <h3 className="font-medium text-red-900 dark:text-red-300">
              {t('tenant.settings.danger.delete_title')}
            </h3>
            <p className="text-sm text-red-700 dark:text-red-400 mt-1 max-w-xl">
              {t('tenant.settings.danger.delete_desc')}
            </p>
          </div>
          <button
            className="bg-white border border-red-300 text-red-600 hover:bg-red-50 px-4 py-2 rounded-lg text-sm font-medium transition-colors shadow-sm whitespace-nowrap disabled:cursor-not-allowed disabled:opacity-60 dark:bg-transparent dark:border-red-800 dark:text-red-400 dark:hover:bg-red-900/20"
            disabled={isDeleting}
            type="button"
            onClick={() => {
              void handleDelete();
            }}
          >
            {isDeleting
              ? t('tenant.settings.danger.deleting')
              : t('tenant.settings.danger.delete_button')}
          </button>
        </div>
      </div>
    </div>
  );
};

export const TenantSettings: React.FC = () => {
  const { currentTenant } = useTenantStore(
    useShallow((state) => ({
      currentTenant: state.currentTenant,
    }))
  );

  if (!currentTenant) return null;

  return <TenantSettingsForm key={currentTenant.id} tenant={currentTenant} />;
};

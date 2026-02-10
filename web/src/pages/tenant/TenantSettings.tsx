import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';

import { useTenantStore } from '../../stores/tenant';
import { Tenant } from '../../types/memory';
import { formatDateOnly } from '@/utils/date';

const TenantSettingsForm: React.FC<{ tenant: Tenant }> = ({ tenant }) => {
  const { t } = useTranslation();
  const { updateTenant, isLoading } = useTenantStore();
  const [name, setName] = useState(tenant.name);
  const [description, setDescription] = useState(tenant.description || '');
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const handleSave = async () => {
    setMessage(null);
    try {
      await updateTenant(tenant.id, {
        name,
        description,
      });
      setMessage({ type: 'success', text: t('tenant.settings.success') });
    } catch (error) {
      console.error('Failed to update tenant:', error);
      setMessage({ type: 'error', text: t('tenant.settings.error') });
    }
  };

  return (
    <div className="max-w-full mx-auto flex flex-col gap-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-slate-900 dark:text-white">
          {t('tenant.settings.title')}
        </h1>
        <p className="text-slate-500 dark:text-slate-400 mt-1">{t('tenant.settings.subtitle')}</p>
      </div>

      {/* General Settings */}
      <div className="bg-white dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 p-6 md:p-8">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-6 flex items-center gap-2">
          <span className="material-symbols-outlined text-primary">settings</span>
          {t('tenant.settings.general.title')}
        </h2>

        <div className="flex flex-col gap-6 max-w-2xl">
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              {t('tenant.settings.general.name')}
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all outline-none"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 dark:text-slate-300 mb-2">
              {t('tenant.settings.general.description')}
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-slate-900 dark:text-white focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all outline-none resize-none"
            />
          </div>

          {message && (
            <div
              className={`p-4 rounded-lg flex items-center gap-3 ${message.type === 'success' ? 'bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-300' : 'bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-300'}`}
            >
              <span className="material-symbols-outlined text-[20px]">
                {message.type === 'success' ? 'check_circle' : 'error'}
              </span>
              {message.text}
            </div>
          )}

          <div>
            <button
              onClick={handleSave}
              disabled={isLoading}
              className="bg-primary hover:bg-primary-dark text-white px-6 py-2.5 rounded-lg font-medium transition-colors disabled:opacity-70 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {isLoading && (
                <span className="material-symbols-outlined animate-spin text-[20px]">
                  progress_activity
                </span>
              )}
              {t('tenant.settings.save')}
            </button>
          </div>
        </div>
      </div>

      {/* Plan & Usage */}
      <div className="bg-white dark:bg-surface-dark rounded-xl shadow-sm border border-slate-200 dark:border-slate-800 p-6 md:p-8">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-6 flex items-center gap-2">
          <span className="material-symbols-outlined text-primary">credit_card</span>
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
                Active
              </span>
            </div>
            <p className="text-sm text-slate-500 mb-6">
              {t('tenant.settings.plan.active_since', {
                date: formatDateOnly(tenant.created_at),
              })}
            </p>
            <button className="text-primary hover:text-primary-dark font-medium text-sm flex items-center gap-1">
              {t('tenant.settings.plan.change')}{' '}
              <span className="material-symbols-outlined text-[16px]">arrow_forward</span>
            </button>
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
                  <span className="font-medium text-slate-900 dark:text-white">3 / 10</span>
                </div>
                <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                  <div className="h-full bg-blue-500 w-[30%]"></div>
                </div>
              </div>
              <div>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-slate-600 dark:text-slate-300">
                    {t('tenant.settings.plan.storage')}
                  </span>
                  <span className="font-medium text-slate-900 dark:text-white">45%</span>
                </div>
                <div className="h-2 bg-slate-100 dark:bg-slate-800 rounded-full overflow-hidden">
                  <div className="h-full bg-purple-500 w-[45%]"></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Danger Zone */}
      <div className="bg-red-50 dark:bg-red-900/10 rounded-xl border border-red-200 dark:border-red-900/30 p-6 md:p-8">
        <h2 className="text-lg font-semibold text-red-700 dark:text-red-400 mb-2 flex items-center gap-2">
          <span className="material-symbols-outlined">warning</span>
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
          <button className="bg-white border border-red-300 text-red-600 hover:bg-red-50 px-4 py-2 rounded-lg text-sm font-medium transition-colors shadow-sm whitespace-nowrap dark:bg-transparent dark:border-red-800 dark:text-red-400 dark:hover:bg-red-900/20">
            {t('tenant.settings.danger.delete_button')}
          </button>
        </div>
      </div>
    </div>
  );
};

export const TenantSettings: React.FC = () => {
  const { currentTenant } = useTenantStore();

  if (!currentTenant) return null;

  return <TenantSettingsForm key={currentTenant.id} tenant={currentTenant} />;
};

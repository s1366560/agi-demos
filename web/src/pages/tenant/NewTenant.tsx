import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, Link } from 'react-router-dom';

import { AlertCircle, ArrowRight, Brain, Building2, Loader2 } from 'lucide-react';

import { useTenantStore } from '../../stores/tenant';
import { confirmAction } from '../../utils/confirmAction';
import { logger } from '../../utils/logger';

export const NewTenant: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { createTenant, isLoading, error } = useTenantStore();

  const [formData, setFormData] = useState({
    name: '',
    description: '',
    plan: 'free',
  });

  const isDirty = formData.name.trim() !== '' || formData.description.trim() !== '';

  const handleNavAway = (e: React.MouseEvent<HTMLAnchorElement>) => {
    if (!isDirty) return;
    e.preventDefault();
    void confirmAction({
      title: t('tenant.create_page.discardConfirm'),
      danger: true,
    }).then((confirmed) => {
      if (confirmed) void navigate('/tenant');
    });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createTenant({
        name: formData.name,
        description: formData.description,
        plan: formData.plan,
      });
      void navigate('/tenant');
    } catch (err) {
      logger.error('Failed to create tenant', err);
    }
  };

  return (
    <div className="min-h-screen bg-background-light dark:bg-background-dark flex flex-col">
      {/* Header */}
      <header className="w-full border-b border-slate-200 dark:border-slate-800 bg-surface-light dark:bg-surface-dark sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 md:px-8 h-16 flex items-center justify-between">
          <Link to="/tenant" onClick={handleNavAway} className="flex items-center gap-3">
            <div className="size-8 text-primary flex items-center justify-center bg-primary/10 rounded-lg">
              <Brain size={24} />
            </div>
            <span className="text-lg font-bold tracking-tight text-slate-900 dark:text-white">
              MemStack<span className="text-primary">.ai</span>
            </span>
          </Link>
          <Link
            to="/tenant"
            onClick={handleNavAway}
            className="text-sm font-medium text-slate-500 hover:text-primary transition-colors"
          >
            {t('tenant.create_page.header_cancel')}
          </Link>
        </div>
      </header>

      {/* Main Content */}
      <main className="relative flex flex-grow items-center justify-center overflow-hidden px-4 py-12 sm:px-6 lg:px-8">
        <div className="z-10 w-full max-w-[540px]">
          <div className="overflow-hidden rounded-lg border border-slate-200 bg-surface-light shadow-sm dark:border-slate-800 dark:bg-surface-dark">
            <div className="p-8 pb-4">
              <div className="flex flex-col gap-2">
                <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">
                  {t('tenant.create_page.title')}
                </h1>
                <p className="text-slate-500 dark:text-slate-400 text-base">
                  {t('tenant.create_page.subtitle')}
                </p>
              </div>
            </div>

            {error && (
              <div
                role="alert"
                className="mx-8 mb-4 p-4 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 rounded-lg text-sm border border-red-200 dark:border-red-800 flex items-center gap-2"
              >
                <AlertCircle size={16} aria-hidden="true" />
                {error}
              </div>
            )}

            <form
              onSubmit={(event) => {
                void handleSubmit(event);
              }}
              className="p-8 pt-2 flex flex-col gap-6"
            >
              <div className="space-y-4">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                  {t('tenant.create_page.org_details')}
                </h3>

                <label className="flex flex-col w-full">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-2">
                    {t('tenant.create_page.name')} <span className="text-red-500">*</span>
                  </span>
                  <div className="relative group">
                    <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-slate-400">
                      <Building2 size={20} />
                    </div>
                    <input
                      required
                      name="name"
                      autoComplete="organization"
                      spellCheck={false}
                      value={formData.name}
                      onChange={(e) => {
                        setFormData({ ...formData, name: e.target.value });
                      }}
                      className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary pl-10 h-12 text-sm placeholder:text-slate-400 transition-[color,background-color,border-color,box-shadow,opacity,transform] outline-none"
                      placeholder={t('tenant.create_page.name_placeholder', {
                        defaultValue: 'e.g. Acme Corp',
                      })}
                      type="text"
                    />
                  </div>
                </label>

                <label className="flex flex-col w-full">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-2">
                    {t('tenant.create_page.description', { defaultValue: 'Description' })}
                  </span>
                  <textarea
                    rows={3}
                    value={formData.description}
                    onChange={(e) => {
                      setFormData({ ...formData, description: e.target.value });
                    }}
                    className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary p-3 text-sm placeholder:text-slate-400 transition-[color,background-color,border-color,box-shadow,opacity,transform] outline-none resize-none"
                    placeholder={t('tenant.create_page.description_placeholder', {
                      defaultValue: 'Briefly describe your organization…',
                    })}
                  />
                </label>

                <label className="flex flex-col w-full">
                  <span className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-2">
                    {t('tenant.create_page.plan', { defaultValue: 'Plan' })}
                  </span>
                  <select
                    value={formData.plan}
                    onChange={(e) => {
                      setFormData({ ...formData, plan: e.target.value });
                    }}
                    className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary h-12 px-3 text-sm outline-none"
                  >
                    <option value="free">
                      {t('tenant.create_page.plan_options.free', { defaultValue: 'Free Starter' })}
                    </option>
                    <option value="basic">
                      {t('tenant.create_page.plan_options.basic', { defaultValue: 'Basic Team' })}
                    </option>
                    <option value="premium">
                      {t('tenant.create_page.plan_options.premium', {
                        defaultValue: 'Premium Business',
                      })}
                    </option>
                    <option value="enterprise">
                      {t('tenant.create_page.plan_options.enterprise', {
                        defaultValue: 'Enterprise',
                      })}
                    </option>
                  </select>
                </label>
              </div>

              <div className="pt-2">
                <button
                  type="submit"
                  disabled={isLoading || !formData.name.trim()}
                  className="w-full flex items-center justify-center h-12 px-6 rounded-lg bg-primary hover:bg-primary/90 text-white font-bold text-sm tracking-wide shadow-lg shadow-primary/25 transition-[color,background-color,border-color,box-shadow,opacity] disabled:opacity-70 disabled:cursor-not-allowed"
                >
                  {isLoading ? (
                    <Loader2 size={16} className="animate-spin motion-reduce:animate-none" />
                  ) : (
                    <>
                      {t('tenant.create_page.submit')}
                      <ArrowRight size={16} className="ml-2" />
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      </main>
    </div>
  );
};

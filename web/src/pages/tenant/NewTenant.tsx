import React, { useState } from 'react';

import { useTranslation } from 'react-i18next';
import { useNavigate, Link } from 'react-router-dom';

import { ArrowRight, Brain, Loader2 } from 'lucide-react';

import {
  DEFAULT_TENANT_CREATE_VALUES,
  TenantCreateForm,
} from '@/components/tenant/TenantCreateForm';
import type { TenantCreateFormValues } from '@/components/tenant/TenantCreateForm';
import { useLazyMessage } from '@/components/ui/lazyAntd';

import { useTenantStore } from '../../stores/tenant';
import { confirmAction } from '../../utils/confirmAction';
import { logger } from '../../utils/logger';

export const NewTenant: React.FC = () => {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const message = useLazyMessage();
  const { createTenant, isLoading, error } = useTenantStore();

  const [formData, setFormData] = useState<TenantCreateFormValues>(DEFAULT_TENANT_CREATE_VALUES);

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

  const handleSubmit = async (values: TenantCreateFormValues) => {
    try {
      await createTenant({
        name: values.name,
        description: values.description,
        plan: values.plan,
      });
      message?.success(t('tenant.create_page.success', { defaultValue: 'Organization created' }));
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

            <div className="p-8 pt-2">
              <TenantCreateForm
                values={formData}
                onChange={setFormData}
                onSubmit={(values) => {
                  void handleSubmit(values);
                }}
                showPlan
                isLoading={isLoading}
                error={error}
              >
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
              </TenantCreateForm>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
};

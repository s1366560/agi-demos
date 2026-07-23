import React from 'react';

import { useTranslation } from 'react-i18next';

import { AlertCircle, Building2 } from 'lucide-react';

export interface TenantCreateFormValues {
  name: string;
  description: string;
  plan: string;
}

// eslint-disable-next-line react-refresh/only-export-components
export const DEFAULT_TENANT_CREATE_VALUES: TenantCreateFormValues = {
  name: '',
  description: '',
  plan: 'free',
};

const PLAN_OPTIONS = ['free', 'basic', 'premium', 'enterprise'] as const;

interface TenantCreateFormProps {
  /** Form id so an external submit button (e.g. in a modal footer) can trigger it. */
  formId?: string | undefined;
  values: TenantCreateFormValues;
  onChange: (values: TenantCreateFormValues) => void;
  onSubmit: (values: TenantCreateFormValues) => void;
  /** Show the plan selector (full-page onboarding); hidden in the modal. */
  showPlan?: boolean | undefined;
  isLoading?: boolean | undefined;
  error?: string | null | undefined;
  /** Optional inline actions (e.g. a submit button) rendered after the fields. */
  children?: React.ReactNode;
}

/**
 * Shared tenant creation form used by both the NewTenant page and the
 * TenantCreateModal so fields, validation, and submission stay in sync.
 */
export const TenantCreateForm: React.FC<TenantCreateFormProps> = ({
  formId,
  values,
  onChange,
  onSubmit,
  showPlan = false,
  isLoading = false,
  error,
  children,
}) => {
  const { t } = useTranslation();

  return (
    <form
      id={formId}
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(values);
      }}
      className="flex flex-col gap-6"
    >
      {error ? (
        <div
          role="alert"
          className="p-4 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 rounded-lg text-sm border border-red-200 dark:border-red-800 flex items-center gap-2"
        >
          <AlertCircle size={16} aria-hidden="true" />
          {error}
        </div>
      ) : null}

      <div className="space-y-4">
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
              type="text"
              autoComplete="organization"
              spellCheck={false}
              disabled={isLoading}
              value={values.name}
              onChange={(e) => {
                onChange({ ...values, name: e.target.value });
              }}
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary pl-10 h-12 text-sm placeholder:text-slate-400 transition-[color,background-color,border-color,box-shadow,opacity,transform] outline-none disabled:opacity-50 disabled:cursor-not-allowed"
              placeholder={t('tenant.create_page.name_placeholder')}
            />
          </div>
        </label>

        <label className="flex flex-col w-full">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-2">
            {t('tenant.create_page.description')}
          </span>
          <textarea
            rows={3}
            name="description"
            disabled={isLoading}
            value={values.description}
            onChange={(e) => {
              onChange({ ...values, description: e.target.value });
            }}
            className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary p-3 text-sm placeholder:text-slate-400 transition-[color,background-color,border-color,box-shadow,opacity,transform] outline-none resize-none disabled:opacity-50 disabled:cursor-not-allowed"
            placeholder={t('tenant.create_page.description_placeholder')}
          />
        </label>

        {showPlan ? (
          <label className="flex flex-col w-full">
            <span className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-2">
              {t('tenant.create_page.plan')}
            </span>
            <select
              name="plan"
              disabled={isLoading}
              value={values.plan}
              onChange={(e) => {
                onChange({ ...values, plan: e.target.value });
              }}
              className="w-full rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white focus:border-primary focus:ring-1 focus:ring-primary h-12 px-3 text-sm outline-none disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {PLAN_OPTIONS.map((plan) => (
                <option key={plan} value={plan}>
                  {t(`tenant.create_page.plan_options.${plan}`)}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </div>

      {children}
    </form>
  );
};

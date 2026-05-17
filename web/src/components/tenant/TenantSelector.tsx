import React from 'react';

import { useTranslation } from 'react-i18next';

import { Building2, Plus, Settings } from 'lucide-react';

import { formatDateOnly } from '@/utils/date';

import { useTenantStore } from '../../stores/tenant';
import { Tenant } from '../../types/memory';

interface TenantSelectorProps {
  onCreateTenant?: (() => void) | undefined;
  onManageTenant?: ((tenant: Tenant) => void) | undefined;
}

export const TenantSelector: React.FC<TenantSelectorProps> = ({
  onCreateTenant,
  onManageTenant,
}) => {
  const { t } = useTranslation();
  const { tenants, currentTenant, setCurrentTenant, isLoading } = useTenantStore();

  const handleTenantSelect = (tenant: Tenant) => {
    setCurrentTenant(tenant);
  };

  const getPlanColor = (plan: string) => {
    switch (plan) {
      case 'free':
        return 'bg-gray-100 text-gray-800 dark:bg-slate-800 dark:text-slate-200';
      case 'basic':
        return 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300';
      case 'premium':
        return 'bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300';
      case 'enterprise':
        return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300';
      default:
        return 'bg-gray-100 text-gray-800 dark:bg-slate-800 dark:text-slate-200';
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-4">
        <div className="animate-spin motion-reduce:animate-none rounded-full h-6 w-6 border-b-2 border-blue-600 dark:border-blue-400"></div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800">
      <div className="p-4 border-b border-gray-200 dark:border-slate-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Building2 className="h-5 w-5 text-gray-600 dark:text-slate-400" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              {t('tenant.selector.workspacesTitle')}
            </h3>
          </div>
          <button
            type="button"
            onClick={onCreateTenant}
            className="flex items-center space-x-1 px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1 text-sm"
          >
            <Plus className="h-4 w-4" />
            <span>{t('tenant.selector.newButton')}</span>
          </button>
        </div>
      </div>

      <div className="p-4">
        {tenants.length === 0 ? (
          <div className="text-center py-8">
            <Building2 className="h-12 w-12 text-gray-400 dark:text-slate-600 mx-auto mb-3" />
            <p className="text-gray-600 dark:text-slate-400 mb-4">
              {t('tenant.selector.emptyMessage')}
            </p>
            <button
              type="button"
              onClick={onCreateTenant}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-1"
            >
              {t('tenant.selector.createButton')}
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            {tenants.map((tenant) => (
              <div
                key={tenant.id}
                className={`rounded-lg border transition-[color,background-color,border-color,box-shadow,opacity,transform] duration-150 ${
                  currentTenant?.id === tenant.id
                    ? 'border-blue-500 dark:border-blue-400 bg-blue-50 dark:bg-blue-900/20'
                    : 'border-gray-200 dark:border-slate-700 hover:border-gray-300 dark:hover:border-slate-600 hover:bg-gray-50 dark:hover:bg-slate-800'
                }`}
              >
                <div className="flex items-center justify-between p-3">
                  <button
                    type="button"
                    onClick={() => {
                      handleTenantSelect(tenant);
                    }}
                    className="flex min-w-0 flex-1 items-center space-x-3 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                  >
                    <div className="flex-shrink-0">
                      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-slate-900 dark:bg-slate-100">
                        <Building2 className="h-5 w-5 text-slate-50 dark:text-slate-900" />
                      </div>
                    </div>
                    <div>
                      <h4 className="text-sm font-medium text-gray-900 dark:text-white">
                        {tenant.name}
                      </h4>
                      <div className="flex items-center space-x-2 mt-1">
                        <span
                          className={`px-2 py-1 rounded-full text-xs font-medium ${getPlanColor(tenant.plan)}`}
                        >
                          {tenant.plan}
                        </span>
                        <span className="text-xs text-gray-500 dark:text-slate-400">
                          {formatDateOnly(tenant.created_at)}
                        </span>
                      </div>
                    </div>
                  </button>
                  <div className="flex items-center space-x-2">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onManageTenant?.(tenant);
                      }}
                      aria-label={t('tenant.selector.manageTenant', {
                        tenant: tenant.name,
                        defaultValue: 'Manage {{tenant}}',
                      })}
                      title={t('tenant.selector.manageTenant', {
                        tenant: tenant.name,
                        defaultValue: 'Manage {{tenant}}',
                      })}
                      className="p-2 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-700 rounded-md transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                    >
                      <Settings className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

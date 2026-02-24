import React from 'react';

import { Building2, Plus, Settings } from 'lucide-react';

import { formatDateOnly } from '@/utils/date';

import { useTenantStore } from '../../stores/tenant';
import { Tenant } from '../../types/memory';

interface TenantSelectorProps {
  onCreateTenant?: () => void;
  onManageTenant?: (tenant: Tenant) => void;
}

export const TenantSelector: React.FC<TenantSelectorProps> = ({
  onCreateTenant,
  onManageTenant,
}) => {
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
        <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600 dark:border-blue-400"></div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-900 rounded-lg shadow-sm border border-gray-200 dark:border-slate-800">
      <div className="p-4 border-b border-gray-200 dark:border-slate-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Building2 className="h-5 w-5 text-gray-600 dark:text-slate-400" />
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">工作空间</h3>
          </div>
          <button
            onClick={onCreateTenant}
            className="flex items-center space-x-1 px-3 py-1.5 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors text-sm"
          >
            <Plus className="h-4 w-4" />
            <span>新建</span>
          </button>
        </div>
      </div>

      <div className="p-4">
        {tenants.length === 0 ? (
          <div className="text-center py-8">
            <Building2 className="h-12 w-12 text-gray-400 dark:text-slate-600 mx-auto mb-3" />
            <p className="text-gray-600 dark:text-slate-400 mb-4">暂无工作空间</p>
            <button
              onClick={onCreateTenant}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
            >
              创建工作空间
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            {tenants.map((tenant) => (
              <div
                key={tenant.id}
                className={`p-3 rounded-lg border cursor-pointer transition-all ${
                  currentTenant?.id === tenant.id
                    ? 'border-blue-500 dark:border-blue-400 bg-blue-50 dark:bg-blue-900/20'
                    : 'border-gray-200 dark:border-slate-700 hover:border-gray-300 dark:hover:border-slate-600 hover:bg-gray-50 dark:hover:bg-slate-800'
                }`}
                onClick={() => { handleTenantSelect(tenant); }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-3">
                    <div className="flex-shrink-0">
                      <div className="w-10 h-10 bg-gradient-to-br from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
                        <Building2 className="h-5 w-5 text-white" />
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
                  </div>
                  <div className="flex items-center space-x-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onManageTenant?.(tenant);
                      }}
                      className="p-2 text-gray-400 dark:text-slate-500 hover:text-gray-600 dark:hover:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-700 rounded-md transition-colors"
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

/**
 * TenantWorkspaceSwitcher - Convenience component for tenant switching
 *
 * Pre-configured WorkspaceSwitcher for tenant mode.
 */

import { useEffect } from 'react';

import { useTranslation } from 'react-i18next';
import { useLocation, useNavigate } from 'react-router-dom';

import { Brain, ChevronsUpDown } from 'lucide-react';

import { useTenantStore } from '@/stores/tenant';

import { WorkspaceSwitcherRoot, WorkspaceSwitcherTrigger, WorkspaceSwitcherMenu } from './compound';
import { TenantList } from './TenantList';

import type { Tenant } from '@/types/memory';

import type { TenantWorkspaceSwitcherProps } from './types';

export const TenantWorkspaceSwitcher: React.FC<TenantWorkspaceSwitcherProps> = ({
  onTenantSelect,
  onCreateTenant,
  createLabel,
  triggerClassName = '',
  menuClassName = '',
}) => {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();

  // Store hooks - use selective selectors to prevent unnecessary re-renders
  const tenants = useTenantStore((state) => state.tenants);
  const currentTenant = useTenantStore((state) => state.currentTenant);
  const listTenants = useTenantStore((state) => state.listTenants);
  const setCurrentTenant = useTenantStore((state) => state.setCurrentTenant);

  // Load data if missing
  useEffect(() => {
    if (tenants.length === 0) {
      void listTenants();
    }
  }, [tenants.length, listTenants]);

  const handleTenantSelect = (tenant: Tenant) => {
    if (currentTenant?.id !== tenant.id) {
      setCurrentTenant(tenant);
    }
    onTenantSelect?.(tenant);
    const targetPath = `/tenant/${tenant.id}/overview`;
    if (location.pathname !== targetPath) {
      void navigate(targetPath);
    }
  };

  const handleCreateTenant = () => {
    if (onCreateTenant) {
      onCreateTenant();
    } else {
      void navigate('/tenants/new');
    }
  };

  return (
    <WorkspaceSwitcherRoot mode="tenant">
      <WorkspaceSwitcherTrigger className={triggerClassName}>
        <div className="bg-primary/10 p-1.5 rounded-md shrink-0 flex items-center justify-center">
          <Brain size={20} className="text-primary" />
        </div>
        <div className="flex flex-col overflow-hidden">
          <h1 className="text-slate-900 dark:text-white text-sm font-bold leading-none tracking-tight truncate">
            {currentTenant?.name ||
              t('components.workspaceSwitcher.selectTenant', { defaultValue: 'Select Tenant' })}
          </h1>
          <p className="text-2xs text-slate-500 truncate leading-tight opacity-80">
            {t('components.workspaceSwitcher.tenantConsole', {
              defaultValue: 'Tenant Console',
            })}
          </p>
        </div>
        <ChevronsUpDown size={18} className="text-slate-400 ml-auto" />
      </WorkspaceSwitcherTrigger>

      <WorkspaceSwitcherMenu
        label={t('components.workspaceSwitcher.switchTenant', {
          defaultValue: 'Switch Tenant',
        })}
        className={menuClassName}
      >
        <TenantList
          tenants={tenants}
          currentTenant={currentTenant}
          onTenantSelect={handleTenantSelect}
          onCreateTenant={handleCreateTenant}
          createLabel={
            createLabel ??
            t('components.workspaceSwitcher.createTenant', {
              defaultValue: 'Create Tenant',
            })
          }
        />
      </WorkspaceSwitcherMenu>
    </WorkspaceSwitcherRoot>
  );
};

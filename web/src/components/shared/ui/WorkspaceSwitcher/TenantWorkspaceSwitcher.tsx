/**
 * TenantWorkspaceSwitcher - Convenience component for tenant switching
 *
 * Pre-configured WorkspaceSwitcher for tenant mode.
 */

import { useEffect } from 'react'

import { useNavigate } from 'react-router-dom'

import { useTenantStore } from '@/stores/tenant'

import {
  WorkspaceSwitcherRoot,
  WorkspaceSwitcherTrigger,
  WorkspaceSwitcherMenu,
} from './compound'
import { TenantList } from './TenantList'

import type { Tenant } from '@/types/memory'

import type { TenantWorkspaceSwitcherProps } from './types'

export const TenantWorkspaceSwitcher: React.FC<TenantWorkspaceSwitcherProps> = ({
  onTenantSelect,
  onCreateTenant,
  createLabel = 'Create Tenant',
  triggerClassName = '',
  menuClassName = '',
}) => {
  const navigate = useNavigate()

  // Store hooks - use selective selectors to prevent unnecessary re-renders
  const tenants = useTenantStore((state) => state.tenants)
  const currentTenant = useTenantStore((state) => state.currentTenant)
  const listTenants = useTenantStore((state) => state.listTenants)
  const setCurrentTenant = useTenantStore((state) => state.setCurrentTenant)

  // Load data if missing
  useEffect(() => {
    if (tenants.length === 0) listTenants()
  }, [tenants.length, listTenants])

  const handleTenantSelect = (tenant: Tenant) => {
    setCurrentTenant(tenant)
    onTenantSelect?.(tenant)
    navigate(`/tenant/${tenant.id}`)
  }

  const handleCreateTenant = () => {
    onCreateTenant?.() ?? navigate('/tenants/new')
  }

  return (
    <WorkspaceSwitcherRoot mode="tenant">
      <WorkspaceSwitcherTrigger className={triggerClassName}>
        <div className="bg-primary/10 p-1.5 rounded-md shrink-0 flex items-center justify-center">
          <span className="material-symbols-outlined text-primary text-[20px]">memory</span>
        </div>
        <div className="flex flex-col overflow-hidden">
          <h1 className="text-slate-900 dark:text-white text-sm font-bold leading-none tracking-tight truncate">
            {currentTenant?.name || 'Select Tenant'}
          </h1>
          <p className="text-[10px] text-slate-500 truncate leading-tight opacity-80">
            Tenant Console
          </p>
        </div>
        <span className="material-symbols-outlined text-slate-400 ml-auto text-[18px]">
          unfold_more
        </span>
      </WorkspaceSwitcherTrigger>

      <WorkspaceSwitcherMenu label="Switch Tenant" className={menuClassName}>
        <TenantList
          tenants={tenants}
          currentTenant={currentTenant}
          onTenantSelect={handleTenantSelect}
          onCreateTenant={handleCreateTenant}
          createLabel={createLabel}
        />
      </WorkspaceSwitcherMenu>
    </WorkspaceSwitcherRoot>
  )
}

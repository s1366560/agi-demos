/**
 * TenantSidebar Component
 *
 * Tenant-level sidebar wrapper that provides navigation configuration
 * and state management for the tenant console layout.
 */

import * as React from 'react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AppSidebar } from './AppSidebar'
import { getTenantSidebarConfig } from '@/config/navigation'
import { useAuthStore } from '@/stores/auth'
import type { NavUser } from '@/config/navigation'

export interface TenantSidebarProps {
  /** Current tenant ID for path generation */
  tenantId?: string
  /** Initial collapsed state */
  defaultCollapsed?: boolean
}

/**
 * Tenant sidebar component with configuration and state management
 */
export function TenantSidebar({
  tenantId,
  defaultCollapsed = false,
}: TenantSidebarProps): JSX.Element {
  const { t } = useTranslation()
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  // Internal state for collapse
  const [collapsed, setCollapsed] = useState(defaultCollapsed)

  // Internal state for group toggles
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({})

  const basePath = tenantId ? `/tenant/${tenantId}` : '/tenant'

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const handleGroupToggle = (groupId: string) => {
    setOpenGroups((prev) => ({ ...prev, [groupId]: !prev[groupId] }))
  }

  const navUser: NavUser = {
    name: user?.name || 'User',
    email: user?.email || 'user@example.com',
  }

  return (
    <AppSidebar
      config={getTenantSidebarConfig()}
      basePath={basePath}
      context="tenant"
      collapsed={collapsed}
      onCollapseToggle={() => setCollapsed(!collapsed)}
      user={navUser}
      onLogout={handleLogout}
      openGroups={openGroups}
      onGroupToggle={handleGroupToggle}
      t={t}
    />
  )
}

export default TenantSidebar

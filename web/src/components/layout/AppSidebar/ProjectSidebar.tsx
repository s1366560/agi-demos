/**
 * ProjectSidebar Component (Refactored)
 *
 * Project-level sidebar variant component.
 * Explicit variant with embedded configuration and state management.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AppSidebar } from './AppSidebar'
import { getProjectSidebarConfig } from '@/config/navigation'
import { useAuthStore } from '@/stores/auth'
import type { NavUser } from '@/config/navigation'
import type { ProjectSidebarProps } from './types'

/**
 * Project sidebar component with configuration and state management
 */
export function ProjectSidebar({
  projectId = '',
  defaultCollapsed = false,
  collapsed: controlledCollapsed,
  onCollapseToggle,
  user: externalUser,
  onLogout: externalLogout,
  openGroups: controlledOpenGroups,
  onGroupToggle,
  t: externalT,
}: ProjectSidebarProps & {
  collapsed?: boolean
  onCollapseToggle?: () => void
  user?: NavUser
  onLogout?: () => void
  openGroups?: Record<string, boolean>
  onGroupToggle?: (groupId: string) => void
  t?: (key: string) => string
}) {
  const { t: useT } = useTranslation()
  const { user: authUser, logout: authLogout } = useAuthStore()
  const navigate = useNavigate()

  // Use external callbacks if provided, otherwise use internal state
  const [internalCollapsed, setInternalCollapsed] = useState(defaultCollapsed)
  const [internalOpenGroups, setInternalOpenGroups] = useState<Record<string, boolean>>({
    knowledge: true,
    discovery: true,
    config: true,
  })

  const collapsed = controlledCollapsed ?? internalCollapsed
  const openGroups = controlledOpenGroups ?? internalOpenGroups
  const handleCollapseToggle = onCollapseToggle ?? (() => setInternalCollapsed(!collapsed))
  const handleGroupToggle = onGroupToggle ?? ((groupId: string) => {
    setInternalOpenGroups((prev) => ({ ...prev, [groupId]: !prev[groupId] }))
  })

  const basePath = `/project/${projectId}`

  const handleLogout = externalLogout ?? (() => {
    authLogout()
    navigate('/login')
  })

  const navUser: NavUser = externalUser ?? {
    name: authUser?.name || 'User',
    email: authUser?.email || 'user@example.com',
  }

  const t = externalT ?? useT

  return (
    <AppSidebar
      config={getProjectSidebarConfig()}
      basePath={basePath}
      variant="project"
      collapsed={collapsed}
      onCollapseToggle={handleCollapseToggle}
      user={navUser}
      onLogout={handleLogout}
      openGroups={openGroups}
      onGroupToggle={handleGroupToggle}
      t={t}
    />
  )
}

export default ProjectSidebar

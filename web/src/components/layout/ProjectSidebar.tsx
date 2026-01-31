/**
 * ProjectSidebar Component
 *
 * Project-level sidebar wrapper that provides navigation configuration
 * and state management for the project workbench layout.
 */

import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AppSidebar } from './AppSidebar'
import { getProjectSidebarConfig } from '@/config/navigation'
import { useAuthStore } from '@/stores/auth'
import type { NavUser } from '@/config/navigation'

export interface ProjectSidebarProps {
  /** Current project ID for path generation */
  projectId?: string
  /** Initial collapsed state */
  defaultCollapsed?: boolean
}

/**
 * Project sidebar component with configuration and state management
 */
export function ProjectSidebar({
  projectId = '',
  defaultCollapsed = false,
}: ProjectSidebarProps) {
  const { t } = useTranslation()
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  // Internal state for collapse
  const [collapsed, setCollapsed] = useState(defaultCollapsed)

  // Internal state for group toggles - some groups open by default
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({
    knowledge: true,
    discovery: true,
    config: true,
  })

  const basePath = `/project/${projectId}`

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
      config={getProjectSidebarConfig()}
      basePath={basePath}
      context="project"
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

export default ProjectSidebar

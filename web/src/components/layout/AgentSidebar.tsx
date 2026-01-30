/**
 * AgentSidebar Component
 *
 * Agent-level sidebar wrapper that provides navigation configuration
 * and state management for the agent layout.
 */

import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AppSidebar } from './AppSidebar'
import { getAgentConfig } from '@/config/navigation'
import { useAuthStore } from '@/stores/auth'
import type { NavUser } from '@/config/navigation'

export interface AgentSidebarProps {
  /** Current project ID for navigation */
  projectId?: string
  /** Current conversation ID for navigation */
  conversationId?: string
  /** Initial collapsed state */
  defaultCollapsed?: boolean
  /** Controlled collapsed state */
  collapsed?: boolean
  /** Callback when collapse is toggled */
  onCollapseToggle?: () => void
}

/**
 * Agent sidebar component with configuration and state management
 */
export function AgentSidebar({
  projectId = '',
  conversationId = '',
  defaultCollapsed = false,
  collapsed: controlledCollapsed,
  onCollapseToggle,
}: AgentSidebarProps): JSX.Element {
  const { t } = useTranslation()
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  // Agent sidebar basePath is the project level
  // Navigation items use relative paths from there
  // This avoids double slashes when conversationId is empty
  const basePath = projectId ? `/project/${projectId}` : '/project'

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  const navUser: NavUser = {
    name: user?.name || 'User',
    email: user?.email || 'user@example.com',
  }

  // Agent sidebar has a flat structure without collapsible groups
  const config = getAgentConfig().sidebar

  // Determine collapsed state: controlled > defaultCollapsed > false
  const isCollapsed = controlledCollapsed ?? defaultCollapsed ?? false

  return (
    <AppSidebar
      config={config}
      basePath={basePath}
      context="agent"
      collapsed={isCollapsed}
      onCollapseToggle={onCollapseToggle}
      user={navUser}
      onLogout={handleLogout}
      t={t}
    />
  )
}

export default AgentSidebar

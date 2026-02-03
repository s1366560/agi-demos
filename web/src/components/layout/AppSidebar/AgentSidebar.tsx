/**
 * AgentSidebar Component (Refactored)
 *
 * Agent-level sidebar variant component.
 * Explicit variant with embedded configuration and state management.
 */

import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AppSidebar } from './AppSidebar'
import { getAgentConfig } from '@/config/navigation'
import { useAuthStore } from '@/stores/auth'
import type { NavUser } from '@/config/navigation'
import type { AgentSidebarProps } from './types'

/**
 * Agent sidebar component with configuration and state management
 */
export function AgentSidebar({
  projectId = '',
  // conversationId // Reserved for future use
  defaultCollapsed = false,
  collapsed: controlledCollapsed,
  onCollapseToggle,
  user: externalUser,
  onLogout: externalLogout,
  t: externalT,
}: AgentSidebarProps & {
  collapsed?: boolean
  onCollapseToggle?: () => void
  user?: NavUser
  onLogout?: () => void
  t?: (key: string) => string
}) {
  const { t: useT } = useTranslation()
  const { user: authUser, logout: authLogout } = useAuthStore()
  const navigate = useNavigate()

  // Agent sidebar basePath is the project level
  const basePath = projectId ? `/project/${projectId}` : '/project'

  const handleLogout = externalLogout ?? (() => {
    authLogout()
    navigate('/login')
  })

  const navUser: NavUser = externalUser ?? {
    name: authUser?.name || 'User',
    email: authUser?.email || 'user@example.com',
  }

  const t = externalT ?? useT

  // Agent sidebar has a flat structure without collapsible groups
  const config = getAgentConfig().sidebar

  // Determine collapsed state: controlled > defaultCollapsed > false
  const isCollapsed = controlledCollapsed ?? defaultCollapsed ?? false

  return (
    <AppSidebar
      config={config}
      basePath={basePath}
      variant="agent"
      collapsed={isCollapsed}
      onCollapseToggle={onCollapseToggle}
      user={navUser}
      onLogout={handleLogout}
      t={t}
    />
  )
}

export default AgentSidebar

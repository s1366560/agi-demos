/**
 * AppSidebar Component
 *
 * A reusable sidebar component that accepts navigation configuration
 * and renders a collapsible sidebar with navigation groups.
 */

import * as React from 'react'
import { useState } from 'react'
import { Collapse } from 'antd'
import { ChevronDown } from 'lucide-react'
import { SidebarNavItem } from './SidebarNavItem'
import type { SidebarConfig, NavGroup, NavUser } from '@/config/navigation'

export interface AppSidebarProps {
  /** Sidebar configuration from navigation.ts */
  config: SidebarConfig
  /** Base path for generating links */
  basePath: string
  /** Layout context for styling */
  context?: 'tenant' | 'project' | 'agent'
  /** Current collapsed state (controlled) */
  collapsed?: boolean
  /** Default collapsed state */
  defaultCollapsed?: boolean
  /** Callback when collapse state changes */
  onCollapseToggle?: () => void
  /** User information for profile section */
  user?: NavUser
  /** Callback when user logs out */
  onLogout?: () => void
  /** Currently open groups (controlled) */
  openGroups?: Record<string, boolean>
  /** Callback when group is toggled */
  onGroupToggle?: (groupId: string) => void
  /** Brand element to display in header */
  brand?: React.ReactNode
  /** Translation function for labels */
  t?: (key: string) => string
}

/**
 * Get default brand element
 */
function getDefaultBrand(_context?: string): React.ReactNode {
  return (
    <div className="flex items-center gap-3 px-2">
      <div className="bg-primary/10 p-2 rounded-lg border border-primary/20">
        <span className="material-symbols-outlined text-primary">memory</span>
      </div>
      <h1 className="text-slate-900 dark:text-white text-lg font-bold leading-none tracking-tight">
        MemStack<span className="text-primary">.ai</span>
      </h1>
    </div>
  )
}

/**
 * Render a collapsible navigation group
 */
function NavGroupSection({
  group,
  basePath,
  collapsed,
  isOpen,
  onToggle,
  t,
}: {
  group: NavGroup
  basePath: string
  collapsed: boolean
  isOpen: boolean
  onToggle?: () => void
  t?: (key: string) => string
}) {
  const translate = t || ((key: string) => key)

  if (collapsed) {
    return (
      <div className="space-y-1">
        {group.items.map((item) => (
          <SidebarNavItem key={item.id} item={item} collapsed={collapsed} basePath={basePath} t={translate} />
        ))}
      </div>
    )
  }

  // Non-collapsible group (collapsible === false)
  if (group.collapsible === false) {
    return (
      <div className="space-y-1">
        {group.title && !collapsed && (
          <p className="px-3 text-[10px] font-semibold text-slate-400 uppercase tracking-wider mb-2">
            {translate(group.title)}
          </p>
        )}
        <div className="space-y-1">
          {group.items.map((item) => (
            <SidebarNavItem key={item.id} item={item} collapsed={collapsed} basePath={basePath} t={translate} />
          ))}
        </div>
      </div>
    )
  }

  // Collapsible group
  return (
    <div className="space-y-1">
      {/* Group header with collapse toggle */}
      {group.title && !collapsed && (
        <button
          onClick={onToggle}
          className="flex items-center justify-between w-full px-3 py-1.5 text-[10px] font-semibold text-slate-400 uppercase tracking-wider hover:text-slate-600 dark:hover:text-slate-300 transition-colors"
          type="button"
        >
          <span>{translate(group.title)}</span>
          <ChevronDown
            className={`w-3 h-3 transition-transform ${isOpen ? '' : '-rotate-90'}`}
          />
        </button>
      )}

      {/* Group items */}
      {!collapsed && (
        <Collapse in={isOpen ?? group.defaultOpen ?? true}>
          <div className="space-y-1">
            {group.items.map((item) => (
              <SidebarNavItem key={item.id} item={item} collapsed={collapsed} basePath={basePath} t={translate} />
            ))}
          </div>
        </Collapse>
      )}

      {/* When collapsed, always show items */}
      {collapsed && (
        <div className="space-y-1">
          {group.items.map((item) => (
            <SidebarNavItem key={item.id} item={item} collapsed={collapsed} basePath={basePath} t={translate} />
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * Main AppSidebar component
 */
export function AppSidebar({
  config,
  basePath,
  context,
  collapsed: controlledCollapsed,
  defaultCollapsed = false,
  onCollapseToggle,
  user,
  onLogout,
  openGroups: controlledOpenGroups,
  onGroupToggle,
  brand,
  t,
}: AppSidebarProps): JSX.Element {
  const translate = t || ((key: string) => key)

  // Internal state for uncontrolled mode
  const [internalCollapsed, setInternalCollapsed] = useState(defaultCollapsed)
  const [internalOpenGroups, setInternalOpenGroups] = useState<Record<string, boolean>>(() => {
    const initial: Record<string, boolean> = {}
    config.groups.forEach((group) => {
      if (group.defaultOpen !== undefined) {
        initial[group.id] = group.defaultOpen
      }
    })
    return initial
  })

  // Determine collapsed state (controlled vs uncontrolled)
  const isCollapsed = controlledCollapsed ?? internalCollapsed

  // Determine open groups state (controlled vs uncontrolled)
  const isOpenGroups = controlledOpenGroups ?? internalOpenGroups

  // Handle collapse toggle
  const handleCollapseToggle = () => {
    if (onCollapseToggle) {
      onCollapseToggle()
    } else {
      setInternalCollapsed(!isCollapsed)
    }
  }

  // Handle group toggle
  const handleGroupToggle = (groupId: string) => {
    if (onGroupToggle) {
      onGroupToggle(groupId)
    } else {
      setInternalOpenGroups((prev) => ({ ...prev, [groupId]: !prev[groupId] }))
    }
  }

  const width = isCollapsed ? (config.collapsedWidth ?? 80) : (config.width ?? 256)

  return (
    <aside
      className={`flex flex-col bg-surface-light dark:bg-surface-dark border-r border-slate-200 dark:border-border-dark flex-none z-20 transition-all duration-300 ease-in-out relative ${
        isCollapsed ? 'w-20' : 'w-64'
      }`}
      style={{ width: isCollapsed ? `${config.collapsedWidth ?? 80}px` : `${config.width ?? 256}px` }}
    >
      {/* Brand Header */}
      <div className="h-16 flex items-center px-4 border-b border-slate-100 dark:border-slate-800/50 shrink-0">
        {isCollapsed ? (
          <div className="w-full flex justify-center">
            <div className="bg-primary/10 p-2 rounded-lg border border-primary/20">
              <span className="material-symbols-outlined text-primary">memory</span>
            </div>
          </div>
        ) : (
          brand || getDefaultBrand(context)
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto custom-scrollbar px-3 py-4 space-y-4 shrink-0">
        {config.groups.map((group) => (
          <NavGroupSection
            key={group.id}
            group={group}
            basePath={basePath}
            collapsed={isCollapsed}
            isOpen={isOpenGroups[group.id] ?? group.defaultOpen ?? true}
            onToggle={() => handleGroupToggle(group.id)}
            t={translate}
          />
        ))}
      </nav>

      {/* Bottom Section */}
      {config.bottom && config.bottom.length > 0 && (
        <div className="px-3 py-2 border-t border-slate-100 dark:border-slate-800">
          {config.bottom.map((item) => (
            <SidebarNavItem key={item.id} item={item} collapsed={isCollapsed} basePath={basePath} t={translate} />
          ))}
        </div>
      )}

      {/* User Profile */}
      {config.showUser && user && (
        <div className="p-3 border-t border-slate-100 dark:border-slate-800">
          <div
            className={`flex items-center gap-3 p-2 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-700/50 group ${
              isCollapsed ? 'justify-center' : ''
            }`}
          >
            {/* Avatar */}
            <div className="size-8 rounded-full bg-gradient-to-br from-primary to-primary-light flex items-center justify-center text-xs font-bold text-white shrink-0 shadow-sm">
              {user.name?.[0]?.toUpperCase() || 'U'}
            </div>

            {/* User info */}
            {!isCollapsed && user && (
              <>
                <div className="flex flex-col overflow-hidden min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-900 dark:text-white truncate">
                    {user.name}
                  </p>
                  <p className="text-xs text-slate-500 truncate">{user.email}</p>
                </div>
              </>
            )}

            {/* Logout button */}
            {onLogout && !isCollapsed && (
              <button
                onClick={onLogout}
                className="p-1.5 text-slate-400 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md transition-colors opacity-0 group-hover:opacity-100"
                title="Sign out"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                </svg>
              </button>
            )}
          </div>
        </div>
      )}

      {/* Collapse Toggle Button */}
      <button
        onClick={handleCollapseToggle}
        className="absolute top-20 -right-3 w-6 h-6 bg-white dark:bg-surface-dark border border-slate-200 dark:border-border-dark rounded-full flex items-center justify-center shadow-sm hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors z-30"
        title={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        <svg className="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          {isCollapsed ? (
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          ) : (
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          )}
        </svg>
      </button>
    </aside>
  )
}

export default AppSidebar

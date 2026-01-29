/**
 * SidebarNavItem Component
 *
 * A reusable navigation item component for sidebar navigation.
 * Handles active state, tooltip when collapsed, and badges.
 */

import React from 'react'
import { Link } from 'react-router-dom'
import { Tooltip } from 'antd'
import { useNavigation } from '@/hooks/useNavigation'
import type { NavItem } from '@/config/navigation'

export interface SidebarNavItemProps {
  /** Navigation item configuration */
  item: NavItem
  /** Whether the sidebar is collapsed (show tooltip) */
  collapsed?: boolean
  /** Base path for generating links */
  basePath: string
  /** Current location pathname (for testing) */
  currentPathname?: string
  /** Whether to show as active */
  forceActive?: boolean
  /** Translation function (defaults to identity) */
  t?: (key: string) => string
}

/**
 * Normalize a path to ensure it starts with /
 */
function normalizePath(path: string): string {
  if (path === '') return ''
  return path.startsWith('/') ? path : `/${path}`
}

/**
 * Remove trailing slash from path
 */
function removeTrailingSlash(path: string): string {
  return path.endsWith('/') && path.length > 1 ? path.slice(0, -1) : path
}

/**
 * Check if a nav item is active based on current path
 */
function isNavActive(item: NavItem, basePath: string, currentPath: string): boolean {
  const normalizedCurrentPath = removeTrailingSlash(currentPath)
  const normalizedItemPath = normalizePath(item.path)
  const targetPath = basePath + normalizedItemPath

  // Handle empty path (root navigation)
  if (item.path === '' || item.exact) {
    return normalizedCurrentPath === targetPath
  }

  // Check for exact match or nested path match
  return (
    normalizedCurrentPath === targetPath ||
    normalizedCurrentPath.startsWith(`${targetPath}/`)
  )
}

/**
 * Render a single navigation item in the sidebar
 */
export function SidebarNavItem({
  item,
  collapsed = false,
  basePath,
  currentPathname,
  forceActive = false,
  t = (key: string) => key,
}: SidebarNavItemProps): JSX.Element {
  const { isActive: checkIsActive } = useNavigation(basePath)
  const currentPath = currentPathname || (typeof window !== 'undefined' ? window.location.pathname : '')

  const isActive = forceActive || checkIsActive(item.path)

  // Translate label if it looks like an i18n key (contains dot or starts with nav.)
  const label = item.label.includes('.') ? t(item.label) : item.label

  const linkContent = (
    <Link
      to={basePath + normalizePath(item.path)}
      className={`relative flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 group ${
        isActive
          ? 'bg-primary/10 text-primary font-medium'
          : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-white'
      } ${collapsed ? 'justify-center' : ''}`}
      aria-current={isActive ? 'page' : undefined}
    >
      {/* Icon */}
      <span
        className={`material-symbols-outlined text-[20px] ${
          isActive ? 'icon-filled' : ''
        }`}
      >
        {item.icon}
      </span>

      {/* Label */}
      {!collapsed && (
        <span className="text-sm whitespace-nowrap">{label}</span>
      )}

      {/* Badge */}
      {!collapsed && item.badge !== undefined && item.badge > 0 && (
        <span className="ml-auto bg-primary text-white text-xs px-1.5 py-0.5 rounded-full">
          {item.badge > 99 ? '99+' : item.badge}
        </span>
      )}

      {/* Active indicator dot */}
      {isActive && !collapsed && (
        <div className="absolute right-3 w-1.5 h-1.5 rounded-full bg-primary" />
      )}
    </Link>
  )

  // Show tooltip when collapsed
  if (collapsed) {
    return (
      <Tooltip title={label} placement="right">
        {linkContent}
      </Tooltip>
    )
  }

  return linkContent
}

export default SidebarNavItem

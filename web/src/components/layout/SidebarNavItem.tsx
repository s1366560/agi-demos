/**
 * SidebarNavItem Component
 *
 * A reusable navigation item component for sidebar navigation.
 * Handles active state, tooltip when collapsed, and badges.
 */

import { Link } from 'react-router-dom'

import { useNavigation } from '@/hooks/useNavigation'

import { LazyTooltip } from '@/components/ui/lazyAntd'

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
 * Render a single navigation item in the sidebar
 */
export function SidebarNavItem({
  item,
  collapsed = false,
  basePath,
  forceActive = false,
  t = (key: string) => key,
}: SidebarNavItemProps) {
  const { isActive: checkIsActive } = useNavigation(basePath)

  const isActive = forceActive || checkIsActive(item.path)

  // Translate label if it looks like an i18n key (contains dot or starts with nav.)
  const label = item.label.includes('.') ? t(item.label) : item.label

  const linkContent = (
    <Link
      to={basePath + normalizePath(item.path)}
      className={`relative flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 group ${
        isActive
          ? 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200'
          : 'text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/60 hover:text-slate-900 dark:hover:text-white'
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
        <span className="ml-auto bg-slate-500 dark:bg-slate-600 text-white text-xs px-1.5 py-0.5 rounded-full">
          {item.badge > 99 ? '99+' : item.badge}
        </span>
      )}

      {/* Active indicator line */}
      {isActive && (
        <div className={`absolute left-0 w-0.5 h-5 bg-slate-400 dark:bg-slate-500 rounded-r-full ${collapsed ? '' : 'hidden'}`} />
      )}
    </Link>
  )

  // Show tooltip when collapsed
  if (collapsed) {
    return (
      <LazyTooltip title={label} placement="right">
        {linkContent}
      </LazyTooltip>
    )
  }

  return linkContent
}

export default SidebarNavItem

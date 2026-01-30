/**
 * AppHeader Component
 *
 * A reusable header component for application layouts.
 * Provides breadcrumbs, search, theme toggle, language switcher,
 * notifications, and action buttons.
 */

import * as React from 'react'
import { Link } from 'react-router-dom'
import { Search, Bell, Menu, PanelLeft, PanelRight } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ThemeToggle } from '@/components/shared/ui/ThemeToggle'
import { LanguageSwitcher } from '@/components/shared/ui/LanguageSwitcher'
import { WorkspaceSwitcher } from '@/components/shared/ui/WorkspaceSwitcher'
import { useBreadcrumbs } from '@/hooks/useBreadcrumbs'

export interface Breadcrumb {
  label: string
  path: string
}

export interface AppHeaderProps {
  /** Layout context for breadcrumbs */
  context?: 'tenant' | 'project' | 'agent'
  /** Base path for navigation */
  basePath: string
  /** Current project/tenant name for context */
  contextName?: string
  /** Show sidebar toggle button */
  showSidebarToggle?: boolean
  /** Sidebar collapsed state */
  sidebarCollapsed?: boolean
  /** Callback when sidebar toggle is clicked */
  onSidebarToggle?: () => void
  /** Show mobile menu button */
  showMobileMenu?: boolean
  /** Callback when mobile menu is toggled */
  onMobileMenuToggle?: () => void
  /** Show search input */
  showSearch?: boolean
  /** Search input value */
  searchValue?: string
  /** Callback when search value changes */
  onSearchChange?: (value: string) => void
  /** Callback when search is submitted */
  onSearchSubmit?: (value: string) => void
  /** Show notifications bell */
  showNotifications?: boolean
  /** Notification count badge */
  notificationCount?: number
  /** Callback when notification bell is clicked */
  onNotificationsClick?: () => void
  /** Show theme toggle */
  showThemeToggle?: boolean
  /** Show language switcher */
  showLanguageSwitcher?: boolean
  /** Show workspace switcher */
  showWorkspaceSwitcher?: boolean
  /** Workspace switcher mode */
  workspaceMode?: 'tenant' | 'project'
  /** Primary action button */
  primaryAction?: {
    label: string
    to: string
    icon?: React.ReactNode
  }
  /** Additional actions to display on the right */
  extraActions?: React.ReactNode
  /** Custom breadcrumbs (overrides useBreadcrumbs hook) */
  breadcrumbs?: Breadcrumb[]
  /** Options for breadcrumb generation */
  breadcrumbOptions?: Parameters<typeof useBreadcrumbs>[1]
}

/**
 * Default breadcrumbs when no custom breadcrumbs provided
 */
function DefaultBreadcrumbs({ crumbs }: { crumbs: Breadcrumb[] }) {
  if (crumbs.length === 0) return null

  return (
    <nav className="flex items-center text-sm">
      {crumbs.map((crumb, index, array) => (
        <React.Fragment key={crumb.path}>
          {index > 0 && (
            <span className="mx-2 text-slate-300 dark:text-slate-600">/</span>
          )}
          {index === array.length - 1 ? (
            <span className="font-medium text-slate-900 dark:text-white">
              {crumb.label}
            </span>
          ) : (
            <Link
              to={crumb.path}
              className="text-slate-500 hover:text-primary transition-colors"
            >
              {crumb.label}
            </Link>
          )}
        </React.Fragment>
      ))}
    </nav>
  )
}

/**
 * Main AppHeader component
 */
export function AppHeader({
  context = 'tenant',
  basePath,
  contextName,
  showSidebarToggle = false,
  sidebarCollapsed = false,
  onSidebarToggle,
  showMobileMenu = false,
  onMobileMenuToggle,
  showSearch = true,
  searchValue = '',
  onSearchChange,
  onSearchSubmit,
  showNotifications = true,
  notificationCount = 0,
  onNotificationsClick,
  showThemeToggle = true,
  showLanguageSwitcher = true,
  showWorkspaceSwitcher = true,
  workspaceMode = 'tenant',
  primaryAction,
  extraActions,
  breadcrumbs: customBreadcrumbs,
  breadcrumbOptions,
}: AppHeaderProps): JSX.Element {
  const { t } = useTranslation()

  // Use custom breadcrumbs or generate from hook
  const defaultBreadcrumbs = useBreadcrumbs(basePath, breadcrumbOptions)
  const breadcrumbs = customBreadcrumbs ?? defaultBreadcrumbs

  const handleSearchKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && onSearchSubmit) {
      onSearchSubmit(searchValue)
    }
  }

  // Translate label if it contains a dot (i18n key)
  const translateLabel = (label: string) => {
    return label.includes('.') ? t(label) : label
  }

  return (
    <header className="h-16 flex items-center justify-between px-6 bg-surface-light dark:bg-surface-dark border-b border-slate-200 dark:border-border-dark flex-none shrink-0">
      {/* Left: Sidebar toggle + Mobile menu + Breadcrumbs */}
      <div className="flex items-center gap-3">
        {/* Sidebar Toggle Button */}
        {showSidebarToggle && onSidebarToggle && (
          <button
            onClick={onSidebarToggle}
            className="p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg transition-colors"
            aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {sidebarCollapsed ? (
              <PanelRight className="w-5 h-5" />
            ) : (
              <PanelLeft className="w-5 h-5" />
            )}
          </button>
        )}

        {showMobileMenu && onMobileMenuToggle && (
          <button
            onClick={onMobileMenuToggle}
            className="lg:hidden p-2 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-lg"
            aria-label="Toggle menu"
          >
            <Menu className="w-5 h-5" />
          </button>
        )}

        <div className="ml-1">
          <DefaultBreadcrumbs crumbs={breadcrumbs} />
        </div>
      </div>

      {/* Right: Actions */}
      <div className="flex items-center gap-4">
        {/* Search */}
        {showSearch && (
          <div className="relative hidden md:block group">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 group-focus-within:text-primary w-4 h-4 transition-colors" />
            <input
              type="text"
              value={searchValue}
              onChange={(e) => onSearchChange?.(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              placeholder="Search..."
              className="input-search w-64"
            />
          </div>
        )}

        {showThemeToggle && <ThemeToggle />}
        {showLanguageSwitcher && <LanguageSwitcher />}

        {/* Notifications */}
        {showNotifications && (
          <button
            onClick={onNotificationsClick}
            className="relative p-2 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors"
            aria-label="Notifications"
          >
            <Bell className="w-5 h-5" />
            {notificationCount > 0 && (
              <span className="absolute top-2 right-2 size-2 bg-red-500 rounded-full border-2 border-white dark:border-surface-dark" />
            )}
          </button>
        )}

        {/* Extra actions */}
        {extraActions}

        {/* Primary Action Button */}
        {primaryAction && (
          <Link to={primaryAction.to}>
            <button className="btn-primary">
              {primaryAction.icon}
              <span>{translateLabel(primaryAction.label)}</span>
            </button>
          </Link>
        )}

        {/* Divider before workspace switcher if we have actions */}
        {(showNotifications || primaryAction || extraActions) && showWorkspaceSwitcher && (
          <div className="h-6 w-px bg-slate-200 dark:bg-slate-700" />
        )}

        {/* Workspace Switcher */}
        {showWorkspaceSwitcher && (
          <div className={workspaceMode === 'project' ? 'w-48' : 'w-56'}>
            <WorkspaceSwitcher mode={workspaceMode} />
          </div>
        )}
      </div>
    </header>
  )
}

export default AppHeader

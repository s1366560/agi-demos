/**
 * AppHeader Component
 *
 * A reusable header component for application layouts.
 * Provides breadcrumbs, search, theme toggle, language switcher,
 * notifications, and action buttons.
 */

import * as React from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Search, Bell, Menu, PanelLeft, PanelRight, User, Settings, LogOut, ChevronDown } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { ThemeToggle } from '@/components/shared/ui/ThemeToggle'
import { LanguageSwitcher } from '@/components/shared/ui/LanguageSwitcher'
import { WorkspaceSwitcher } from '@/components/shared/ui/WorkspaceSwitcher'
import { useBreadcrumbs } from '@/hooks/useBreadcrumbs'
import { useUser, useAuthActions } from '@/stores/auth'

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
  /** Show user status bar */
  showUserStatus?: boolean
  /** User profile path */
  userProfilePath?: string
  /** User settings path */
  userSettingsPath?: string
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
/**
 * User Status Dropdown Component
 */
function UserStatusDropdown({
  userProfilePath = '/profile',
  userSettingsPath = '/settings',
}: {
  userProfilePath?: string
  userSettingsPath?: string
}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const user = useUser()
  const { logout } = useAuthActions()
  const [isOpen, setIsOpen] = React.useState(false)
  const dropdownRef = React.useRef<HTMLDivElement>(null)

  // Close dropdown when clicking outside
  React.useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleLogout = () => {
    logout()
    navigate('/login')
  }

  if (!user) return null

  // Get user initials for avatar fallback
  const getInitials = (name: string) => {
    return name
      .split(' ')
      .map(n => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2)
  }

  // Get display name
  const displayName = user.name || user.email.split('@')[0]
  const initials = getInitials(displayName)

  // Get avatar URL from profile
  const avatarUrl = user.profile?.avatar_url

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        aria-label="User menu"
      >
        {/* Avatar */}
        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-primary to-primary-dark flex items-center justify-center text-white text-sm font-medium overflow-hidden">
          {avatarUrl ? (
            <img src={avatarUrl} alt={displayName} className="w-full h-full object-cover" />
          ) : (
            initials
          )}
        </div>
        
        {/* User Info - hidden on small screens */}
        <div className="hidden sm:flex flex-col items-start">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-200 leading-tight">
            {displayName}
          </span>
          <span className="text-xs text-slate-500 dark:text-slate-400 leading-tight">
            {user.roles?.[0] || 'User'}
          </span>
        </div>
        
        <ChevronDown className={`w-4 h-4 text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <div className="absolute right-0 mt-2 w-56 bg-white dark:bg-surface-dark rounded-xl shadow-lg border border-slate-200 dark:border-slate-700 py-1 z-50">
          {/* User Info Header */}
          <div className="px-4 py-3 border-b border-slate-100 dark:border-slate-700">
            <p className="text-sm font-medium text-slate-900 dark:text-white truncate">
              {displayName}
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400 truncate">
              {user.email}
            </p>
          </div>

          {/* Menu Items */}
          <div className="py-1">
            <Link
              to={userProfilePath}
              onClick={() => setIsOpen(false)}
              className="flex items-center gap-3 px-4 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
            >
              <User className="w-4 h-4 text-slate-400" />
              {t('user.profile', '个人资料')}
            </Link>
            <Link
              to={userSettingsPath}
              onClick={() => setIsOpen(false)}
              className="flex items-center gap-3 px-4 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
            >
              <Settings className="w-4 h-4 text-slate-400" />
              {t('user.settings', '设置')}
            </Link>
          </div>

          {/* Divider */}
          <div className="border-t border-slate-100 dark:border-slate-700 my-1" />

          {/* Logout */}
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
          >
            <LogOut className="w-4 h-4" />
            {t('common.logout', '登出')}
          </button>
        </div>
      )}
    </div>
  )
}

export function AppHeader({
  context = 'tenant',
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
  showUserStatus = true,
  userProfilePath = '/profile',
  userSettingsPath = '/settings',
}: AppHeaderProps) {
  const { t } = useTranslation()

  // Use custom breadcrumbs or generate from hook
  const defaultBreadcrumbs = useBreadcrumbs(context, breadcrumbOptions)
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

        {/* Divider before user status */}
        {showUserStatus && (
          <div className="h-6 w-px bg-slate-200 dark:bg-slate-700" />
        )}

        {/* User Status */}
        {showUserStatus && (
          <UserStatusDropdown
            userProfilePath={userProfilePath}
            userSettingsPath={userSettingsPath}
          />
        )}
      </div>
    </header>
  )
}

export default AppHeader

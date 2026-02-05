/**
 * AppHeader Type Definitions
 *
 * Types for the new compound component API.
 */

import * as React from 'react'

/**
 * Header variant presets
 */
export type HeaderVariant = 'minimal' | 'compact' | 'full' | 'custom'

/**
 * Workspace mode
 */
export type WorkspaceMode = 'tenant' | 'project'

/**
 * Root AppHeader props
 */
export interface AppHeaderRootProps {
  /** Base path for navigation */
  basePath: string
  /** Layout context */
  context?: 'tenant' | 'project' | 'agent'
  /** Header variant (presets for common configurations) */
  variant?: HeaderVariant
}

/**
 * Sidebar toggle props
 */
export interface SidebarToggleProps {
  /** Current collapsed state */
  collapsed: boolean
  /** Callback when toggle is clicked */
  onToggle: () => void
  /** ARIA label for the button */
  ariaLabel?: string
}

/**
 * Mobile menu props
 */
export interface MobileMenuProps {
  /** Callback when menu toggle is clicked */
  onToggle: () => void
  /** ARIA label for the button */
  ariaLabel?: string
}

/**
 * Search props
 */
export interface SearchProps {
  /** Current search value */
  value?: string
  /** Callback when search value changes */
  onChange?: (value: string) => void
  /** Callback when search is submitted (Enter key) */
  onSubmit?: (value: string) => void
  /** Placeholder text */
  placeholder?: string
  /** ARIA label for the input */
  ariaLabel?: string
}

/**
 * Notifications props
 */
export interface NotificationsProps {
  /** Notification count for badge */
  count?: number
  /** Callback when notification bell is clicked */
  onClick?: () => void
  /** ARIA label for the button */
  ariaLabel?: string
}

/**
 * Tools container props
 */
export interface ToolsProps {
  /** Tool components to render */
  children: React.ReactNode
}

/**
 * Theme toggle props
 */
export interface ThemeToggleProps {
  /** Custom theme toggle component */
  as?: React.ElementType
}

/**
 * Language switcher props
 */
export interface LanguageSwitcherProps {
  /** Custom language switcher component */
  as?: React.ElementType
}

/**
 * Workspace switcher props
 */
export interface WorkspaceSwitcherProps {
  /** Workspace switcher mode */
  mode: WorkspaceMode
  /** Custom workspace switcher component */
  as?: React.ElementType
}

/**
 * User menu props
 */
export interface UserMenuProps {
  /** User profile path */
  profilePath?: string
  /** User settings path */
  settingsPath?: string
  /** Custom user menu component */
  as?: React.ElementType
}

/**
 * Primary action props
 */
export interface PrimaryActionProps {
  /** Button label (can be i18n key) */
  label: string
  /** Link destination */
  to: string
  /** Optional icon */
  icon?: React.ReactNode
  /** Button variant */
  variant?: 'primary' | 'secondary'
}

/**
 * Props for all compound components
 */
export interface CompoundComponentProps {
  SidebarToggle: React.FC<SidebarToggleProps>
  MobileMenu: React.FC<MobileMenuProps>
  Search: React.FC<SearchProps>
  Notifications: React.FC<NotificationsProps>
  Tools: React.FC<ToolsProps>
  ThemeToggle: React.FC<ThemeToggleProps>
  LanguageSwitcher: React.FC<LanguageSwitcherProps>
  WorkspaceSwitcher: React.FC<WorkspaceSwitcherProps>
  UserMenu: React.FC<UserMenuProps>
  PrimaryAction: React.FC<PrimaryActionProps>
}

/**
 * Context for sharing state between compound components
 */
export interface AppHeaderContextValue {
  basePath: string
  context?: 'tenant' | 'project' | 'agent'
}

/**
 * Legacy props for backward compatibility
 */
export interface LegacyAppHeaderProps {
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
  workspaceMode?: WorkspaceMode
  /** Primary action button */
  primaryAction?: {
    label: string
    to: string
    icon?: React.ReactNode
  }
  /** Additional actions to display on the right */
  extraActions?: React.ReactNode
  /** Show user status bar */
  showUserStatus?: boolean
  /** User profile path */
  userProfilePath?: string
  /** User settings path */
  userSettingsPath?: string
}

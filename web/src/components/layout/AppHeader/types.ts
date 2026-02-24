/**
 * AppHeader Type Definitions
 *
 * Types for the new compound component API.
 */

import * as React from 'react';

/**
 * Header variant presets
 */
export type HeaderVariant = 'minimal' | 'compact' | 'full' | 'custom';

/**
 * Workspace mode
 */
export type WorkspaceMode = 'tenant' | 'project';

/**
 * Breadcrumb item
 */
export interface Breadcrumb {
  label: string;
  path: string;
}

/**
 * Root AppHeader props
 */
export interface AppHeaderRootProps {
  /** Base path for navigation */
  basePath: string;
  /** Layout context */
  context?: 'tenant' | 'project' | 'agent' | undefined;
  /** Header variant (presets for common configurations) */
  variant?: HeaderVariant | undefined;
  /** Custom breadcrumbs to display */
  breadcrumbs?: Breadcrumb[] | undefined;
  /** Options for breadcrumb generation */
  breadcrumbOptions?: {
    skipFirst?: boolean | undefined;
  } | undefined;
}

/**
 * Sidebar toggle props
 */
export interface SidebarToggleProps {
  /** Current collapsed state */
  collapsed: boolean;
  /** Callback when toggle is clicked */
  onToggle: () => void;
  /** ARIA label for the button */
  ariaLabel?: string | undefined;
}

/**
 * Mobile menu props
 */
export interface MobileMenuProps {
  /** Callback when menu toggle is clicked */
  onToggle: () => void;
  /** ARIA label for the button */
  ariaLabel?: string | undefined;
}

/**
 * Search props
 */
export interface SearchProps {
  /** Current search value */
  value?: string | undefined;
  /** Callback when search value changes */
  onChange?: ((value: string) => void) | undefined;
  /** Callback when search is submitted (Enter key) */
  onSubmit?: ((value: string) => void) | undefined;
  /** Placeholder text */
  placeholder?: string | undefined;
  /** ARIA label for the input */
  ariaLabel?: string | undefined;
}

/**
 * Notifications props
 */
export interface NotificationsProps {
  /** Notification count for badge */
  count?: number | undefined;
  /** Callback when notification bell is clicked */
  onClick?: (() => void) | undefined;
  /** ARIA label for the button */
  ariaLabel?: string | undefined;
}

/**
 * Tools container props
 */
export interface ToolsProps {
  /** Tool components to render */
  children: React.ReactNode;
}

/**
 * Theme toggle props
 */
export interface ThemeToggleProps {
  /** Custom theme toggle component */
  as?: React.ElementType | undefined;
}

/**
 * Language switcher props
 */
export interface LanguageSwitcherProps {
  /** Custom language switcher component */
  as?: React.ElementType | undefined;
}

/**
 * Workspace switcher props
 */
export interface WorkspaceSwitcherProps {
  /** Workspace switcher mode */
  mode: WorkspaceMode;
  /** Custom workspace switcher component */
  as?: React.ElementType | undefined;
}

/**
 * User menu props
 */
export interface UserMenuProps {
  /** User profile path */
  profilePath?: string | undefined;
  /** User settings path */
  settingsPath?: string | undefined;
  /** Custom user menu component */
  as?: React.ElementType | undefined;
}

/**
 * Primary action props
 */
export interface PrimaryActionProps {
  /** Button label (can be i18n key) */
  label: string;
  /** Link destination */
  to: string;
  /** Optional icon */
  icon?: React.ReactNode | undefined;
  /** Button variant */
  variant?: 'primary' | 'secondary' | undefined;
}

/**
 * Props for all compound components
 */
export interface CompoundComponentProps {
  SidebarToggle: React.FC<SidebarToggleProps>;
  MobileMenu: React.FC<MobileMenuProps>;
  Search: React.FC<SearchProps>;
  Notifications: React.FC<NotificationsProps>;
  Tools: React.FC<ToolsProps>;
  ThemeToggle: React.FC<ThemeToggleProps>;
  LanguageSwitcher: React.FC<LanguageSwitcherProps>;
  WorkspaceSwitcher: React.FC<WorkspaceSwitcherProps>;
  UserMenu: React.FC<UserMenuProps>;
  PrimaryAction: React.FC<PrimaryActionProps>;
}

/**
 * Context for sharing state between compound components
 */
export interface AppHeaderContextValue {
  basePath: string;
  context?: 'tenant' | 'project' | 'agent' | undefined;
}

/**
 * Legacy props for backward compatibility
 */
export interface LegacyAppHeaderProps {
  /** Layout context for breadcrumbs */
  context?: 'tenant' | 'project' | 'agent' | undefined;
  /** Base path for navigation */
  basePath: string;
  /** Current project/tenant name for context */
  contextName?: string | undefined;
  /** Show sidebar toggle button */
  showSidebarToggle?: boolean | undefined;
  /** Sidebar collapsed state */
  sidebarCollapsed?: boolean | undefined;
  /** Callback when sidebar toggle is clicked */
  onSidebarToggle?: (() => void) | undefined;
  /** Show mobile menu button */
  showMobileMenu?: boolean | undefined;
  /** Callback when mobile menu is toggled */
  onMobileMenuToggle?: (() => void) | undefined;
  /** Show search input */
  showSearch?: boolean | undefined;
  /** Search input value */
  searchValue?: string | undefined;
  /** Callback when search value changes */
  onSearchChange?: ((value: string) => void) | undefined;
  /** Callback when search is submitted */
  onSearchSubmit?: ((value: string) => void) | undefined;
  /** Show notifications bell */
  showNotifications?: boolean | undefined;
  /** Notification count badge */
  notificationCount?: number | undefined;
  /** Callback when notification bell is clicked */
  onNotificationsClick?: (() => void) | undefined;
  /** Show theme toggle */
  showThemeToggle?: boolean | undefined;
  /** Show language switcher */
  showLanguageSwitcher?: boolean | undefined;
  /** Show workspace switcher */
  showWorkspaceSwitcher?: boolean | undefined;
  /** Workspace switcher mode */
  workspaceMode?: WorkspaceMode | undefined;
  /** Primary action button */
  primaryAction?: {
    label: string;
    to: string;
    icon?: React.ReactNode | undefined;
  } | undefined;
  /** Additional actions to display on the right */
  extraActions?: React.ReactNode | undefined;
  /** Show user status bar */
  showUserStatus?: boolean | undefined;
  /** User profile path */
  userProfilePath?: string | undefined;
  /** User settings path */
  userSettingsPath?: string | undefined;
}

/**
 * AppHeader - Compound Component Exports
 *
 * Main exports for the AppHeader compound component system.
 */

// Export default AppHeader with compound components
export { AppHeader as default } from './AppHeader'

// Export named AppHeader for explicit imports
export { AppHeader } from './AppHeader'

// Export individual subcomponents
export { SidebarToggle } from './SidebarToggle'
export { MobileMenu } from './MobileMenu'
export { Search } from './Search'
export { Notifications } from './Notifications'
export { Tools } from './Tools'
export { ThemeToggle } from './ThemeToggle'
export { LanguageSwitcher } from './LanguageSwitcher'
export { WorkspaceSwitcher } from './WorkspaceSwitcher'
export { UserMenu } from './UserMenu'
export { PrimaryAction } from './PrimaryAction'

// Export types
export type {
  Breadcrumb,
  AppHeaderRootProps,
  HeaderVariant,
  WorkspaceMode,
  SidebarToggleProps,
  MobileMenuProps,
  SearchProps,
  NotificationsProps,
  ToolsProps,
  ThemeToggleProps,
  LanguageSwitcherProps,
  WorkspaceSwitcherProps,
  UserMenuProps,
  PrimaryActionProps,
  AppHeaderContextValue,
  CompoundComponentProps,
  BreadcrumbOptions,
} from './types'

// Re-export types with aliases for convenience
import type { AppHeaderRootProps } from './types'
export type AppHeaderProps = AppHeaderRootProps

// Legacy AppHeader for backward compatibility
export { AppHeader as LegacyAppHeader } from '../AppHeader.legacy'
export type { AppHeaderProps as LegacyAppHeaderProps } from '../AppHeader.legacy'

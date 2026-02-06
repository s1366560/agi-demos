/**
 * Shared UI Components Barrel Export
 *
 * Generic UI components used across the application.
 */

export { LanguageSwitcher } from './LanguageSwitcher';
export { NotificationPanel } from './NotificationPanel';
export { ThemeToggle } from './ThemeToggle';

// WorkspaceSwitcher compound components
export {
  WorkspaceSwitcherRoot,
  WorkspaceSwitcherTrigger,
  WorkspaceSwitcherMenu,
  TenantWorkspaceSwitcher,
  ProjectWorkspaceSwitcher,
  TenantList,
  ProjectList,
  WorkspaceSwitcher as WorkspaceSwitcherCompound,
} from './WorkspaceSwitcher';

// Legacy WorkspaceSwitcher - exports the original for backward compatibility
export { WorkspaceSwitcher } from './WorkspaceSwitcher';
